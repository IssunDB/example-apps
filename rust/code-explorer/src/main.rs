//! Code Navigator: a semantic code graph for Rust projects, backed by IssunDB.
//!
//! Showcases the embedded side of IssunDB: a single self-contained binary
//! parses a source tree into a graph and answers structural questions with
//! Cypher, native traversals, and the GraphBLAS-backed analytics engine
//! (PageRank, connected components, cycle detection).

mod index;

use std::collections::HashMap;
use std::path::PathBuf;

use anyhow::{Context, Result};
use clap::{Parser, Subcommand};
use issundb::{Graph, GraphQueryExt, NodeId, PropValue, serde_json::Value};

#[derive(Parser)]
#[command(about = "Navigate a Rust codebase as a graph (IssunDB example)")]
struct Cli {
    /// Path to the IssunDB database directory.
    #[arg(long, default_value = "./codegraph-data")]
    db: PathBuf,
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// Parse a Rust source tree and (re)build the code graph.
    Index { path: PathBuf },
    /// Show graph statistics.
    Stats,
    /// Who calls this function?
    Callers { name: String },
    /// What does this function call?
    Callees { name: String },
    /// Functions that nothing calls (dead-code candidates).
    Dead,
    /// Everything transitively affected if this function changes.
    Impact { name: String },
    /// Most structurally important functions (PageRank over the code graph).
    Rank {
        #[arg(long, default_value_t = 15)]
        top: usize,
    },
    /// Connected components and reference cycles across the code graph.
    Structure,
    /// Shortest call path between two functions.
    Path { from: String, to: String },
    /// Run a raw Cypher query against the code graph.
    Query { cypher: String },
}

fn main() -> Result<()> {
    let cli = Cli::parse();

    if matches!(cli.command, Command::Index { .. }) && cli.db.exists() {
        std::fs::remove_dir_all(&cli.db)?;
    }
    let graph = Graph::open(&cli.db, 1).with_context(|| format!("opening {}", cli.db.display()))?;

    match cli.command {
        Command::Index { path } => index::index(&graph, &path),
        Command::Stats => stats(&graph),
        Command::Callers { name } => relation(&graph, &name, Direction::Callers),
        Command::Callees { name } => relation(&graph, &name, Direction::Callees),
        Command::Dead => dead(&graph),
        Command::Impact { name } => impact(&graph, &name),
        Command::Rank { top } => rank(&graph, top),
        Command::Structure => structure(&graph),
        Command::Path { from, to } => path(&graph, &from, &to),
        Command::Query { cypher } => query(&graph, &cypher),
    }
}

fn stats(graph: &Graph) -> Result<()> {
    for label in ["File", "Function", "Struct", "Enum", "Trait"] {
        println!("{label:<10} {}", graph.node_count_by_label(label)?);
    }
    for etype in ["CONTAINS", "CALLS", "METHOD_OF", "IMPLEMENTS"] {
        println!("{etype:<10} {}", graph.edge_count_by_type(etype)?);
    }
    Ok(())
}

enum Direction {
    Callers,
    Callees,
}

fn relation(graph: &Graph, name: &str, direction: Direction) -> Result<()> {
    let (pattern, what) = match direction {
        Direction::Callers => (
            "MATCH (caller:Function)-[:CALLS]->(f:Function {name: $name}) \
              RETURN caller.qualified, caller.file ORDER BY caller.qualified",
            "callers",
        ),
        Direction::Callees => (
            "MATCH (f:Function {name: $name})-[:CALLS]->(callee:Function) \
              RETURN callee.qualified, callee.file ORDER BY callee.qualified",
            "callees",
        ),
    };
    let params = HashMap::from([("name".to_owned(), Value::String(name.to_owned()))]);
    let result = graph.query_with_params(pattern, &params)?;
    if result.records.is_empty() {
        println!("no {what} found for {name:?}");
        return Ok(());
    }
    for record in result.records {
        println!(
            "{:<40} {}",
            display(&record.values[0]),
            display(&record.values[1])
        );
    }
    Ok(())
}

fn dead(graph: &Graph) -> Result<()> {
    let result = graph.query(
        "MATCH (f:Function) OPTIONAL MATCH (caller:Function)-[:CALLS]->(f) \
         WITH f, COUNT(caller) AS callers WHERE callers = 0 AND f.name <> 'main' \
         RETURN f.qualified, f.file ORDER BY f.file, f.qualified",
    )?;
    if result.records.is_empty() {
        println!("no dead-code candidates 🎉");
        return Ok(());
    }
    println!("functions with no callers (candidates — entry points and trait impls may be live):");
    for record in result.records {
        println!(
            "  {:<40} {}",
            display(&record.values[0]),
            display(&record.values[1])
        );
    }
    Ok(())
}

