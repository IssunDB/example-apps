//! Document ingestion: chunking, entity extraction, and graph construction.

use std::collections::HashMap;
use std::path::Path;

use anyhow::{Context, Result};
use issundb::{Graph, NodeId, TextIndexExt, VectorGraphExt, VectorIndexOptions, serde_json::json};
use walkdir::WalkDir;

use crate::embed;

/// Soft target for chunk size in characters; paragraphs are merged up to it.
///
/// Kept below 480 because IssunDB (0.1.0-alpha.5) auto-indexes every string
/// property and LMDB caps index keys at ~511 bytes — longer `text` values
/// make `add_node` fail with `MDB_BAD_VALSIZE`.
const CHUNK_TARGET: usize = 400;
/// Hard ceiling enforced by splitting on word boundaries.
const CHUNK_MAX: usize = 470;

/// Leading words that never start an entity name.
const STOPWORDS: &[&str] = &[
    "The", "A", "An", "In", "On", "At", "It", "Its", "This", "That", "These", "Those", "By", "For",
    "From", "With", "When", "Where", "While", "After", "Before", "During", "Each", "Every", "Both",
    "But", "And", "Or", "If", "As", "To", "Of", "Not", "All", "Some",
];

struct DocChunks {
    title: String,
    path: String,
    chunks: Vec<String>,
}

/// Ingest every `.md`/`.txt` file under `dir` into the graph.
pub fn ingest(graph: &Graph, dir: &Path) -> Result<()> {
    graph.configure_vector_index(VectorIndexOptions::default())?;
    if !graph.has_text_index("Chunk", "text")? {
        graph.create_text_index("Chunk", "text")?;
    }

    let docs = load_documents(dir)?;
    anyhow::ensure!(
        !docs.is_empty(),
        "no .md or .txt files found under {}",
        dir.display()
    );

    // entity name -> node id, created lazily across all documents
    let mut entities: HashMap<String, NodeId> = HashMap::new();
    // (entity a, entity b) -> co-occurrence count, flushed at the end
    let mut co_occurs: HashMap<(NodeId, NodeId), u32> = HashMap::new();
    let mut n_chunks = 0usize;

    for doc in &docs {
        let doc_id =
            graph.add_node("Document", &json!({ "path": doc.path, "title": doc.title }))?;
        let mut prev: Option<NodeId> = None;

        for (seq, text) in doc.chunks.iter().enumerate() {
            let chunk_id = graph.add_node(
                "Chunk",
                &json!({ "doc": doc.title, "seq": seq as i64, "text": text }),
            )?;
            graph.add_edge(doc_id, chunk_id, "HAS_CHUNK", &json!({ "seq": seq as i64 }))?;
            if let Some(p) = prev {
                graph.add_edge(p, chunk_id, "NEXT", &json!({}))?;
            }
            prev = Some(chunk_id);

            graph.upsert_vector(chunk_id, &embed::embed(text))?;

            let mentioned = extract_entities(text);
            let mut ids: Vec<NodeId> = Vec::new();
            for (name, count) in &mentioned {
                let eid = match entities.get(name) {
                    Some(id) => *id,
                    None => {
                        let id = graph.add_node("Entity", &json!({ "name": name }))?;
                        entities.insert(name.clone(), id);
                        id
                    }
                };
                graph.add_edge(
                    chunk_id,
                    eid,
                    "MENTIONS",
                    &json!({ "count": *count as i64 }),
                )?;
                ids.push(eid);
            }
            ids.sort_unstable();
            for i in 0..ids.len() {
                for j in (i + 1)..ids.len() {
                    *co_occurs.entry((ids[i], ids[j])).or_insert(0) += 1;
                }
            }
            n_chunks += 1;
        }
    }

    for ((a, b), weight) in &co_occurs {
        graph.add_edge(*a, *b, "CO_OCCURS", &json!({ "weight": *weight as i64 }))?;
    }

    // Refresh the in-memory adjacency (CSR) after the bulk load so traversals
    // and Cypher run against the freshly written graph.
    graph.rebuild_csr()?;

    println!(
        "Ingested {} documents: {} chunks, {} entities, {} co-occurrence edges.",
        docs.len(),
        n_chunks,
        entities.len(),
        co_occurs.len()
    );
    Ok(())
}

