"""Pure-python tests for the network generator and embeddings (no DB)."""

from __future__ import annotations

import numpy as np

from social_recommendations import embeddings
from social_recommendations.network import DAY, NOW_TS, VOCAB, generate


def test_generate_is_deterministic() -> None:
    a = generate(seed=7, n_users=60)
    b = generate(seed=7, n_users=60)
    assert a == b


def test_different_seeds_differ() -> None:
    a = generate(seed=1, n_users=60)
    b = generate(seed=2, n_users=60)
    assert a != b


def test_basic_shape_and_referential_integrity() -> None:
    net = generate(seed=42, n_users=60)
    assert len(net.users) == 60
    handles = {u.handle for u in net.users}
    assert len(handles) == 60
    assert set(net.topics) == set(VOCAB)
    post_ids = {p.post_id for p in net.posts}
    assert len(post_ids) == len(net.posts)
    for follow in net.follows:
        assert follow.src in handles
        assert follow.dst in handles
        assert follow.src != follow.dst
        assert follow.since <= NOW_TS
    for post in net.posts:
        assert post.author in handles
        assert set(post.topics) <= set(net.topics)
        assert post.topics[0] == next(u for u in net.users if u.handle == post.author).community
        assert post.created_at <= NOW_TS
    posts_by_id = {p.post_id: p for p in net.posts}
    for like in net.likes:
        assert like.user in handles
        assert like.post_id in post_ids
        assert like.user != posts_by_id[like.post_id].author
        assert posts_by_id[like.post_id].created_at <= like.ts <= NOW_TS


def test_no_duplicate_follow_pairs() -> None:
    net = generate(seed=3, n_users=50)
    pairs = [(f.src, f.dst) for f in net.follows]
    assert len(pairs) == len(set(pairs))


def test_follows_are_intra_community_biased() -> None:
    net = generate(seed=42, n_users=100)
    community = {u.handle: u.community for u in net.users}
    intra = sum(1 for f in net.follows if community[f.src] == community[f.dst])
    assert intra / len(net.follows) > 0.5


def test_affinities_include_primary_community() -> None:
    net = generate(seed=42, n_users=30)
    for user in net.users:
        affinities = dict(user.affinities)
        assert affinities[user.community] == 1.0
        assert all(0.0 < w <= 1.0 for w in affinities.values())


def test_like_window_supports_trending() -> None:
    net = generate(seed=42, n_users=100)
    cutoff = NOW_TS - 14 * DAY
    assert any(like.ts >= cutoff for like in net.likes)


def test_topic_basis_deterministic_and_unit_norm() -> None:
    a = embeddings.topic_basis("rust-dev")
    b = embeddings.topic_basis("rust-dev")
    assert np.allclose(a, b)
    assert a.shape == (embeddings.DIM,)
    assert abs(float(np.linalg.norm(a)) - 1.0) < 1e-9
    assert not np.allclose(a, embeddings.topic_basis("cooking"))


def test_user_vector_is_unit_norm_and_community_aligned() -> None:
    vec = embeddings.user_vector({"ml": 1.0, "music": 0.2})
    assert abs(float(np.linalg.norm(vec)) - 1.0) < 1e-9
    own = float(vec @ embeddings.topic_basis("ml"))
    other = float(vec @ embeddings.topic_basis("gamedev"))
    assert own > other


def test_user_vector_accepts_pairs() -> None:
    as_dict = embeddings.user_vector({"ml": 1.0, "music": 0.2})
    as_pairs = embeddings.user_vector([("ml", 1.0), ("music", 0.2)])
    assert np.allclose(as_dict, as_pairs)


def test_post_vector_deterministic_and_text_sensitive() -> None:
    a = embeddings.post_vector(["rust-dev"], "Just shipped a lock-free crate.")
    b = embeddings.post_vector(["rust-dev"], "Just shipped a lock-free crate.")
    c = embeddings.post_vector(["rust-dev"], "A totally different post body.")
    assert np.allclose(a, b)
    assert not np.allclose(a, c)
    assert abs(float(np.linalg.norm(a)) - 1.0) < 1e-9
    assert float(a @ c) > 0.8  # same topic keeps them close despite text noise
