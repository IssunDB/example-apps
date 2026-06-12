"""Maps generated stream events onto the IssunDB property graph.

Graph schema::

    (:Account {id, name, country, created_at})
    (:Device {id, fingerprint})
    (:Merchant {id, category})

    (Account)-[:TRANSFER {amount, ts}]->(Account)
    (Account)-[:USED_DEVICE {ts}]->(Device)
    (Account)-[:PAID {amount, ts}]->(Merchant)

Internal IssunDB node ids are kept in local dictionaries keyed by the domain
ids (``ACC-…``, ``DEV-…``, ``MER-…``); detectors match purely on the ``id``
property, never on internal node ids.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from fraud_detection_stream.generator import (
    DeviceLogin,
    Event,
    NewAccount,
    NewDevice,
    NewMerchant,
    Payment,
    Transfer,
)

if TYPE_CHECKING:
    from issundb import IssunDB


class GraphStore:
    """Thin write-path wrapper translating events into nodes and edges."""

    def __init__(self, db: IssunDB) -> None:
        self._db = db
        self._accounts: dict[str, int] = {}
        self._devices: dict[str, int] = {}
        self._merchants: dict[str, int] = {}
        self.nodes_created = 0
        self.edges_created = 0

    @property
    def db(self) -> IssunDB:
        """The underlying IssunDB handle (for running detector queries)."""
        return self._db

    def apply(self, event: Event) -> None:
        """Apply one stream event to the graph."""
        if isinstance(event, NewAccount):
            self._ensure_account(event.account_id, event.name, event.country, event.ts)
        elif isinstance(event, NewDevice):
            self._ensure_device(event.device_id, event.fingerprint)
        elif isinstance(event, NewMerchant):
            self._ensure_merchant(event.merchant_id, event.category)
        elif isinstance(event, Transfer):
            self._apply_transfer(event)
        elif isinstance(event, DeviceLogin):
            self._apply_device_login(event)
        else:
            self._apply_payment(event)

    # -- node upserts ------------------------------------------------------

    def _ensure_account(self, account_id: str, name: str, country: str, ts: int) -> int:
        node_id = self._accounts.get(account_id)
        if node_id is None:
            props = {"id": account_id, "name": name, "country": country, "created_at": ts}
            node_id = self._db.add_node("Account", json.dumps(props))
            self._accounts[account_id] = node_id
            self.nodes_created += 1
        return node_id

    def _ensure_device(self, device_id: str, fingerprint: str) -> int:
        node_id = self._devices.get(device_id)
        if node_id is None:
            props = {"id": device_id, "fingerprint": fingerprint}
            node_id = self._db.add_node("Device", json.dumps(props))
            self._devices[device_id] = node_id
            self.nodes_created += 1
        return node_id

    def _ensure_merchant(self, merchant_id: str, category: str) -> int:
        node_id = self._merchants.get(merchant_id)
        if node_id is None:
            props = {"id": merchant_id, "category": category}
            node_id = self._db.add_node("Merchant", json.dumps(props))
            self._merchants[merchant_id] = node_id
            self.nodes_created += 1
        return node_id

    # -- edge writes -------------------------------------------------------

    def _apply_transfer(self, event: Transfer) -> None:
        src = self._ensure_account(event.src_account, "unknown", "??", event.ts)
        dst = self._ensure_account(event.dst_account, "unknown", "??", event.ts)
        props = {"amount": event.amount, "ts": event.ts}
        self._db.add_edge(src, dst, "TRANSFER", json.dumps(props))
        self.edges_created += 1

    def _apply_device_login(self, event: DeviceLogin) -> None:
        account = self._ensure_account(event.account_id, "unknown", "??", event.ts)
        device = self._ensure_device(event.device_id, "unknown")
        self._db.add_edge(account, device, "USED_DEVICE", json.dumps({"ts": event.ts}))
        self.edges_created += 1

    def _apply_payment(self, event: Payment) -> None:
        account = self._ensure_account(event.account_id, "unknown", "??", event.ts)
        merchant = self._ensure_merchant(event.merchant_id, "unknown")
        props = {"amount": event.amount, "ts": event.ts}
        self._db.add_edge(account, merchant, "PAID", json.dumps(props))
        self.edges_created += 1
