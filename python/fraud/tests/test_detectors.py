"""Integration tests for the Cypher detectors against a real IssunDB.

These tests skip cleanly while the ``issundb`` package is not installed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

issundb = pytest.importorskip("issundb")

from fraud_detection_stream.detectors import (  # noqa: E402
    detect_fan_in_mules,
    detect_rings,
    detect_shared_devices,
    detect_velocity_bursts,
    run_all_detectors,
)
from fraud_detection_stream.generator import (  # noqa: E402
    BASE_TS,
    DeviceLogin,
    EventGenerator,
    NewAccount,
    NewDevice,
    Transfer,
)
from fraud_detection_stream.graph_store import GraphStore  # noqa: E402


@pytest.fixture()
def store(tmp_path: Path) -> GraphStore:
    db = issundb.IssunDB(str(tmp_path / "graph-db"))
    return GraphStore(db)


def _add_accounts(store: GraphStore, ids: list[str]) -> None:
    for i, account_id in enumerate(ids):
        store.apply(NewAccount(account_id, f"Person {i}", "NO", BASE_TS))


def test_detect_ring(store: GraphStore) -> None:
    _add_accounts(store, ["ACC-A", "ACC-B", "ACC-C", "ACC-X"])
    ts = BASE_TS + 100
    store.apply(Transfer("ACC-A", "ACC-B", 5000.0, ts))
    store.apply(Transfer("ACC-B", "ACC-C", 4900.0, ts + 5))
    store.apply(Transfer("ACC-C", "ACC-A", 4800.0, ts + 10))
    # A benign transfer that must not create a false ring.
    store.apply(Transfer("ACC-A", "ACC-X", 100.0, ts + 20))

    alerts = detect_rings(store.db, BASE_TS)
    assert len(alerts) == 1
    assert alerts[0].subject == "ACC-A|ACC-B|ACC-C"
    assert alerts[0].evidence["total_amount"] == pytest.approx(14700.0)


def test_ring_outside_window_is_ignored(store: GraphStore) -> None:
    _add_accounts(store, ["ACC-A", "ACC-B", "ACC-C"])
    ts = BASE_TS + 100
    store.apply(Transfer("ACC-A", "ACC-B", 5000.0, ts))
    store.apply(Transfer("ACC-B", "ACC-C", 4900.0, ts + 5))
    store.apply(Transfer("ACC-C", "ACC-A", 4800.0, ts + 10))

    assert detect_rings(store.db, ts + 1000) == []


def test_detect_shared_device(store: GraphStore) -> None:
    accounts = ["ACC-1", "ACC-2", "ACC-3", "ACC-4", "ACC-5"]
    _add_accounts(store, accounts)
    store.apply(NewDevice("DEV-HOT", "deadbeef", BASE_TS))
    store.apply(NewDevice("DEV-OK", "cafebabe", BASE_TS))
    for i, account_id in enumerate(accounts[:4]):
        store.apply(DeviceLogin(account_id, "DEV-HOT", BASE_TS + 10 + i))
    # Only two accounts on DEV-OK: below the threshold.
    store.apply(DeviceLogin("ACC-4", "DEV-OK", BASE_TS + 50))
    store.apply(DeviceLogin("ACC-5", "DEV-OK", BASE_TS + 51))

    alerts = detect_shared_devices(store.db, BASE_TS)
    assert len(alerts) == 1
    assert alerts[0].subject == "DEV-HOT"
    assert alerts[0].evidence["accounts"] == 4


def test_detect_fan_in_mule(store: GraphStore) -> None:
    senders = [f"ACC-S{i}" for i in range(8)]
    _add_accounts(store, [*senders, "ACC-MULE", "ACC-OUT"])
    total = 0.0
    for i, sender in enumerate(senders):
        amount = 100.0 + i
        total += amount
        store.apply(Transfer(sender, "ACC-MULE", amount, BASE_TS + 10 + i))
    store.apply(Transfer("ACC-MULE", "ACC-OUT", round(total * 0.95, 2), BASE_TS + 60))

    alerts = detect_fan_in_mules(store.db, BASE_TS)
    assert [alert.subject for alert in alerts] == ["ACC-MULE"]
    assert alerts[0].severity == "high"
    assert alerts[0].evidence["inbound"] == 8


def test_detect_velocity_burst(store: GraphStore) -> None:
    targets = [f"ACC-T{i}" for i in range(12)]
    _add_accounts(store, ["ACC-FAST", "ACC-SLOW", *targets])
    for i, target in enumerate(targets):
        store.apply(Transfer("ACC-FAST", target, 200.0, BASE_TS + 10 + 2 * i))
    # Slow account: same count but spread over hours -> no alert.
    for i, target in enumerate(targets):
        store.apply(Transfer("ACC-SLOW", target, 200.0, BASE_TS + 10 + 3600 * i))

    alerts = detect_velocity_bursts(store.db, BASE_TS - 1)
    assert [alert.subject for alert in alerts] == ["ACC-FAST"]
    assert alerts[0].evidence["transfers"] == 12


def test_end_to_end_stream_detects_injected_patterns(tmp_path: Path) -> None:
    db = issundb.IssunDB(str(tmp_path / "stream-db"))
    store = GraphStore(db)
    generator = EventGenerator(seed=42)
    for event in generator.stream(3000):
        store.apply(event)

    alerts = run_all_detectors(db, BASE_TS)
    detected = {(alert.rule, alert.subject) for alert in alerts}
    injected = {(pattern.rule, pattern.subject) for pattern in generator.injected}
    assert injected, "expected injected patterns with this seed/volume"
    # Every fully-emitted injected pattern should be found over the full window;
    # patterns truncated at the very end of the stream may legitimately be missed.
    missed = injected - detected
    assert len(missed) <= 1
