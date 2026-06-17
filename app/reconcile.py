"""Fuel reconciliation — Veeder-Root (tank gauge) vs BOL (delivered) gallons.

Fuel deliveries are logged as `fuel_events` (written by chat_live.analyze_images
from scanned BOL / Veeder-Root images) with `bol_gallons` and `veeder_gallons`.
When the gauge increase doesn't match the delivered amount, fuel is missing or
mis-measured — e.g. the ~2,500 gal Channelview case. This module flags those gaps.

All comparison logic is pure (no I/O) so it is unit-testable; the store-backed
helpers (`find_mismatches`) sit on top.
"""
from __future__ import annotations

import os

from app import store

# Deliveries and tank gauges rarely match to the gallon (temperature, meter drift,
# timing of the reading). Only flag gaps beyond this tolerance. Configurable so ops
# can tighten/loosen it without a code change.
DEFAULT_TOLERANCE_GAL = float(os.getenv("OPS_FUEL_TOLERANCE_GAL", "200"))


def _num(value):
    """Coerce a reading to float, or None if missing/non-numeric."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def discrepancy(bol_gallons, veeder_gallons):
    """Signed BOL-minus-Veeder gallons (positive = delivered more than the gauge
    rose = potential shrinkage/short-drop). None if either reading is missing."""
    bol, veeder = _num(bol_gallons), _num(veeder_gallons)
    if bol is None or veeder is None:
        return None
    return round(bol - veeder, 2)


def is_mismatch(bol_gallons, veeder_gallons, tolerance: float = DEFAULT_TOLERANCE_GAL) -> bool:
    d = discrepancy(bol_gallons, veeder_gallons)
    return d is not None and abs(d) > tolerance


def reconcile_events(events: list[dict], tolerance: float = DEFAULT_TOLERANCE_GAL) -> list[dict]:
    """Filter raw fuel_event rows down to mismatches beyond tolerance, biggest gap
    first. Rows missing either reading are skipped (nothing to compare)."""
    out: list[dict] = []
    for e in events:
        d = discrepancy(e.get("bol_gallons"), e.get("veeder_gallons"))
        if d is None or abs(d) <= tolerance:
            continue
        out.append({
            "room_name": e.get("room_name"),
            "report_date": e.get("report_date"),
            "bol_gallons": _num(e.get("bol_gallons")),
            "veeder_gallons": _num(e.get("veeder_gallons")),
            "discrepancy_gallons": d,
            "data_id": e.get("data_id"),
        })
    out.sort(key=lambda r: abs(r["discrepancy_gallons"]), reverse=True)
    return out


def format_mismatches(rows: list[dict]) -> str:
    if not rows:
        return "✅ Fuel reconciliation: no BOL/Veeder discrepancies above tolerance."
    lines = ["⛽ *Fuel reconciliation — BOL vs Veeder-Root discrepancies:*"]
    for r in rows:
        d = r["discrepancy_gallons"]
        # BOL > Veeder rise => delivered more than the tank gained => "short" in tank.
        direction = "short in tank" if d > 0 else "over in tank"
        date = f" {r['report_date']}" if r.get("report_date") else ""
        lines.append(
            f"• [{r.get('room_name')}]{date}: BOL {r.get('bol_gallons'):g} vs "
            f"Veeder {r.get('veeder_gallons'):g} → {abs(d):g} gal {direction}"
        )
    return "\n".join(lines)


def find_mismatches(tolerance: float | None = None) -> list[dict]:
    """Scan all stored fuel_events for discrepancies (store-backed entry point)."""
    tol = DEFAULT_TOLERANCE_GAL if tolerance is None else tolerance
    return reconcile_events(store.list_all("fuel_events"), tol)
