//! Optional answer generation through the OpenRouter API.
//!
//! The example is fully functional offline; when `OPENROUTER_API_KEY` is set
//! the retrieved context is handed to OpenRouter to produce a grounded answer.

use anyhow::{Context, Result};
use issundb::serde_json::{Value, json};

const API_URL: &str = "https://openrouter.ai/api/v1/chat/completions";
const DEFAULT_MODEL: &str = "openai/gpt-5.4-mini";

/// Returns `Ok(None)` when no API key is configured.
pub fn answer(question: &str, context: &str) -> Result<Option<String>> {
    let Ok(api_key) = std::env::var("OPENROUTER_API_KEY") else {
        return Ok(None);
    };
    let model = std::env::var("OPENROUTER_MODEL").unwrap_or_else(|_| DEFAULT_MODEL.to_owned());

    let body = json!({
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You answer questions using ONLY the provided context, which was \
                           retrieved from a knowledge graph. Cite the source documents you used. \
                           If the context does not contain the answer, say so plainly."
            },
            {
                "role": "user",
                "content": format!("<context>\n{context}\n</context>\n\nQuestion: {question}"),
            }
        ],
    });

    let response: Value = ureq::post(API_URL)
        .set("Authorization", &format!("Bearer {api_key}"))
        .set("content-type", "application/json")
        .send_json(body)
        .context("OpenRouter API request failed")?
        .into_json()
        .context("OpenRouter API returned malformed JSON")?;

    let text = response["choices"][0]["message"]["content"]
        .as_str()
        .context("OpenRouter API returned response without message content")?
        .to_owned();
    Ok(Some(text))
}
