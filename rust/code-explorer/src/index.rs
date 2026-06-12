//! Builds a code graph from a Rust source tree using `syn`.
//!
//! Nodes: `File`, `Function`, `Struct`, `Enum`, `Trait`.
//! Edges: `CONTAINS` (file -> item), `CALLS` (function -> function),
//! `IMPLEMENTS` (type -> trait), `METHOD_OF` (function -> type).

use std::collections::HashMap;
use std::path::Path;

use anyhow::{Context, Result};
use issundb::{Graph, NodeId, serde_json::json};
use syn::visit::Visit;
use walkdir::WalkDir;

#[derive(Clone)]
struct Item {
    name: String,
    kind: &'static str,
    file: String,
    /// Type name for methods (`impl Foo { fn bar }` -> `Some("Foo")`).
    self_ty: Option<String>,
    calls: Vec<String>,
}

pub fn index(graph: &Graph, root: &Path) -> Result<()> {
    let mut items: Vec<Item> = Vec::new();
    let mut impls: Vec<(String, String, String)> = Vec::new(); // (type, trait, file)
    let mut files: Vec<String> = Vec::new();

    for entry in WalkDir::new(root)
        .into_iter()
        .filter_entry(|e| e.file_name() != "target" && e.file_name() != ".git")
        .filter_map(Result::ok)
        .filter(|e| {
            e.file_type().is_file() && e.path().extension().and_then(|x| x.to_str()) == Some("rs")
        })
    {
        let path = entry.path();
        let rel = path
            .strip_prefix(root)
            .unwrap_or(path)
            .display()
            .to_string();
        let source =
            std::fs::read_to_string(path).with_context(|| format!("reading {}", path.display()))?;
        let Ok(ast) = syn::parse_file(&source) else {
            eprintln!("skipping {rel}: parse error");
            continue;
        };
        files.push(rel.clone());
        collect(&ast.items, &rel, None, &mut items, &mut impls);
    }
    anyhow::ensure!(
        !files.is_empty(),
        "no .rs files found under {}",
        root.display()
    );

    // ---- write the graph ----
    let mut file_ids: HashMap<String, NodeId> = HashMap::new();
    for file in &files {
        let id = graph.add_node("File", &json!({ "name": file }))?;
        file_ids.insert(file.clone(), id);
    }

    // name -> node ids (a name may be defined in several files)
    let mut by_name: HashMap<String, Vec<NodeId>> = HashMap::new();
    let mut type_ids: HashMap<String, NodeId> = HashMap::new();
    let mut node_of_item: Vec<NodeId> = Vec::with_capacity(items.len());

    for item in &items {
        let qualified = match &item.self_ty {
            Some(ty) => format!("{ty}::{}", item.name),
            None => item.name.clone(),
        };
        let id = graph.add_node(
            item.kind,
            &json!({ "name": item.name, "qualified": qualified, "file": item.file }),
        )?;
        by_name.entry(item.name.clone()).or_default().push(id);
        if matches!(item.kind, "Struct" | "Enum" | "Trait") {
            type_ids.insert(item.name.clone(), id);
        }
        graph.add_edge(file_ids[&item.file], id, "CONTAINS", &json!({}))?;
        node_of_item.push(id);
    }

    // CALLS edges resolve by bare name: ambiguous targets get one edge each,
    // which is the honest answer a name-level indexer can give.
    let mut n_calls = 0usize;
    for (item, src) in items.iter().zip(&node_of_item) {
        let mut seen: Vec<NodeId> = Vec::new();
        for callee in &item.calls {
            for dst in by_name.get(callee).into_iter().flatten() {
                if *dst != *src && !seen.contains(dst) {
                    graph.add_edge(*src, *dst, "CALLS", &json!({}))?;
                    seen.push(*dst);
                    n_calls += 1;
                }
            }
        }
    }

    // METHOD_OF and IMPLEMENTS edges.
    for (item, src) in items.iter().zip(&node_of_item) {
        if let Some(ty_id) = item.self_ty.as_ref().and_then(|ty| type_ids.get(ty)) {
            graph.add_edge(*src, *ty_id, "METHOD_OF", &json!({}))?;
        }
    }
    for (ty, tr, _file) in &impls {
        if let (Some(t), Some(r)) = (type_ids.get(ty), type_ids.get(tr)) {
            graph.add_edge(*t, *r, "IMPLEMENTS", &json!({}))?;
        }
    }

    graph.rebuild_csr()?;
    println!(
        "Indexed {} files: {} items, {} call edges.",
        files.len(),
        items.len(),
        n_calls
    );
    Ok(())
}