/// Reverse-BFS over CALLS edges using the native adjacency API.
fn impact(graph: &Graph, name: &str) -> Result<()> {
    let start = function_ids(graph, name)?;
    anyhow::ensure!(!start.is_empty(), "no function named {name:?}");

    let calls_type = "CALLS";
    let mut frontier = start.clone();
    let mut visited: Vec<NodeId> = start.clone();
    let mut depth = 0u32;
    while !frontier.is_empty() && depth < 32 {
        let mut next = Vec::new();
        for node in &frontier {
            for entry in graph.in_neighbors(*node)? {
                let etype = graph.type_name(entry.edge_type)?.unwrap_or_default();
                if etype == calls_type && !visited.contains(&entry.node) {
                    visited.push(entry.node);
                    next.push(entry.node);
                }
            }
        }
        frontier = next;
        depth += 1;
    }

    let affected: Vec<NodeId> = visited.into_iter().filter(|n| !start.contains(n)).collect();
    println!("{} function(s) transitively call {name:?}:", affected.len());
    let mut lines: Vec<String> = affected
        .iter()
        .map(|n| prop_string(graph, *n, "qualified"))
        .collect::<Result<_>>()?;
    lines.sort();
    for line in lines {
        println!("  {line}");
    }
    Ok(())
}

fn rank(graph: &Graph, top: usize) -> Result<()> {
    // PageRank runs over every edge type (CALLS, CONTAINS, METHOD_OF,
    // IMPLEMENTS), so the score is whole-code-graph centrality, not pure
    // call-graph importance; we then keep only the Function nodes.
    let scores = graph.page_rank(30, 0.85)?;
    let functions = graph.nodes_by_label("Function")?;
    let mut ranked: Vec<(NodeId, f32)> = functions
        .into_iter()
        .filter_map(|n| scores.get(&n).map(|s| (n, *s)))
        .collect();
    ranked.sort_by(|a, b| b.1.total_cmp(&a.1));

    println!("most central functions (PageRank over the code graph):");
    for (node, score) in ranked.into_iter().take(top) {
        println!(
            "  {score:.5}  {:<36} {}",
            prop_string(graph, node, "qualified")?,
            prop_string(graph, node, "file")?
        );
    }
    Ok(())
}

fn structure(graph: &Graph) -> Result<()> {
    let components = graph.connected_components()?;
    let mut sizes: HashMap<u64, usize> = HashMap::new();
    for component in components.values() {
        *sizes.entry(*component).or_insert(0) += 1;
    }
    let mut sizes: Vec<usize> = sizes.into_values().collect();
    sizes.sort_unstable_by(|a, b| b.cmp(a));
    println!(
        "{} weakly connected component(s); largest sizes: {:?}",
        sizes.len(),
        &sizes[..sizes.len().min(8)]
    );
    // detect_cycle spans all edge types; in this schema a cycle is almost
    // always CALLS recursion, but it is not restricted to it.
    println!(
        "cycle present: {}",
        if graph.detect_cycle()? { "yes" } else { "no" }
    );
    Ok(())
}

fn path(graph: &Graph, from: &str, to: &str) -> Result<()> {
    let src = function_ids(graph, from)?;
    let dst = function_ids(graph, to)?;
    anyhow::ensure!(!src.is_empty(), "no function named {from:?}");
    anyhow::ensure!(!dst.is_empty(), "no function named {to:?}");

    for s in &src {
        for d in &dst {
            if let Some(found) = graph.shortest_path(*s, *d)? {
                let names: Vec<String> = found
                    .iter()
                    .map(|n| prop_string(graph, *n, "qualified"))
                    .collect::<Result<_>>()?;
                println!("{}", names.join(" -> "));
                return Ok(());
            }
        }
    }
    println!("no call path from {from:?} to {to:?}");
    Ok(())
}

fn query(graph: &Graph, cypher: &str) -> Result<()> {
    let result = graph.query(cypher)?;
    println!("{}", result.columns.join(" | "));
    let count = result.records.len();
    for record in result.records {
        let row: Vec<String> = record.values.iter().map(display).collect();
        println!("{}", row.join(" | "));
    }
    println!("({count} rows)");
    Ok(())
}

fn function_ids(graph: &Graph, name: &str) -> Result<Vec<NodeId>> {
    Ok(graph.nodes_by_property("Function", "name", PropValue::Str(name.to_owned()))?)
}

fn prop_string(graph: &Graph, node: NodeId, prop: &str) -> Result<String> {
    Ok(graph
        .node_prop_json(node, prop)?
        .and_then(|v| v.as_str().map(str::to_owned))
        .unwrap_or_default())
}

fn display(value: &Value) -> String {
    match value {
        Value::String(s) => s.clone(),
        other => other.to_string(),
    }
}
