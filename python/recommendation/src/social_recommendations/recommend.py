"""The four recommendation features.

Each feature exercises a different IssunDB capability against the same graph:

* :func:`friends`: friend-of-friend recommendations via Cypher.
* :func:`interests`: kindred users and posts via vector search.
* :func:`trending`: topic ranking via Cypher aggregation over recent likes.
* :func:`discover`: a hybrid (vector + text + graph expansion) feed via
  :meth:`IssunDB.retrieve_hybrid`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from issundb import IssunDB

from .embeddings import to_list, user_vector
from .network import DAY, NOW_TS


@dataclass(frozen=True)
class FriendRec:
    """A friend-of-friend recommendation."""

    handle: str
    name: str
    mutuals: int


@dataclass(frozen=True)
class UserMatch:
    """A user surfaced by interest-vector similarity."""

    handle: str
    name: str
    community: str
    similarity: float


@dataclass(frozen=True)
class PostMatch:
    """A post surfaced by interest-vector similarity."""

    post_id: str
    author: str
    text: str
    similarity: float


@dataclass(frozen=True)
class TopicTrend:
    """A topic ranked by recent like activity."""

    topic: str
    likes: int
    posts: int


@dataclass(frozen=True)
class DiscoverItem:
    """A post in the hybrid discover feed."""

    post_id: str
    author: str
    text: str
    topics: tuple[str, ...]
    score: float


def _rows(db: IssunDB, cypher: str, params: dict[str, Any] | None = None) -> list[list[Any]]:
    """Run a Cypher query and return its records as plain value lists."""
    raw = db.query(cypher, json.dumps(params) if params is not None else None)
    payload = json.loads(raw)
    return [record["values"] for record in payload["records"]]


def _node_props(db: IssunDB, node_id: int) -> dict[str, Any]:
    """Fetch and decode a node's property map, empty if the node is missing."""
    raw = db.get_node(node_id)
    if raw is None:
        return {}
    props: dict[str, Any] = json.loads(raw)
    return props


def _user_vec(db: IssunDB, handle: str) -> list[float]:
    """Rebuild a user's interest vector from their stored affinities."""
    rows = _rows(
        db,
        "MATCH (u:User) WHERE u.handle = $h RETURN u.affinities AS affinities",
        {"h": handle},
    )
    if not rows:
        raise KeyError(f"no user with handle {handle!r}")
    affinities: dict[str, float] = json.loads(rows[0][0])
    return to_list(user_vector(affinities))


def friends(db: IssunDB, handle: str, k: int = 10) -> list[FriendRec]:
    """Recommend users via friend-of-friend traversal.

    Scores candidates by the number of distinct mutual connections and
    excludes the user themselves plus everyone they already follow.

    Args:
        db: Open IssunDB handle.
        handle: Handle of the user to recommend for.
        k: Maximum number of recommendations.

    Returns:
        Recommendations sorted by mutual-connection count, best first.
    """
    direct = {
        row[0]
        for row in _rows(
            db,
            "MATCH (me:User)-[:FOLLOWS]->(f:User) WHERE me.handle = $h RETURN f.handle",
            {"h": handle},
        )
    }
    rows = _rows(
        db,
        "MATCH (me:User)-[:FOLLOWS]->(f:User)-[:FOLLOWS]->(fof:User) "
        "WHERE me.handle = $h AND fof.handle <> $h "
        "RETURN fof.handle AS handle, fof.name AS name, COUNT(DISTINCT f) AS mutuals "
        "ORDER BY mutuals DESC",
        {"h": handle},
    )
    recs = [
        FriendRec(handle=str(h), name=str(name), mutuals=int(mutuals))
        for h, name, mutuals in rows
        if h not in direct
    ]
    return recs[:k]


