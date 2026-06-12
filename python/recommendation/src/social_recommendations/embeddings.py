"""Deterministic interest-vector embeddings.

No ML dependencies: each topic gets a fixed pseudo-random basis vector derived
from a hash of its name, user vectors are normalized weighted sums of their
topic affinities, and post vectors are normalized sums of their topics' bases
plus a small content-hash perturbation. All vectors are L2-normalized, so the
vector index should be configured with the ``"cosine"`` metric.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence

import numpy as np

#: Dimensionality of every embedding produced by this module.
DIM = 64

_BASIS_CACHE: dict[str, np.ndarray] = {}


def _stable_seed(text: str) -> int:
    """Return a deterministic 64-bit seed derived from ``text``."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def normalize(vec: np.ndarray) -> np.ndarray:
    """L2-normalize ``vec``, returning it unchanged if it has zero norm."""
    norm = float(np.linalg.norm(vec))
    if norm == 0.0:
        return vec.astype(np.float64)
    return (vec / norm).astype(np.float64)


def topic_basis(topic: str) -> np.ndarray:
    """Return the fixed unit basis vector for ``topic``.

    The basis is drawn from an RNG seeded by a hash of the topic name, so it
    is stable across processes and (with high probability) near-orthogonal to
    the bases of other topics.
    """
    cached = _BASIS_CACHE.get(topic)
    if cached is None:
        rng = np.random.default_rng(_stable_seed(f"topic:{topic}"))
        cached = normalize(rng.standard_normal(DIM))
        _BASIS_CACHE[topic] = cached
    return cached.copy()


def user_vector(affinities: dict[str, float] | Iterable[tuple[str, float]]) -> np.ndarray:
    """Embed a user as the normalized weighted sum of their topic affinities.

    Args:
        affinities: Mapping (or pairs) of topic name to affinity weight.

    Returns:
        A unit-norm vector of dimension :data:`DIM`.
    """
    pairs = affinities.items() if isinstance(affinities, dict) else affinities
    vec = np.zeros(DIM, dtype=np.float64)
    for topic, weight in sorted(pairs):
        vec += float(weight) * topic_basis(topic)
    return normalize(vec)


def post_vector(topics: Sequence[str], text: str) -> np.ndarray:
    """Embed a post from its topics plus a small content-hash perturbation.

    Args:
        topics: Topic names the post is about.
        text: Post text; only its hash is used, keeping the embedding
            deterministic without any ML model.

    Returns:
        A unit-norm vector of dimension :data:`DIM`.
    """
    vec = np.zeros(DIM, dtype=np.float64)
    for topic in sorted(set(topics)):
        vec += topic_basis(topic)
    rng = np.random.default_rng(_stable_seed(f"post:{text}"))
    # Expected noise norm is 0.04 * sqrt(DIM) = 0.32, so posts sharing a topic
    # stay close (cosine ~0.9) while distinct texts remain distinguishable.
    vec += 0.04 * rng.standard_normal(DIM)
    return normalize(vec)


def to_list(vec: np.ndarray) -> list[float]:
    """Convert a vector to the plain ``list[float]`` IssunDB expects."""
    return [float(x) for x in vec]
