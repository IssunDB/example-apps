"""Command line interface for the social recommendation engine."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from issundb import IssunDB

DEFAULT_DB = str(Path(__file__).resolve().parent.parent / "social-data")


def _print_table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> None:
    """Print rows as aligned plain-text columns."""
    cells = [[str(value) for value in row] for row in rows]
    widths = [
        max(len(headers[i]), *(len(row[i]) for row in cells)) if cells else len(headers[i])
        for i in range(len(headers))
    ]
    line = "  ".join(header.ljust(widths[i]) for i, header in enumerate(headers))
    print(line)
    print("  ".join("-" * width for width in widths))
    for row in cells:
        print("  ".join(value.ljust(widths[i]) for i, value in enumerate(row)))


def _ellipsis(text: str, limit: int = 64) -> str:
    """Truncate ``text`` to ``limit`` characters with a trailing ellipsis."""
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _open_db(path: str) -> IssunDB:
    """Open an existing database, exiting with a hint when it is missing."""
    if not Path(path).exists():
        raise SystemExit(f"error: no database at {path!r} -- run the 'seed' subcommand first")
    from issundb import IssunDB as _IssunDB

    return _IssunDB(path)


def _cmd_seed(args: argparse.Namespace) -> int:
    from .seed import seed_database

    stats = seed_database(args.db, seed=args.seed, n_users=args.users)
    print(f"Seeded database at {args.db}")
    _print_table(
        ["users", "posts", "topics", "follows", "likes", "about"],
        [[stats.users, stats.posts, stats.topics, stats.follows, stats.likes, stats.about_edges]],
    )
    return 0


def _cmd_friends(args: argparse.Namespace) -> int:
    from .recommend import friends

    recs = friends(_open_db(args.db), args.user, k=args.k)
    print(f"People {args.user} may know (friend-of-friend):")
    _print_table(["handle", "name", "mutuals"], [[r.handle, r.name, r.mutuals] for r in recs])
    return 0


def _cmd_interests(args: argparse.Namespace) -> int:
    from .recommend import interests

    users, posts = interests(_open_db(args.db), args.user, k=args.k)
    print(f"Users with interests similar to {args.user}:")
    _print_table(
        ["handle", "name", "community", "similarity"],
        [[u.handle, u.name, u.community, f"{u.similarity:.3f}"] for u in users],
    )
    print()
    print("Posts they might like:")
    _print_table(
        ["post", "author", "similarity", "text"],
        [[p.post_id, p.author, f"{p.similarity:.3f}", _ellipsis(p.text)] for p in posts],
    )
    return 0


def _cmd_trending(args: argparse.Namespace) -> int:
    from .recommend import trending

    trends = trending(_open_db(args.db), window_days=args.window)
    print(f"Trending topics (likes in the last {args.window} days):")
    max_likes = max((t.likes for t in trends), default=1) or 1
    rows = [
        [t.topic, t.likes, t.posts, "#" * max(1, round(20 * t.likes / max_likes))] for t in trends
    ]
    _print_table(["topic", "likes", "posts", ""], rows)
    return 0


def _cmd_discover(args: argparse.Namespace) -> int:
    from .recommend import discover

    feed = discover(_open_db(args.db), args.user, args.query, k=args.k)
    print(f"Discover feed for {args.user} (query: {args.query!r}, hybrid rrf fusion):")
    _print_table(
        ["post", "author", "score", "topics", "text"],
        [
            [i.post_id, i.author, f"{i.score:.4f}", ",".join(i.topics), _ellipsis(i.text, 48)]
            for i in feed
        ],
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the argparse CLI with its five subcommands."""
    parser = argparse.ArgumentParser(
        prog="social-recommendations",
        description="Social recommendation engine showcase for IssunDB.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    seed_p = sub.add_parser("seed", help="generate and persist the synthetic social network")
    seed_p.add_argument("--db", default=DEFAULT_DB, help="database directory path")
    seed_p.add_argument("--seed", type=int, default=42, help="generator seed")
    seed_p.add_argument("--users", type=int, default=200, help="number of users")
    seed_p.set_defaults(func=_cmd_seed)

    friends_p = sub.add_parser("friends", help="friend-of-friend recommendations (Cypher)")
    friends_p.add_argument("--db", default=DEFAULT_DB, help="database directory path")
    friends_p.add_argument("--user", required=True, help="user handle")
    friends_p.add_argument("-k", type=int, default=10, help="max recommendations")
    friends_p.set_defaults(func=_cmd_friends)

    interests_p = sub.add_parser("interests", help="interest-based matches (vector search)")
    interests_p.add_argument("--db", default=DEFAULT_DB, help="database directory path")
    interests_p.add_argument("--user", required=True, help="user handle")
    interests_p.add_argument("-k", type=int, default=10, help="max results per section")
    interests_p.set_defaults(func=_cmd_interests)

    trending_p = sub.add_parser("trending", help="trending topics (aggregation)")
    trending_p.add_argument("--db", default=DEFAULT_DB, help="database directory path")
    trending_p.add_argument("--window", type=int, default=14, help="window in days")
    trending_p.set_defaults(func=_cmd_trending)

    discover_p = sub.add_parser("discover", help="hybrid discover feed (vector + text + graph)")
    discover_p.add_argument("--db", default=DEFAULT_DB, help="database directory path")
    discover_p.add_argument("--user", required=True, help="user handle")
    discover_p.add_argument("--query", required=True, help="free-text query")
    discover_p.add_argument("-k", type=int, default=10, help="max feed items")
    discover_p.set_defaults(func=_cmd_discover)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""
    args = build_parser().parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
