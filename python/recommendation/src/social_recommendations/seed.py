"""Build the IssunDB graph from a generated network.

Creates ``Topic``, ``User``, and ``Post`` nodes, the ``FOLLOWS`` / ``POSTED``
/ ``LIKES`` / ``ABOUT`` edges, per-node interest vectors, and a full-text
index over post text.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from issundb import IssunDB

from .embeddings import post_vector, to_list, user_vector
from .network import Network, generate


@dataclass(frozen=True)
class SeedStats:
    """Counts of what was written to the database."""

    users: int
    posts: int
    topics: int
    follows: int
    likes: int
    about_edges: int


def _add_topics(db: IssunDB, net: Network) -> dict[str, int]:
    return {
        topic: db.add_node("Topic", json.dumps({"name": topic, "kind": "topic"}))
        for topic in net.topics
    }


def _add_users(db: IssunDB, net: Network) -> dict[str, int]:
    user_ids: dict[str, int] = {}
    for user in net.users:
        props = {
            "handle": user.handle,
            "name": user.name,
            "bio": user.bio,
            "joined_at": user.joined_at,
            "community": user.community,
            # Stored as a JSON string so it round-trips through Cypher RETURN
            # as a plain scalar.
            "affinities": json.dumps(dict(user.affinities)),
            "kind": "user",
        }
        node_id = db.add_node("User", json.dumps(props))
        user_ids[user.handle] = node_id
        db.upsert_vector(node_id, to_list(user_vector(dict(user.affinities))))
    return user_ids


def _add_posts(db: IssunDB, net: Network) -> dict[str, int]:
    like_counts = net.like_counts()
    post_ids: dict[str, int] = {}
    for post in net.posts:
        props = {
            "id": post.post_id,
            "text": post.text,
            "created_at": post.created_at,
            "likes": like_counts[post.post_id],
            "author": post.author,
            "kind": "post",
        }
        node_id = db.add_node("Post", json.dumps(props))
        post_ids[post.post_id] = node_id
        db.upsert_vector(node_id, to_list(post_vector(post.topics, post.text)))
    return post_ids


def _add_edges(
    db: IssunDB,
    net: Network,
    topic_ids: dict[str, int],
    user_ids: dict[str, int],
    post_ids: dict[str, int],
) -> tuple[int, int, int]:
    for follow in net.follows:
        db.add_edge(
            user_ids[follow.src],
            user_ids[follow.dst],
            "FOLLOWS",
            json.dumps({"since": follow.since}),
        )
    about_edges = 0
    for post in net.posts:
        db.add_edge(
            user_ids[post.author],
            post_ids[post.post_id],
            "POSTED",
            json.dumps({"ts": post.created_at}),
        )
        weight = 1.0 / len(post.topics)
        for topic in post.topics:
            db.add_edge(
                post_ids[post.post_id],
                topic_ids[topic],
                "ABOUT",
                json.dumps({"weight": weight}),
            )
            about_edges += 1
    for like in net.likes:
        db.add_edge(
            user_ids[like.user],
            post_ids[like.post_id],
            "LIKES",
            json.dumps({"ts": like.ts}),
        )
    return len(net.follows), len(net.likes), about_edges


def seed_database(db_path: str, seed: int = 42, n_users: int = 200) -> SeedStats:
    """Generate a network and persist it into a fresh IssunDB at ``db_path``.

    Args:
        db_path: Directory path for the embedded database.
        seed: Deterministic seed for the synthetic network generator.
        n_users: Number of users to generate.

    Returns:
        Counts of the nodes and edges that were written.
    """
    net = generate(seed=seed, n_users=n_users)
    db = IssunDB(db_path)
    db.configure_vector_index("cosine")
    topic_ids = _add_topics(db, net)
    user_ids = _add_users(db, net)
    post_ids = _add_posts(db, net)
    follows, likes, about_edges = _add_edges(db, net, topic_ids, user_ids, post_ids)
    db.create_text_index("Post", "text")
    return SeedStats(
        users=len(user_ids),
        posts=len(post_ids),
        topics=len(topic_ids),
        follows=follows,
        likes=likes,
        about_edges=about_edges,
    )