fn collect(
    syn_items: &[syn::Item],
    file: &str,
    self_ty: Option<&str>,
    out: &mut Vec<Item>,
    impls: &mut Vec<(String, String, String)>,
) {
    for item in syn_items {
        match item {
            syn::Item::Fn(f) => {
                let mut visitor = CallVisitor::default();
                visitor.visit_block(&f.block);
                out.push(Item {
                    name: f.sig.ident.to_string(),
                    kind: "Function",
                    file: file.to_owned(),
                    self_ty: self_ty.map(str::to_owned),
                    calls: visitor.calls,
                });
            }
            syn::Item::Struct(s) => out.push(plain(s.ident.to_string(), "Struct", file)),
            syn::Item::Enum(e) => out.push(plain(e.ident.to_string(), "Enum", file)),
            syn::Item::Trait(t) => {
                out.push(plain(t.ident.to_string(), "Trait", file));
                for ti in &t.items {
                    if let syn::TraitItem::Fn(f) = ti {
                        let calls = f
                            .default
                            .as_ref()
                            .map(|block| {
                                let mut v = CallVisitor::default();
                                v.visit_block(block);
                                v.calls
                            })
                            .unwrap_or_default();
                        out.push(Item {
                            name: f.sig.ident.to_string(),
                            kind: "Function",
                            file: file.to_owned(),
                            self_ty: Some(t.ident.to_string()),
                            calls,
                        });
                    }
                }
            }
            syn::Item::Impl(imp) => {
                let ty = type_name(&imp.self_ty);
                if let (Some(ty_name), Some((_, trait_path, _))) = (&ty, &imp.trait_) {
                    if let Some(seg) = trait_path.segments.last() {
                        impls.push((ty_name.clone(), seg.ident.to_string(), file.to_owned()));
                    }
                }
                for ii in &imp.items {
                    if let syn::ImplItem::Fn(f) = ii {
                        let mut visitor = CallVisitor::default();
                        visitor.visit_block(&f.block);
                        out.push(Item {
                            name: f.sig.ident.to_string(),
                            kind: "Function",
                            file: file.to_owned(),
                            self_ty: ty.clone(),
                            calls: visitor.calls,
                        });
                    }
                }
            }
            syn::Item::Mod(m) => {
                if let Some((_, nested)) = &m.content {
                    collect(nested, file, self_ty, out, impls);
                }
            }
            _ => {}
        }
    }
}

fn plain(name: String, kind: &'static str, file: &str) -> Item {
    Item {
        name,
        kind,
        file: file.to_owned(),
        self_ty: None,
        calls: Vec::new(),
    }
}

fn type_name(ty: &syn::Type) -> Option<String> {
    if let syn::Type::Path(p) = ty {
        p.path.segments.last().map(|s| s.ident.to_string())
    } else {
        None
    }
}

/// Records the last path segment of every call and method-call expression.
#[derive(Default)]
struct CallVisitor {
    calls: Vec<String>,
}

impl<'ast> Visit<'ast> for CallVisitor {
    fn visit_expr_call(&mut self, call: &'ast syn::ExprCall) {
        if let syn::Expr::Path(p) = call.func.as_ref() {
            if let Some(seg) = p.path.segments.last() {
                self.calls.push(seg.ident.to_string());
            }
        }
        syn::visit::visit_expr_call(self, call);
    }

    fn visit_expr_method_call(&mut self, call: &'ast syn::ExprMethodCall) {
        self.calls.push(call.method.to_string());
        syn::visit::visit_expr_method_call(self, call);
    }
}
