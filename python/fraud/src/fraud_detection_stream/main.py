"""Command-line entry point: stream events into IssunDB and surface alerts.

Usage::

    python -m fraud_detection_stream --events 2000 --batch-size 200 --seed 42

WARNING: the database directory (``--db``, default ``./fraud-stream-data``)
is deleted and recreated on every run so each run starts from a clean graph.
"""

from __future__ import annotations

import argparse
import itertools
import shutil
from pathlib import Path

from fraud_detection_stream.detectors import Alert, format_alert, run_all_detectors
from fraud_detection_stream.generator import BASE_TS, EventGenerator
from fraud_detection_stream.graph_store import GraphStore

RULES = ("ring", "shared_device", "fan_in_mule", "velocity")
DEFAULT_WINDOW_SECONDS = 3600


def build_parser() -> argparse.ArgumentParser:
    """Build the argparse CLI parser."""
    parser = argparse.ArgumentParser(
        prog="fraud_detection_stream",
        description=(
            "Stream simulated financial events into an embedded IssunDB graph "
            "and run Cypher-based fraud detectors after every batch."
        ),
    )
    parser.add_argument("--events", type=int, default=2000, help="total events to stream")
    parser.add_argument("--batch-size", type=int, default=200, help="events per batch")
    parser.add_argument("--seed", type=int, default=42, help="seed for the event generator")
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("./fraud-stream-data"),
        help="database directory (DELETED and recreated at start)",
    )
    parser.add_argument(
        "--window",
        type=int,
        default=DEFAULT_WINDOW_SECONDS,
        help="detection look-back window in simulated seconds",
    )
    return parser


def print_summary(
    detected: dict[str, set[str]], injected: dict[str, set[str]], store: GraphStore
) -> None:
    """Print the final detected-vs-injected summary table."""
    print()
    print("=" * 72)
    print("Summary")
    print("=" * 72)
    print(f"  graph: {store.nodes_created} nodes, {store.edges_created} edges")
    print()
    print(f"  {'rule':<14} {'injected':>9} {'detected':>9} {'matched':>8}")
    print(f"  {'-' * 14} {'-' * 9} {'-' * 9} {'-' * 8}")
    for rule in RULES:
        truth = injected.get(rule, set())
        found = detected.get(rule, set())
        matched = len(truth & found)
        print(f"  {rule:<14} {len(truth):>9} {len(found):>9} {matched:>8}")
    print()
    print("  ('detected' counts unique alert subjects; 'matched' are detected")
    print("   subjects that correspond to an injected ground-truth pattern.)")


def main(argv: list[str] | None = None) -> int:
    """Run the streaming fraud-detection demo."""
    args = build_parser().parse_args(argv)

    from issundb import IssunDB  # imported here so --help works without the package

    db_path: Path = args.db
    if db_path.exists():
        print(f"Removing existing database directory {db_path} ...")
        shutil.rmtree(db_path)
    db = IssunDB(str(db_path))
    store = GraphStore(db)
    generator = EventGenerator(seed=args.seed)

    print(
        f"Streaming {args.events} events (seed={args.seed}, "
        f"batch_size={args.batch_size}, window={args.window}s) into {db_path}"
    )

    seen: set[tuple[str, str]] = set()
    detected: dict[str, set[str]] = {rule: set() for rule in RULES}
    events = generator.stream(args.events)
    batch_no = 0
    last_ts = BASE_TS
    while True:
        batch = list(itertools.islice(events, args.batch_size))
        if not batch:
            break
        batch_no += 1
        batch_first_ts = batch[0].ts
        for event in batch:
            store.apply(event)
            last_ts = max(last_ts, event.ts)

        # Look back `window` seconds, but never start later than the oldest
        # event in this batch: a batch whose span exceeds the window would
        # otherwise drop patterns injected early in it before they are scored.
        since_ts = min(last_ts - args.window, batch_first_ts)
        new_alerts: list[Alert] = []
        for alert in run_all_detectors(db, since_ts):
            key = (alert.rule, alert.subject)
            detected[alert.rule].add(alert.subject)
            if key not in seen:
                seen.add(key)
                new_alerts.append(alert)

        print(
            f"batch {batch_no:>3} | {len(batch):>4} events | "
            f"sim-clock t+{last_ts - BASE_TS}s | new alerts: {len(new_alerts)}"
        )
        for alert in new_alerts:
            print(format_alert(alert))

    injected: dict[str, set[str]] = {rule: set() for rule in RULES}
    for pattern in generator.injected:
        injected[pattern.rule].add(pattern.subject)
    print_summary(detected, injected, store)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
