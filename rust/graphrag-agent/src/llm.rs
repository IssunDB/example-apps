//! Optional answer generation through the Claude API.
//!
//! The example is fully functional offline; when `ANTHROPIC_API_KEY` is set
//! the retrieved context is handed to Claude to produce a grounded answer.

use anyhow::{Context, Result};
use issundb::serde_json::{Value, json};

const API_URL: &str = "https://api.anthropic.com/v1/messages";
const DEFAULT_MODEL: &str = "claude-opus-4-8";

/// Returns `Ok(None)` when no API key is configured.
pub fn answer(question: &str, context: &str) -> Result<Option<String>> {
    let Ok(api_key) = std::env::var("ANTHROPIC_API_KEY") else {
        return Ok(None);
    };
    let model = std::env::var("ANTHROPIC_MODEL").unwrap_or_else(|_| DEFAULT_MODEL.to_owned());

    let body = json!({
        "model": model,
        "max_tokens": 1024,
        "system": "You answer questions using ONLY the provided context, which was \
                   retrieved from a knowledge graph. Cite the source documents you used. \
                   If the context does not contain the answer, say so plainly.",
        "messages": [{
            "role": "user",
            "content": format!("<context>\n{context}\n</context>\n\nQuestion: {question}"),
        }],
    });

    let response: Value = ureq::post(API_URL)
        .set("x-api-key", &api_key)
        .set("anthropic-version", "2023-06-01")
        .set("content-type", "application/json")
        .send_json(body)
        .context("Claude API request failed")?
        .into_json()
        .context("Claude API returned malformed JSON")?;

    if response["stop_reason"] == "refusal" {
        anyhow::bail!("the model declined to answer this request");
    }

    let text = response["content"]
        .as_array()
        .into_iter()
        .flatten()
        .filter(|block| block["type"] == "text")
        .filter_map(|block| block["text"].as_str())
        .collect::<Vec<_>>()
        .join("");
    Ok(Some(text))
}
