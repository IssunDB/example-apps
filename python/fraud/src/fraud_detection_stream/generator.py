"""Deterministic, seeded synthetic event stream with injected fraud patterns.

The generator produces mostly benign financial traffic (transfers, card
payments, device logins) and injects four known fraud patterns at fixed
probabilities: circular transfer rings, device-sharing clusters, money-mule
fan-in, and rapid-fire velocity bursts. Everything is driven by a single
``random.Random`` instance and a simulated clock, so a given seed always
yields the exact same stream.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass, field
from random import Random

BASE_TS = 1_700_000_000
"""Origin of the simulated clock (integer epoch seconds, no wall clock)."""

_FIRST_NAMES = (
    "Ada",
    "Bjarne",
    "Chiyo",
    "Dmitri",
    "Elena",
    "Farid",
    "Grace",
    "Hassan",
    "Ingrid",
    "Jorge",
    "Kateryna",
    "Liam",
    "Mei",
    "Noor",
    "Olusegun",
    "Priya",
    "Quentin",
    "Rosa",
    "Sven",
    "Tomoko",
    "Umar",
    "Vera",
    "Wei",
    "Ximena",
    "Yusuf",
    "Zofia",
)
_LAST_NAMES = (
    "Abe",
    "Bauer",
    "Costa",
    "Diallo",
    "Eriksen",
    "Fontaine",
    "Garcia",
    "Hansen",
    "Ito",
    "Jensen",
    "Kowalski",
    "Larsen",
    "Moreau",
    "Nakamura",
    "Okafor",
    "Petrov",
    "Quinn",
    "Rossi",
    "Schmidt",
    "Tanaka",
    "Ueda",
    "Vasquez",
    "Weber",
    "Xu",
    "Yamamoto",
    "Zhou",
)
_COUNTRIES = ("NO", "DE", "GB", "US", "JP", "BR", "NG", "IN", "PL", "ES")
_MERCHANT_CATEGORIES = (
    "groceries",
    "electronics",
    "travel",
    "fuel",
    "dining",
    "gaming",
    "fashion",
    "pharmacy",
    "streaming",
    "hardware",
)

# Probability that a scheduling step injects a given fraud pattern instead of
# a single benign event. The remainder of the probability mass is benign.
_P_RING = 0.004
_P_DEVICE_CLUSTER = 0.003
_P_MULE = 0.003
_P_VELOCITY = 0.003


@dataclass(frozen=True)
class NewAccount:
    """A new customer account appears in the stream."""

    account_id: str
    name: str
    country: str
    ts: int


@dataclass(frozen=True)
class NewDevice:
    """A new device fingerprint is observed."""

    device_id: str
    fingerprint: str
    ts: int


@dataclass(frozen=True)
class NewMerchant:
    """A new merchant is registered."""

    merchant_id: str
    category: str
    ts: int


@dataclass(frozen=True)
class Transfer:
    """An account-to-account money transfer."""

    src_account: str
    dst_account: str
    amount: float
    ts: int


@dataclass(frozen=True)
class DeviceLogin:
    """An account logs in from a device."""

    account_id: str
    device_id: str
    ts: int


@dataclass(frozen=True)
class Payment:
    """An account pays a merchant."""

    account_id: str
    merchant_id: str
    amount: float
    ts: int


Event = NewAccount | NewDevice | NewMerchant | Transfer | DeviceLogin | Payment


@dataclass(frozen=True)
class InjectedPattern:
    """Ground truth for one injected fraud pattern.

    Attributes:
        rule: Detector rule name this pattern should trigger.
        subject: Canonical subject key the matching detector alert will carry.
        entities: All entity ids involved in the pattern.
        ts: Simulated timestamp at which the pattern was injected.
    """

    rule: str
    subject: str
    entities: tuple[str, ...]
    ts: int


@dataclass
class EventGenerator:
    """Seeded generator yielding a deterministic stream of events.

    Attributes:
        seed: Seed for the internal ``random.Random`` instance.
        n_accounts: Size of the initial benign account pool.
        n_devices: Size of the initial device pool.
        n_merchants: Size of the initial merchant pool.
        injected: Ground-truth list of fraud patterns injected so far.
    """

    seed: int
    n_accounts: int = 60
    n_devices: int = 80
    n_merchants: int = 15
    injected: list[InjectedPattern] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        self._rng = Random(self.seed)
        self._ts = BASE_TS
        self._pending: deque[Event] = deque()
        self._accounts: list[str] = []
        self._devices: list[str] = []
        self._merchants: list[str] = []
        self._account_seq = 0
        self._device_seq = 0
        self._merchant_seq = 0
        self._bootstrap()

    def stream(self, n_events: int) -> Iterator[Event]:
        """Yield exactly ``n_events`` events (creations included).

        A fraud pattern scheduled close to the end of the stream may be
        truncated; its ground-truth entry is still recorded in ``injected``.
        """
        emitted = 0
        while emitted < n_events:
            if not self._pending:
                self._schedule_next()
            yield self._pending.popleft()
            emitted += 1

    # -- internal helpers --------------------------------------------------

    def _tick(self, lo: int, hi: int) -> int:
        """Advance the simulated clock by a random step and return it."""
        self._ts += self._rng.randint(lo, hi)
        return self._ts

    def _new_account(self, ts: int, pooled: bool = True) -> str:
        """Create an account; unpooled accounts never appear in benign traffic."""
        self._account_seq += 1
        account_id = f"ACC-{self._account_seq:05d}"
        name = f"{self._rng.choice(_FIRST_NAMES)} {self._rng.choice(_LAST_NAMES)}"
        country = self._rng.choice(_COUNTRIES)
        if pooled:
            self._accounts.append(account_id)
        self._pending.append(NewAccount(account_id, name, country, ts))
        return account_id

    def _new_device(self, ts: int, pooled: bool = True) -> str:
        """Create a device; unpooled devices never appear in benign logins."""
        self._device_seq += 1
        device_id = f"DEV-{self._device_seq:05d}"
        fingerprint = f"{self._rng.getrandbits(64):016x}"
        if pooled:
            self._devices.append(device_id)
        self._pending.append(NewDevice(device_id, fingerprint, ts))
        return device_id

    def _new_merchant(self, ts: int) -> str:
        self._merchant_seq += 1
        merchant_id = f"MER-{self._merchant_seq:05d}"
        category = self._rng.choice(_MERCHANT_CATEGORIES)
        self._merchants.append(merchant_id)
        self._pending.append(NewMerchant(merchant_id, category, ts))
        return merchant_id

    def _bootstrap(self) -> None:
        """Enqueue creation events for the initial entity pools."""
        for _ in range(self.n_accounts):
            self._new_account(self._tick(0, 2))
        for _ in range(self.n_devices):
            self._new_device(self._tick(0, 2))
        for _ in range(self.n_merchants):
            self._new_merchant(self._tick(0, 2))

    def _schedule_next(self) -> None:
        """Enqueue the next benign event or a whole fraud pattern."""
        roll = self._rng.random()
        if roll < _P_RING:
            self._inject_ring()
        elif roll < _P_RING + _P_DEVICE_CLUSTER:
            self._inject_device_cluster()
        elif roll < _P_RING + _P_DEVICE_CLUSTER + _P_MULE:
            self._inject_mule()
        elif roll < _P_RING + _P_DEVICE_CLUSTER + _P_MULE + _P_VELOCITY:
            self._inject_velocity_burst()
        else:
            self._schedule_benign()

    def _schedule_benign(self) -> None:
        ts = self._tick(5, 25)
        kind = self._rng.random()
        if kind < 0.55:
            src, dst = self._rng.sample(self._accounts, 2)
            amount = round(self._rng.uniform(10.0, 5000.0), 2)
            self._pending.append(Transfer(src, dst, amount, ts))
        elif kind < 0.90:
            account = self._rng.choice(self._accounts)
            merchant = self._rng.choice(self._merchants)
            amount = round(self._rng.uniform(2.0, 900.0), 2)
            self._pending.append(Payment(account, merchant, amount, ts))
        else:
            account = self._rng.choice(self._accounts)
            device = self._rng.choice(self._devices)
            self._pending.append(DeviceLogin(account, device, ts))

    def _inject_ring(self) -> None:
        """Circular transfer ring: A -> B -> C -> A within a short window."""
        ts = self._tick(5, 25)
        a = self._new_account(ts, pooled=False)
        b = self._new_account(ts, pooled=False)
        c = self._new_account(ts, pooled=False)
        base_amount = self._rng.uniform(2000.0, 9000.0)
        for src, dst in ((a, b), (b, c), (c, a)):
            amount = round(base_amount * self._rng.uniform(0.97, 1.03), 2)
            self._pending.append(Transfer(src, dst, amount, self._tick(1, 10)))
        subject = "|".join(sorted((a, b, c)))
        self.injected.append(InjectedPattern("ring", subject, (a, b, c), ts))

    def _inject_device_cluster(self) -> None:
        """Device sharing: 4+ accounts log in from one fresh device."""
        ts = self._tick(5, 25)
        device = self._new_device(ts, pooled=False)
        size = self._rng.randint(4, 6)
        accounts = tuple(self._rng.sample(self._accounts, size))
        for account in accounts:
            self._pending.append(DeviceLogin(account, device, self._tick(1, 8)))
        self.injected.append(InjectedPattern("shared_device", device, (device, *accounts), ts))

    def _inject_mule(self) -> None:
        """Money-mule fan-in: many small inbound transfers, one large outbound."""
        ts = self._tick(5, 25)
        mule = self._new_account(ts, pooled=False)
        senders = self._rng.sample(self._accounts, self._rng.randint(8, 11))
        total = 0.0
        for sender in senders:
            amount = round(self._rng.uniform(40.0, 220.0), 2)
            total += amount
            self._pending.append(Transfer(sender, mule, amount, self._tick(2, 8)))
        cash_out = self._rng.choice(self._accounts)
        self._pending.append(Transfer(mule, cash_out, round(total * 0.95, 2), self._tick(2, 8)))
        self.injected.append(InjectedPattern("fan_in_mule", mule, (mule, *senders), ts))

    def _inject_velocity_burst(self) -> None:
        """Velocity burst: one account fires many transfers in a tiny window."""
        ts = self._tick(5, 25)
        burster = self._new_account(ts, pooled=False)
        count = self._rng.randint(12, 16)
        for _ in range(count):
            dst = self._rng.choice(self._accounts)
            amount = round(self._rng.uniform(100.0, 800.0), 2)
            self._pending.append(Transfer(burster, dst, amount, self._tick(1, 4)))
        self.injected.append(InjectedPattern("velocity", burster, (burster,), ts))