fn load_documents(dir: &Path) -> Result<Vec<DocChunks>> {
    let mut docs = Vec::new();
    let mut paths: Vec<_> = WalkDir::new(dir)
        .into_iter()
        .filter_map(Result::ok)
        .filter(|e| {
            e.file_type().is_file()
                && matches!(
                    e.path().extension().and_then(|x| x.to_str()),
                    Some("md") | Some("txt")
                )
        })
        .map(|e| e.into_path())
        .collect();
    paths.sort();

    for path in paths {
        let text = std::fs::read_to_string(&path)
            .with_context(|| format!("reading {}", path.display()))?;
        let title = text
            .lines()
            .find_map(|l| l.strip_prefix("# "))
            .map(str::to_owned)
            .unwrap_or_else(|| {
                path.file_stem()
                    .map(|s| s.to_string_lossy().into_owned())
                    .unwrap_or_default()
            });
        docs.push(DocChunks {
            title,
            path: path.display().to_string(),
            chunks: chunk(&text),
        });
    }
    Ok(docs)
}

/// Split on blank lines, merging consecutive paragraphs up to `CHUNK_TARGET`.
fn chunk(text: &str) -> Vec<String> {
    let mut chunks: Vec<String> = Vec::new();
    let mut current = String::new();

    for para in text.split("\n\n") {
        let para = para.trim();
        if para.is_empty() || para.starts_with('#') {
            continue;
        }
        if !current.is_empty() && current.len() + para.len() > CHUNK_TARGET {
            chunks.push(std::mem::take(&mut current));
        }
        if !current.is_empty() {
            current.push_str("\n\n");
        }
        current.push_str(para);
        // Hard-split oversized paragraphs on word boundaries.
        while current.len() > CHUNK_MAX {
            let cut = current[..CHUNK_MAX]
                .rfind(char::is_whitespace)
                .unwrap_or(CHUNK_MAX);
            let rest = current.split_off(cut);
            chunks.push(std::mem::take(&mut current));
            current = rest.trim_start().to_owned();
        }
    }
    if !current.is_empty() {
        chunks.push(current);
    }
    chunks
}

/// Heuristic named-entity extraction: runs of capitalized words.
///
/// A real pipeline would use an NER model or an LLM here; runs of TitleCase
/// words are a serviceable stand-in for demo corpora and keep the example
/// dependency-free.
fn extract_entities(text: &str) -> HashMap<String, u32> {
    // Title abbreviations end with '.' but do not end a sentence.
    const TITLES: &[&str] = &["Dr", "Mr", "Ms", "Mrs", "Prof", "St"];

    let mut found: HashMap<String, u32> = HashMap::new();
    let mut run: Vec<&str> = Vec::new();
    let mut sentence_start = true;

    for word in text.split_whitespace() {
        let clean = word.trim_matches(|c: char| !c.is_alphanumeric());
        let clean = clean
            .strip_suffix("'s")
            .or(clean.strip_suffix("’s"))
            .unwrap_or(clean);
        let is_cap = clean.chars().next().is_some_and(|c| c.is_uppercase())
            && clean.chars().any(|c| c.is_lowercase());
        let is_title = TITLES.contains(&clean);

        // Skip the first word of each sentence: capitalization there carries
        // no signal. Titles are skipped too but keep the run alive.
        if is_cap && !sentence_start && !is_title && !STOPWORDS.contains(&clean) {
            run.push(clean);
        } else if !is_title {
            flush_run(&mut run, &mut found);
        }

        sentence_start = !is_title && word.ends_with(['.', '!', '?', ':', ';']);
    }
    flush_run(&mut run, &mut found);
    found
}

fn flush_run(run: &mut Vec<&str>, found: &mut HashMap<String, u32>) {
    if !run.is_empty() {
        let name = run.join(" ");
        if name.len() > 2 {
            *found.entry(name).or_insert(0) += 1;
        }
        run.clear();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn extracts_multiword_entities() {
        let found =
            extract_entities("Funding for the Aster Program was approved by Dr. Mara Voss.");
        assert!(found.contains_key("Aster Program"), "{found:?}");
        assert!(found.contains_key("Mara Voss"), "{found:?}");
    }

    #[test]
    fn skips_sentence_initial_words() {
        let found = extract_entities("Engineers tested the thruster. Results were good.");
        assert!(found.is_empty(), "{found:?}");
    }

    #[test]
    fn chunking_merges_short_paragraphs() {
        let text = "para one.\n\npara two.\n\npara three.";
        let chunks = chunk(text);
        assert_eq!(chunks.len(), 1);
        assert!(chunks[0].contains("para three"));
    }
}
