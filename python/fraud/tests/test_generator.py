"""Pure-Python tests for the deterministic event generator (no DB needed)."""

from __future__ import annotations

from collections import Counter

from fraud_detection_stream.generator import (
    BASE_TS,
    DeviceLogin,
    Event,
    EventGenerator,
    NewAccount,
    NewDevice,
    NewMerchant,
    Transfer,
)


def _take(seed: int, n: int) -> tuple[list[Event], EventGenerator]:
    generator = EventGenerator(seed=seed)
    return list(generator.stream(n)), generator


def test_same_seed_is_deterministic() -> None:
    events_a, gen_a = _take(42, 1500)
    events_b, gen_b = _take(42, 1500)
    assert events_a == events_b
    assert gen_a.injected == gen_b.injected


def test_different_seeds_differ() -> None:
    events_a, _ = _take(1, 1500)
    events_b, _ = _take(2, 1500)
    assert events_a != events_b


def test_stream_yields_exact_count() -> None:
    events, _ = _take(7, 333)
    assert len(events) == 333


def test_clock_is_monotonic_and_simulated() -> None:
    events, _ = _take(42, 2000)
    timestamps = [event.ts for event in events]
    assert timestamps[0] >= BASE_TS
    assert all(a <= b for a, b in zip(timestamps, timestamps[1:]))


def test_entities_are_created_before_first_reference() -> None:
    events, _ = _take(42, 3000)
    accounts: set[str] = set()
    devices: set[str] = set()
    merchants: set[str] = set()
    for event in events:
        if isinstance(event, NewAccount):
            accounts.add(event.account_id)
        elif isinstance(event, NewDevice):
            devices.add(event.device_id)
        elif isinstance(event, NewMerchant):
            merchants.add(event.merchant_id)
        elif isinstance(event, Transfer):
            assert event.src_account in accounts
            assert event.dst_account in accounts
            assert event.src_account != event.dst_account
        elif isinstance(event, DeviceLogin):
            assert event.account_id in accounts
            assert event.device_id in devices
        else:
            assert event.account_id in accounts
            assert event.merchant_id in merchants


def test_fraud_patterns_are_injected_with_ground_truth() -> None:
    _, generator = _take(42, 5000)
    rules = Counter(pattern.rule for pattern in generator.injected)
    assert set(rules) <= {"ring", "shared_device", "fan_in_mule", "velocity"}
    assert sum(rules.values()) > 0
    for pattern in generator.injected:
        assert pattern.subject
        assert pattern.entities


def test_ring_pattern_shape() -> None:
    _, generator = _take(42, 8000)
    rings = [p for p in generator.injected if p.rule == "ring"]
    assert rings, "expected at least one injected ring with this seed/volume"
    for ring in rings:
        assert len(ring.entities) == 3
        assert ring.subject == "|".join(sorted(ring.entities))
