"""Cypher-based fraud detection rules over the IssunDB graph.

Each detector is a function ``(db, since_ts) -> list[Alert]`` driven by a
single Cypher query where possible. IssunDB Cypher has no variable-length
paths or graph-algorithm procedures, so every rule is expressed with
fixed-length patterns plus aggregation — which is exactly what these classic
fraud shapes need.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from issundb import IssunDB

# Rule thresholds (tuned against the generator's injected patterns).
RING_MAX_SPAN_SECONDS = 300
RING_MAX_AMOUNT_RATIO = 1.15
SHARED_DEVICE_MIN_ACCOUNTS = 4
# n accounts sharing a device produce C(n, 2) unordered account pairs.
SHARED_DEVICE_MIN_PAIRS = 6
FAN_IN_MIN_TRANSFERS = 8
FAN_IN_MAX_AVG_AMOUNT = 500.0
VELOCITY_MIN_TRANSFERS = 10
VELOCITY_MAX_SPAN_SECONDS = 120


@dataclass
class Alert:
    """One fraud alert emitted by a detector.

    Attributes:
        rule: Detector rule name (``ring``, ``shared_device``, …).
        severity: ``high`` or ``medium``.
        subject: Canonical dedup key (e.g. ring member ids joined, or the
            focal device/account id).
        entities: All involved entity ids.
        evidence: Rule-specific measurements backing the alert.
    """

    rule: str
    severity: str
    subject: str
    entities: tuple[str, ...]
    evidence: dict[str, object]


def format_alert(alert: Alert) -> str:
    """Render an alert as a single plain-text line."""
    evidence = " ".join(f"{key}={value}" for key, value in alert.evidence.items())
    entities = ",".join(alert.entities)
    return f"  [{alert.severity.upper():<6}] {alert.rule:<14} entities={entities:<40} {evidence}"


def run_query(
    db: IssunDB, cypher: str, params: dict[str, object] | None = None
) -> list[list[object]]:
    """Run a Cypher query and return the record values as plain lists."""
    raw = db.query(cypher, json.dumps(params) if params is not None else None)
    payload = json.loads(raw)
    return [list(record["values"]) for record in payload.get("records", [])]


def detect_rings(db: IssunDB, since_ts: int) -> list[Alert]:
    """Detect circular transfer rings A -> B -> C -> A inside the window.

    The cycle itself is a single fixed-length Cypher pattern; two cheap
    client-side filters (the three hops happen within ``RING_MAX_SPAN_SECONDS``
    and carry similar amounts) weed out coincidental cycles formed by
    unrelated benign transfers.
    """
    cypher = """
    MATCH (a:Account)-[t1:TRANSFER]->(b:Account)-[t2:TRANSFER]->(c:Account)-[t3:TRANSFER]->(a)
    WHERE a.id < b.id AND a.id < c.id AND b.id <> c.id
      AND t1.ts >= $since AND t2.ts >= $since AND t3.ts >= $since
    RETURN a.id AS a_id, b.id AS b_id, c.id AS c_id,
           t1.amount AS amount_ab, t2.amount AS amount_bc, t3.amount AS amount_ca,
           t1.ts AS ts_ab, t2.ts AS ts_bc, t3.ts AS ts_ca
    """
    alerts: list[Alert] = []
    seen: set[str] = set()
    for row in run_query(db, cypher, {"since": since_ts}):
        members = (str(row[0]), str(row[1]), str(row[2]))
        subject = "|".join(sorted(members))
        if subject in seen:
            continue  # parallel transfers can yield duplicate cycles
        amounts = [float(str(row[i])) for i in (3, 4, 5)]
        stamps = [int(float(str(row[i]))) for i in (6, 7, 8)]
        span = max(stamps) - min(stamps)
        if span > RING_MAX_SPAN_SECONDS:
            continue
        if max(amounts) > RING_MAX_AMOUNT_RATIO * min(amounts):
            continue
        seen.add(subject)
        alerts.append(
            Alert(
                rule="ring",
                severity="high",
                subject=subject,
                entities=members,
                evidence={
                    "cycle_len": 3,
                    "total_amount": round(sum(amounts), 2),
                    "span_seconds": span,
                },
            )
        )
    return alerts


def detect_shared_devices(db: IssunDB, since_ts: int) -> list[Alert]:
    """Detect devices shared by ``SHARED_DEVICE_MIN_ACCOUNTS`` or more accounts."""
    cypher = """
    MATCH (a:Account)-[ua:USED_DEVICE]->(d:Device)<-[ub:USED_DEVICE]-(b:Account)
    WHERE a.id < b.id AND ua.ts >= $since AND ub.ts >= $since
    WITH d.id AS device_id, COUNT(ua.ts) AS pair_count,
         COLLECT(a.id) AS left_ids, COLLECT(b.id) AS right_ids
    WHERE pair_count >= $min_pairs
    RETURN device_id, pair_count, left_ids, right_ids
    """
    params: dict[str, object] = {"since": since_ts, "min_pairs": SHARED_DEVICE_MIN_PAIRS}
    alerts: list[Alert] = []
    for row in run_query(db, cypher, params):
        device_id = str(row[0])
        left = row[2] if isinstance(row[2], list) else []
        right = row[3] if isinstance(row[3], list) else []
        accounts = sorted({str(account) for account in [*left, *right]})
        if len(accounts) < SHARED_DEVICE_MIN_ACCOUNTS:
            continue
        alerts.append(
            Alert(
                rule="shared_device",
                severity="medium",
                subject=device_id,
                entities=(device_id, *accounts),
                evidence={"accounts": len(accounts), "pairs": int(float(str(row[1])))},
            )
        )
    return alerts


def detect_fan_in_mules(db: IssunDB, since_ts: int) -> list[Alert]:
    """Detect accounts collecting many small inbound transfers (mule fan-in)."""
    fan_in = """
    MATCH (src:Account)-[t:TRANSFER]->(dst:Account)
    WHERE t.ts >= $since
    WITH dst.id AS account_id, COUNT(t.amount) AS inbound,
         SUM(t.amount) AS total_in, AVG(t.amount) AS avg_in
    WHERE inbound >= $min_inbound AND avg_in <= $max_avg
    RETURN account_id, inbound, total_in, avg_in
    """
    cash_out = """
    MATCH (a:Account)-[t:TRANSFER]->(b:Account)
    WHERE a.id = $account_id AND t.ts >= $since
    RETURN MAX(t.amount) AS max_out
    """
    params: dict[str, object] = {
        "since": since_ts,
        "min_inbound": FAN_IN_MIN_TRANSFERS,
        "max_avg": FAN_IN_MAX_AVG_AMOUNT,
    }
    alerts: list[Alert] = []
    for row in run_query(db, fan_in, params):
        account_id = str(row[0])
        inbound = int(float(str(row[1])))
        total_in = round(float(str(row[2])), 2)
        out_rows = run_query(db, cash_out, {"account_id": account_id, "since": since_ts})
        max_out = 0.0
        if out_rows and out_rows[0][0] is not None:
            max_out = round(float(str(out_rows[0][0])), 2)
        cashed_out = max_out >= 0.5 * total_in
        alerts.append(
            Alert(
                rule="fan_in_mule",
                severity="high" if cashed_out else "medium",
                subject=account_id,
                entities=(account_id,),
                evidence={"inbound": inbound, "total_in": total_in, "max_out": max_out},
            )
        )
    return alerts


def detect_velocity_bursts(db: IssunDB, since_ts: int) -> list[Alert]:
    """Detect accounts firing many outbound transfers in a tiny time span."""
    cypher = """
    MATCH (a:Account)-[t:TRANSFER]->(b:Account)
    WHERE t.ts >= $since
    WITH a.id AS account_id, COUNT(t.ts) AS outbound,
         MIN(t.ts) AS first_ts, MAX(t.ts) AS last_ts
    WHERE outbound >= $min_transfers
    RETURN account_id, outbound, first_ts, last_ts
    """
    params: dict[str, object] = {"since": since_ts, "min_transfers": VELOCITY_MIN_TRANSFERS}
    alerts: list[Alert] = []
    for row in run_query(db, cypher, params):
        account_id = str(row[0])
        outbound = int(float(str(row[1])))
        span = int(float(str(row[3]))) - int(float(str(row[2])))
        if span > VELOCITY_MAX_SPAN_SECONDS:
            continue
        alerts.append(
            Alert(
                rule="velocity",
                severity="medium",
                subject=account_id,
                entities=(account_id,),
                evidence={"transfers": outbound, "span_seconds": span},
            )
        )
    return alerts


ALL_DETECTORS: tuple[Callable[[IssunDB, int], list[Alert]], ...] = (
    detect_rings,
    detect_shared_devices,
    detect_fan_in_mules,
    detect_velocity_bursts,
)


def run_all_detectors(db: IssunDB, since_ts: int) -> list[Alert]:
    """Run every detector against the window starting at ``since_ts``."""
    alerts: list[Alert] = []
    for detector in ALL_DETECTORS:
        alerts.extend(detector(db, since_ts))
    return alerts
