"""Deterministic seeded synthetic social network generator.

Generates users grouped into interest communities, follow edges with an
intra-community bias, template-generated posts tagged with topics, and likes.
Everything is driven by a single ``random.Random`` seed so repeated runs
produce byte-identical networks.
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass

#: Fixed "now" (2026-06-01T00:00:00Z) so generated timestamps are deterministic.
NOW_TS = 1_780_272_000

#: Seconds per day.
DAY = 86_400

#: Community name -> vocabulary used to template post texts and bios.
VOCAB: dict[str, dict[str, list[str]]] = {
    "rust-dev": {
        "nouns": [
            "borrow checker",
            "lifetime annotation",
            "trait object",
            "async runtime",
            "procedural macro",
            "cargo workspace",
            "unsafe block",
            "zero-copy parser",
        ],
        "verbs": ["refactored", "benchmarked", "debugged", "shipped", "profiled"],
        "adjs": ["memory-safe", "zero-cost", "blazingly fast", "fearless", "lock-free"],
    },
    "ml": {
        "nouns": [
            "transformer",
            "embedding space",
            "loss curve",
            "attention head",
            "fine-tuning run",
            "feature store",
            "gradient step",
            "eval harness",
        ],
        "verbs": ["trained", "distilled", "quantized", "regularized", "ablated"],
        "adjs": ["overfit", "sample-efficient", "multimodal", "self-supervised", "sparse"],
    },
    "gamedev": {
        "nouns": [
            "physics engine",
            "shader pipeline",
            "level editor",
            "pathfinding grid",
            "particle system",
            "entity component system",
            "dialogue tree",
            "speedrun route",
        ],
        "verbs": ["playtested", "rigged", "rendered", "optimized", "prototyped"],
        "adjs": ["procedural", "pixel-perfect", "low-poly", "frame-perfect", "immersive"],
    },
    "cooking": {
        "nouns": [
            "sourdough starter",
            "cast iron pan",
            "miso glaze",
            "knife technique",
            "fermentation jar",
            "stock reduction",
            "tasting menu",
            "spice blend",
        ],
        "verbs": ["caramelized", "proofed", "braised", "plated", "deglazed"],
        "adjs": ["umami-rich", "flaky", "slow-roasted", "seasonal", "crispy"],
    },
    "music": {
        "nouns": [
            "modular synth",
            "chord progression",
            "vinyl pressing",
            "drum pattern",
            "field recording",
            "mixing desk",
            "tape loop",
            "bass line",
        ],
        "verbs": ["sampled", "mastered", "sequenced", "improvised", "remixed"],
        "adjs": ["lo-fi", "polyrhythmic", "ambient", "analog-warm", "syncopated"],
    },
}

#: Post text templates filled from a community vocabulary.
TEMPLATES: list[str] = [
    "Just {verb} a {adj} {noun}. Thoughts?",
    "Hot take: every {noun} should be {adj}.",
    "Spent the weekend on my {noun} and finally {verb} it.",
    "Why is my {noun} so {adj}? Asking for a friend.",
    "New post: how I {verb} the {adj} {noun} in one evening.",
    "Reminder that a {adj} {noun} beats a clever one every time.",
]

_FIRST_NAMES: list[str] = [
    "ada",
    "lin",
    "mira",
    "theo",
    "ivan",
    "noor",
    "sage",
    "kira",
    "omar",
    "june",
    "remy",
    "vera",
    "cole",
    "dana",
    "eli",
    "faye",
    "gus",
    "hana",
    "iris",
    "jack",
]

_LAST_NAMES: list[str] = [
    "stone",
    "vega",
    "reed",
    "okafor",
    "sato",
    "lund",
    "marsh",
    "quinn",
    "bell",
    "cruz",
    "ito",
    "wolf",
    "park",
    "haas",
    "noel",
    "ray",
    "kim",
    "frost",
    "lane",
    "drum",
]


@dataclass(frozen=True)
class User:
    """A generated user profile."""

    handle: str
    name: str
    bio: str
    joined_at: int
    community: str
    affinities: tuple[tuple[str, float], ...]


@dataclass(frozen=True)
class Post:
    """A generated post."""

    post_id: str
    author: str
    text: str
    created_at: int
    topics: tuple[str, ...]


@dataclass(frozen=True)
class Follow:
    """A follow edge between two user handles."""

    src: str
    dst: str
    since: int


@dataclass(frozen=True)
class Like:
    """A like by a user on a post."""

    user: str
    post_id: str
    ts: int


@dataclass(frozen=True)
class Network:
    """A complete generated social network."""

    topics: tuple[str, ...]
    users: tuple[User, ...]
    follows: tuple[Follow, ...]
    posts: tuple[Post, ...]
    likes: tuple[Like, ...]

    def like_counts(self) -> dict[str, int]:
        """Return the number of likes per post id."""
        counts: Counter[str] = Counter(like.post_id for like in self.likes)
        return {post.post_id: counts.get(post.post_id, 0) for post in self.posts}


def _make_users(rng: random.Random, n_users: int, communities: list[str]) -> list[User]:
    users: list[User] = []
    for i in range(n_users):
        community = communities[i % len(communities)]
        first = rng.choice(_FIRST_NAMES)
        last = rng.choice(_LAST_NAMES)
        handle = f"{first}_{last}_{i:03d}"
        name = f"{first.capitalize()} {last.capitalize()}"
        vocab = VOCAB[community]
        bio = f"{rng.choice(vocab['adjs']).capitalize()} {rng.choice(vocab['nouns'])} person."
        joined_at = NOW_TS - rng.randint(30, 720) * DAY
        affinities: dict[str, float] = {community: 1.0}
        for other in rng.sample([c for c in communities if c != community], rng.randint(1, 2)):
            affinities[other] = round(rng.uniform(0.15, 0.5), 3)
        users.append(
            User(
                handle=handle,
                name=name,
                bio=bio,
                joined_at=joined_at,
                community=community,
                affinities=tuple(sorted(affinities.items())),
            )
        )
    return users


def _make_follows(rng: random.Random, users: list[User]) -> list[Follow]:
    by_community: dict[str, list[User]] = {}
    for user in users:
        by_community.setdefault(user.community, []).append(user)
    follows: list[Follow] = []
    seen: set[tuple[str, str]] = set()
    for user in users:
        target_count = rng.randint(5, 15)
        added = 0
        attempts = 0
        while added < target_count and attempts < 60:
            attempts += 1
            pool = by_community[user.community] if rng.random() < 0.8 else users
            other = rng.choice(pool)
            key = (user.handle, other.handle)
            if other.handle == user.handle or key in seen:
                continue
            seen.add(key)
            since = rng.randint(max(user.joined_at, other.joined_at), NOW_TS)
            follows.append(Follow(src=user.handle, dst=other.handle, since=since))
            added += 1
    return follows


def _make_posts(rng: random.Random, users: list[User]) -> list[Post]:
    posts: list[Post] = []
    for user in users:
        secondary = [topic for topic, _ in user.affinities if topic != user.community]
        for _ in range(rng.randint(1, 6)):
            vocab = VOCAB[user.community]
            text = rng.choice(TEMPLATES).format(
                verb=rng.choice(vocab["verbs"]),
                adj=rng.choice(vocab["adjs"]),
                noun=rng.choice(vocab["nouns"]),
            )
            topics: list[str] = [user.community]
            if secondary and rng.random() < 0.4:
                topics.append(rng.choice(secondary))
            created_at = NOW_TS - rng.randint(0, 60) * DAY + rng.randint(0, DAY - 1)
            created_at = min(created_at, NOW_TS)
            posts.append(
                Post(
                    post_id=f"p{len(posts):04d}",
                    author=user.handle,
                    text=text,
                    created_at=created_at,
                    topics=tuple(topics),
                )
            )
    return posts


def _make_likes(rng: random.Random, users: list[User], posts: list[Post]) -> list[Like]:
    by_community: dict[str, list[User]] = {}
    for user in users:
        by_community.setdefault(user.community, []).append(user)
    likes: list[Like] = []
    seen: set[tuple[str, str]] = set()
    for post in posts:
        community = post.topics[0]
        for _ in range(rng.randint(0, 12)):
            pool = by_community[community] if rng.random() < 0.7 else users
            liker = rng.choice(pool)
            key = (liker.handle, post.post_id)
            if liker.handle == post.author or key in seen:
                continue
            seen.add(key)
            ts = rng.randint(post.created_at, NOW_TS)
            likes.append(Like(user=liker.handle, post_id=post.post_id, ts=ts))
    return likes


def generate(seed: int = 42, n_users: int = 200) -> Network:
    """Generate a deterministic synthetic social network.

    Args:
        seed: Seed for the internal ``random.Random``; identical seeds yield
            identical networks.
        n_users: Number of users to generate, spread round-robin across the
            interest communities in :data:`VOCAB`.

    Returns:
        A fully populated :class:`Network`.
    """
    rng = random.Random(seed)
    communities = list(VOCAB)
    users = _make_users(rng, n_users, communities)
    follows = _make_follows(rng, users)
    posts = _make_posts(rng, users)
    likes = _make_likes(rng, users, posts)
    return Network(
        topics=tuple(communities),
        users=tuple(users),
        follows=tuple(follows),
        posts=tuple(posts),
        likes=tuple(likes),
    )
