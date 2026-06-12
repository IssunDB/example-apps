//! Deterministic local embeddings via feature hashing.
//!
//! Real deployments would call an embedding model here. For a self-contained
//! example we hash token bigrams and unigrams into a fixed-size vector
//! (the "hashing trick"), which gives stable, useful similarity for
//! bag-of-words style matching without any external service.

/// Embedding dimensionality. Must match across ingestion and queries.
pub const DIM: usize = 256;

/// FNV-1a, fixed parameters: stable across platforms and Rust versions,
/// unlike `DefaultHasher`.
fn fnv1a(bytes: &[u8]) -> u64 {
    let mut hash: u64 = 0xcbf2_9ce4_8422_2325;
    for b in bytes {
        hash ^= u64::from(*b);
        hash = hash.wrapping_mul(0x0000_0100_0000_01b3);
    }
    hash
}

fn tokens(text: &str) -> Vec<String> {
    text.to_lowercase()
        .split(|c: char| !c.is_alphanumeric())
        .filter(|t| t.len() > 1)
        .map(str::to_owned)
        .collect()
}

/// Embed `text` into an L2-normalized `DIM`-dimensional vector.
pub fn embed(text: &str) -> Vec<f32> {
    let toks = tokens(text);
    let mut v = vec![0.0f32; DIM];

    let mut bump = |feature: &str, weight: f32| {
        let h = fnv1a(feature.as_bytes());
        let idx = (h % DIM as u64) as usize;
        // Use a high bit for the sign so collisions partially cancel
        // instead of compounding.
        let sign = if h & (1 << 63) == 0 { 1.0 } else { -1.0 };
        v[idx] += sign * weight;
    };

    for tok in &toks {
        bump(tok, 1.0);
    }
    for pair in toks.windows(2) {
        bump(&format!("{} {}", pair[0], pair[1]), 0.5);
    }

    let norm = v.iter().map(|x| x * x).sum::<f32>().sqrt();
    if norm > 0.0 {
        for x in &mut v {
            *x /= norm;
        }
    }
    v
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn deterministic() {
        assert_eq!(embed("ion thruster design"), embed("ion thruster design"));
    }

    #[test]
    fn normalized() {
        let v = embed("the Helia probe studies the solar corona");
        let norm = v.iter().map(|x| x * x).sum::<f32>().sqrt();
        assert!((norm - 1.0).abs() < 1e-5);
    }

    #[test]
    fn related_text_is_closer_than_unrelated() {
        let cos = |a: &[f32], b: &[f32]| -> f32 { a.iter().zip(b).map(|(x, y)| x * y).sum() };
        let q = embed("ion propulsion engine thrust");
        let related = embed("the ion propulsion system produces thrust");
        let unrelated = embed("the cafeteria menu lists soup on Tuesday");
        assert!(cos(&q, &related) > cos(&q, &unrelated));
    }
}
