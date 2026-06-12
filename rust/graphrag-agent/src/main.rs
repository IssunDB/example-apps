//! GraphRAG pipeline built on IssunDB.
//!
//! Showcases hybrid retrieval: vector search and BM25 text search fused with
//! reciprocal-rank fusion, then expanded through graph structure so the
//! answer context includes related chunks and entities that pure vector
//! similarity would miss. Works fully offline; set `OPENROUTER_API_KEY` to
//! have the model generate the final answer from the retrieved context.

mod embed;
mod ingest;
mod llm;

use std::collections::HashMap;
use std::path::PathBuf;

use anyhow::{Context, Result};
use clap::{Parser, Subcommand};
use issundb::{
    FusionStrategy, Graph, GraphQueryExt, HybridRetrieveOptions, NodeId, retrieve_hybrid,
    serde_json::Value,
};

#[derive(Parser)]
#[command(about = "GraphRAG pipeline: hybrid (vector + text + graph) retrieval over documents")]
struct Cli {
    /// Path to the IssunDB database directory.
    #[arg(long, default_value = "./rag-data")]
    db: PathBuf,
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// Parse, chunk, embed, and link documents from a directory.
    Ingest {
        /// Directory containing .md / .txt files (try ./sample_docs).
        dir: PathBuf,
    },
    /// Ask a question against the ingested corpus.
    Ask {
        question: String,
        /// Number of context chunks to assemble.
        #[arg(long, default_value_t = 5)]
        k: usize,
        /// Graph expansion depth around retrieval seeds.
        #[arg(long, default_value_t = 1)]
        hops: u8,
        /// Print the retrieved context even when an LLM answer is generated.
        #[arg(long)]
        show_context: bool,
    },
    /// List the most-mentioned entities in the corpus.
    Entities {
        #[arg(long, default_value_t = 15)]
        top: usize,
    },
    /// Show the graph neighborhood of an entity.
    Related { entity: String },
}

fn main() -> Result<()> {
    let cli = Cli::parse();

    if let Command::Ingest { .. } = cli.command {
        // Each ingest run rebuilds the database from scratch.
        if cli.db.exists() {
            std::fs::remove_dir_all(&cli.db)?;
        }
    }
    let graph = Graph::open(&cli.db, 1).with_context(|| format!("opening {}", cli.db.display()))?;

    match cli.command {
        Command::Ingest { dir } => ingest::ingest(&graph, &dir),
        Command::Ask {
            question,
            k,
            hops,
            show_context,
        } => ask(&graph, &question, k, hops, show_context),
        Command::Entities { top } => entities(&graph, top),
        Command::Related { entity } => related(&graph, &entity),
    }
}

fn ask(graph: &Graph, question: &str, k: usize, hops: u8, show_context: bool) -> Result<()> {
    let qvec = embed::embed(question);
    let opts = HybridRetrieveOptions {
        vector_k: k,
        text_k: k,
        text_label: Some("Chunk".to_owned()),
        text_property: Some("text".to_owned()),
        vector_label: Some("Chunk".to_owned()),
        hops,
        max_nodes: Some(64),
        fusion: FusionStrategy::Rrf { k: 60 },
        ..Default::default()
    };
    let subgraph = retrieve_hybrid(graph, &qvec, question, &opts)?;

    // Keep the top-scored Chunk nodes; the graph expansion may also pull in
    // Document and Entity nodes, which we surface separately.
    let mut chunks: Vec<(NodeId, f32)> = Vec::new();
    let mut entity_names: Vec<String> = Vec::new();
    for node in &subgraph.nodes {
        let labels = graph.node_labels(*node)?;
        let score = subgraph.scores.get(node).copied().unwrap_or(0.0);
        if labels.iter().any(|l| l == "Chunk") {
            chunks.push((*node, score));
        } else if labels.iter().any(|l| l == "Entity") {
            entity_names.push(prop_string(graph, *node, "name")?);
        }
    }
    chunks.sort_by(|a, b| b.1.total_cmp(&a.1));
    chunks.truncate(k);
    anyhow::ensure!(
        !chunks.is_empty(),
        "no results — did you run `ingest` first?"
    );

    let mut context = String::new();
    for (node, _) in &chunks {
        let doc = prop_string(graph, *node, "doc")?;
        let text = prop_string(graph, *node, "text")?;
        context.push_str(&format!("[source: {doc}]\n{text}\n\n"));
    }

    let answer = llm::answer(question, &context)?;
    if answer.is_none() || show_context {
        println!(
            "=== Retrieved context ({} chunks, {hops}-hop graph expansion) ===\n",
            chunks.len()
        );
        print!("{context}");
        if !entity_names.is_empty() {
            entity_names.sort();
            entity_names.dedup();
            println!("Related entities: {}\n", entity_names.join(", "));
        }
    }
    match answer {
        Some(text) => println!("=== Answer ===\n\n{text}"),
        None => println!("(Set OPENROUTER_API_KEY to generate an answer from this context.)"),
    }
    Ok(())
}

fn entities(graph: &Graph, top: usize) -> Result<()> {
    let result = graph.query(&format!(
        "MATCH (c:Chunk)-[m:MENTIONS]->(e:Entity) \
         RETURN e.name AS entity, COUNT(c) AS mentions \
         ORDER BY mentions DESC, entity LIMIT {top}"
    ))?;
    println!("{:<32} mentions", "entity");
    for record in result.records {
        println!("{:<32} {}", display(&record.values[0]), record.values[1]);
    }
    Ok(())
}

fn related(graph: &Graph, entity: &str) -> Result<()> {
    let params = HashMap::from([("name".to_owned(), Value::String(entity.to_owned()))]);

    let sources = graph.query_with_params(
        "MATCH (c:Chunk)-[:MENTIONS]->(e:Entity {name: $name}) RETURN c.doc",
        &params,
    )?;
    anyhow::ensure!(!sources.records.is_empty(), "no entity named {entity:?}");
    let mut docs: Vec<String> = sources
        .records
        .iter()
        .map(|r| display(&r.values[0]))
        .collect();
    docs.sort();
    docs.dedup();

    // CO_OCCURS edges were written in one canonical direction, so query both.
    let mut co: Vec<(String, i64)> = Vec::new();
    for pattern in [
        "MATCH (e:Entity {name: $name})-[r:CO_OCCURS]->(o:Entity) RETURN o.name, r.weight",
        "MATCH (o:Entity)-[r:CO_OCCURS]->(e:Entity {name: $name}) RETURN o.name, r.weight",
    ] {
        for record in graph.query_with_params(pattern, &params)?.records {
            co.push((
                display(&record.values[0]),
                record.values[1].as_i64().unwrap_or(0),
            ));
        }
    }
    co.sort_by(|a, b| b.1.cmp(&a.1).then(a.0.cmp(&b.0)));

    println!("Entity: {entity}");
    println!("Mentioned in: {}", docs.join(", "));
    println!("Co-occurs with:");
    for (name, weight) in co.into_iter().take(15) {
        println!("  {name:<32} ({weight} shared chunks)");
    }
    Ok(())
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
