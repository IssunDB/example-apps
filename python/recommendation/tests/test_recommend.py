"""End-to-end tests for the recommendation features against a real IssunDB.

Skipped entirely when the ``issundb`` package is not installed.
"""

from __future__ import annotations

import gc
import json
from pathlib import Path

import pytest

issundb = pytest.importorskip("issundb")

from social_recommendations.network import VOCAB, generate  # noqa: E402
from social_recommendations.recommend import (  # noqa: E402
    DiscoverItem,
    discover,
    friends,
    interests,
    trending,
)
from social_recommendations.seed import seed_database  # noqa: E402

SEED = 1
N_USERS = 40


@pytest.fixture(scope="module")
def db_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("social") / "db"
    stats = seed_database(str(path), seed=SEED, n_users=N_USERS)
    assert stats.users == N_USERS
    assert stats.posts > 0
    assert stats.follows > 0
    return path


@pytest.fixture(scope="module")
def db(db_path: Path) -> "issundb.IssunDB":
    # Make sure the handle used during seeding has been released before the
    # embedded database is reopened in this process.
    gc.collect()
    return issundb.IssunDB(str(db_path))


@pytest.fixture(scope="module")
def handle() -> str:
    return generate(seed=SEED, n_users=N_USERS).users[0].handle


def _direct_follows(db: "issundb.IssunDB", handle: str) -> set[str]:
    raw = db.query(
        "MATCH (me:User)-[:FOLLOWS]->(f:User) WHERE me.handle = $h RETURN f.handle",
        json.dumps({"h": handle}),
    )
    return {record["values"][0] for record in json.loads(raw)["records"]}


def test_friends_excludes_self_and_existing_follows(db: "issundb.IssunDB", handle: str) -> None:
    recs = friends(db, handle, k=5)
    assert recs, "expected at least one friend-of-friend recommendation"
    assert len(recs) <= 5
    direct = _direct_follows(db, handle)
    for rec in recs:
        assert rec.handle != handle
        assert rec.handle not in direct
        assert rec.mutuals >= 1
    assert [r.mutuals for r in recs] == sorted((r.mutuals for r in recs), reverse=True)


def test_interests_returns_kindred_users_and_posts(db: "issundb.IssunDB", handle: str) -> None:
    users, posts = interests(db, handle, k=5)
    assert users and posts
    assert all(u.handle != handle for u in users)
    assert all(p.author != handle for p in posts)
    assert all(-1.0 <= u.similarity <= 1.0 + 1e-6 for u in users)
    net = generate(seed=SEED, n_users=N_USERS)
    me = next(u for u in net.users if u.handle == handle)
    # The top kindred user should usually share the primary community.
    assert users[0].community == me.community


def test_trending_ranks_topics_by_recent_likes(db: "issundb.IssunDB") -> None:
    trends = trending(db, window_days=60)
    assert trends
    assert all(t.likes >= 1 and t.posts >= 1 for t in trends)
    assert [t.likes for t in trends] == sorted((t.likes for t in trends), reverse=True)
    assert {t.topic for t in trends} <= set(VOCAB)


def test_discover_returns_scored_posts(db: "issundb.IssunDB", handle: str) -> None:
    net = generate(seed=SEED, n_users=N_USERS)
    me = next(u for u in net.users if u.handle == handle)
    query = VOCAB[me.community]["nouns"][0]
    feed = discover(db, handle, query, k=5)
    assert feed
    assert len(feed) <= 5
    for item in feed:
        assert isinstance(item, DiscoverItem)
        assert item.author != handle
        assert item.topics
    assert [i.score for i in feed] == sorted((i.score for i in feed), reverse=True)
