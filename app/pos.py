"""POS integration scaffold (Phase 5).

Defines the interface the bot will use to pull sales and inventory from a store's
point-of-sale system, plus a deterministic fake adapter for local dev and tests.
No real POS vendor is wired yet — this is the seam so the rest of the app can be
built and tested against a stable contract, then a real adapter dropped in via
`register_adapter` + the `OPS_POS_ADAPTER` env var with zero caller changes.

Pure stdlib (typing.Protocol + dataclasses) to stay Python 3.14-friendly — no
pydantic/pandas (see docs/LIMITATIONS.md #1).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Protocol, runtime_checkable


@dataclass(frozen=True)
class SalesSummary:
    """One store's sales for one business day."""
    store: str
    business_date: str          # ISO date, e.g. "2026-06-17"
    total_sales: float
    fuel_sales: float
    inside_sales: float
    fuel_gallons: float
    transactions: int


@dataclass(frozen=True)
class InventoryItem:
    store: str
    sku: str
    name: str
    quantity: float
    unit: str = "ea"
    reorder_level: float | None = None

    @property
    def below_reorder(self) -> bool:
        """True when stock has dropped under the reorder threshold (if set)."""
        return self.reorder_level is not None and self.quantity < self.reorder_level


@runtime_checkable
class POSAdapter(Protocol):
    """Contract every POS vendor adapter must satisfy."""
    name: str

    def get_sales(self, store: str, business_date: str) -> SalesSummary | None: ...

    def list_inventory(self, store: str) -> list[InventoryItem]: ...


class FakePOSAdapter:
    """Deterministic in-memory adapter for local dev + tests. Figures are derived
    from the store/date strings so results are stable across runs without being
    identical for every store/day."""
    name = "fake"

    def __init__(self, stores: list[str] | None = None):
        self._stores = list(stores) if stores else ["4 Channelview", "11 N&F Windchase"]

    @staticmethod
    def _seed(*parts) -> int:
        return sum(ord(ch) for p in parts for ch in str(p))

    def get_sales(self, store: str, business_date: str) -> SalesSummary | None:
        if store not in self._stores:
            return None
        s = self._seed(store, business_date)
        fuel = round(2000 + (s % 1500), 2)
        inside = round(800 + (s % 700), 2)
        return SalesSummary(
            store=store,
            business_date=business_date,
            total_sales=round(fuel + inside, 2),
            fuel_sales=fuel,
            inside_sales=inside,
            fuel_gallons=round(fuel / 3.25, 1),
            transactions=120 + (s % 200),
        )

    def list_inventory(self, store: str) -> list[InventoryItem]:
        if store not in self._stores:
            return []
        base = self._seed(store)
        rows = [
            ("SKU-REG", "Regular Unleaded", 5000 + base % 3000, "gal", 2000),
            ("SKU-PREM", "Premium Unleaded", 1500 + base % 800, "gal", 800),
            ("SKU-DSL", "Diesel", 3000 + base % 1500, "gal", 1000),
        ]
        return [InventoryItem(store=store, sku=k, name=n, quantity=float(q), unit=u, reorder_level=float(r))
                for (k, n, q, u, r) in rows]


# Adapter registry. Real vendor adapters call register_adapter() at import time;
# until then only the fake adapter is available.
_ADAPTERS: dict[str, Callable[[], POSAdapter]] = {"fake": FakePOSAdapter}


def register_adapter(name: str, factory: Callable[[], POSAdapter]) -> None:
    """Register a POS adapter factory under a name (e.g. 'gilbarco', 'verifone')."""
    _ADAPTERS[name.lower()] = factory


def available_adapters() -> list[str]:
    return sorted(_ADAPTERS)


def get_adapter(name: str | None = None) -> POSAdapter:
    """Return the configured POS adapter instance. Defaults to the fake adapter;
    override with the OPS_POS_ADAPTER env var once a real vendor is registered."""
    key = (name or os.getenv("OPS_POS_ADAPTER", "fake")).lower()
    factory = _ADAPTERS.get(key)
    if not factory:
        raise ValueError(f"Unknown POS adapter '{key}'. Available: {available_adapters()}")
    return factory()