def interests(db: IssunDB, handle: str, k: int = 10) -> tuple[list[UserMatch], list[PostMatch]]:
    """Recommend kindred users and posts via cosine vector search.

    Args:
        db: Open IssunDB handle.
        handle: Handle of the user to recommend for.
        k: Maximum number of users and of posts to return.

    Returns:
        ``(users, posts)`` sorted by similarity, best first. Similarity is
        ``1 - cosine_distance``.
    """
    vec = _user_vec(db, handle)
    user_hits: list[dict[str, Any]] = json.loads(db.vector_search(vec, k + 1, label="User"))
    users: list[UserMatch] = []
    for hit in user_hits:
        props = _node_props(db, int(hit["node"]))
        if props.get("handle") in (None, handle):
            continue
        users.append(
            UserMatch(
                handle=str(props["handle"]),
                name=str(props.get("name", "")),
                community=str(props.get("community", "")),
                similarity=1.0 - float(hit["distance"]),
            )
        )
    post_hits: list[dict[str, Any]] = json.loads(db.vector_search(vec, k, label="Post"))
    posts: list[PostMatch] = []
    for hit in post_hits:
        props = _node_props(db, int(hit["node"]))
        if not props or props.get("author") == handle:
            continue
        posts.append(
            PostMatch(
                post_id=str(props["id"]),
                author=str(props.get("author", "")),
                text=str(props.get("text", "")),
                similarity=1.0 - float(hit["distance"]),
            )
        )
    return users[:k], posts[:k]


def trending(db: IssunDB, window_days: int = 14) -> list[TopicTrend]:
    """Rank topics by likes received on posts about them within a window.

    Args:
        db: Open IssunDB handle.
        window_days: Size of the trailing window (relative to the generator's
            fixed "now") in days.

    Returns:
        Topics sorted by recent like count, busiest first.
    """
    cutoff = NOW_TS - window_days * DAY
    rows = _rows(
        db,
        "MATCH (u:User)-[l:LIKES]->(p:Post)-[:ABOUT]->(t:Topic) "
        "WHERE l.ts >= $cutoff "
        "RETURN t.name AS topic, COUNT(l) AS likes, COUNT(DISTINCT p) AS posts "
        "ORDER BY likes DESC",
        {"cutoff": cutoff},
    )
    return [
        TopicTrend(topic=str(topic), likes=int(likes), posts=int(posts))
        for topic, likes, posts in rows
    ]


def _resolve_post(db: IssunDB, props: dict[str, Any], score: float) -> DiscoverItem:
    """Resolve a post node's author and topics through the graph."""
    rows = _rows(
        db,
        "MATCH (a:User)-[:POSTED]->(p:Post)-[:ABOUT]->(t:Topic) "
        "WHERE p.id = $pid "
        "RETURN a.handle AS author, COLLECT(t.name) AS topics",
        {"pid": props["id"]},
    )
    author = str(rows[0][0]) if rows else str(props.get("author", ""))
    topics = tuple(str(t) for t in rows[0][1]) if rows else ()
    return DiscoverItem(
        post_id=str(props["id"]),
        author=author,
        text=str(props.get("text", "")),
        topics=topics,
        score=score,
    )


def discover(db: IssunDB, handle: str, query: str, k: int = 10) -> list[DiscoverItem]:
    """Build a hybrid discover feed mixing interest vectors and a text query.

    Uses :meth:`IssunDB.retrieve_hybrid` with reciprocal-rank fusion over a
    vector search seeded by the user's interest vector and a full-text search
    over post text, expanded one hop into the graph; post nodes from the
    returned subgraph are rendered with their authors and topics.

    Args:
        db: Open IssunDB handle.
        handle: Handle of the user to personalize for.
        query: Free-text query for the full-text leg.
        k: Maximum number of feed items.

    Returns:
        Posts sorted by fused score, best first.
    """
    vec = _user_vec(db, handle)
    raw = db.retrieve_hybrid(
        vector=vec,
        text_query=query,
        vector_k=k * 3,
        text_k=k * 3,
        text_label="Post",
        text_property="text",
        vector_label="Post",
        hops=1,
        fusion_strategy="rrf",
    )
    result: dict[str, Any] = json.loads(raw)
    scores: dict[str, float] = {str(n): float(s) for n, s in result.get("scores", {}).items()}
    ranked = sorted(result.get("nodes", []), key=lambda n: scores.get(str(n), 0.0), reverse=True)
    feed: list[DiscoverItem] = []
    for node_id in ranked:
        props = _node_props(db, int(node_id))
        if props.get("kind") != "post" or props.get("author") == handle:
            continue
        feed.append(_resolve_post(db, props, scores.get(str(node_id), 0.0)))
        if len(feed) >= k:
            break
    return feed
