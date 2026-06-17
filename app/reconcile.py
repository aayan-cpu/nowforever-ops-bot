"""BOL vs Veeder-Root fuel reconciliation across records.

`app/vision.py` already recomputes a discrepancy when a *single* image happens to
show both the Bill-of-Lading total and the Veeder-Root tank reading. In practice
they almost never share one photo: the driver's BOL receipt is one message and
the tank-monitor reading is another. This module pairs those separate
`fuel_events` per site and delivery date and flags mismatches — the class of
problem behind the ~2,500-gal Channelview case that was only ever caught by hand.

Pure + dependency-free: the matching logic takes a plain list of event dicts so
it unit-tests without Firestore. `find_mismatches()` is the live entry point.

A `fuel_events` record (written by chat_live.analyze_images) looks like:
    {room_name, report_date, doc_type, bol_gallons, veeder_gallons,
     discrepancy_gallons, summary, data_id}
"""
from __future__ import annotations

import os

from app import store

# Gallons of BOL-vs-Veeder difference worth flagging. Shares the env var with
# vision so a deployment tunes one threshold for both single- and cross-image.
DEFAULT_THRESHOLD = int(os.getenv("OPS_BOL_THRESHOLD", "500"))


def _num(x) -> float | None:
    """Coerce a stored gallon value to float, or None if absent/garbage."""
    if isinstance(x, bool):  # guard: bool is an int subclass
        return None
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        s = x.replace(",", "").strip()
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _site(ev: dict) -> str:
    return (ev.get("room_name") or "Unknown").strip() or "Unknown"


def _mismatch(site, report_date, bol, veeder, source, data_ids) -> dict:
    return {
        "site": site,
        "report_date": report_date,
        "bol_gallons": bol,
        "veeder_gallons": veeder,
        "discrepancy_gallons": round(abs(bol - veeder), 2),
        "source": source,            # "same-record" | "matched-by-date"
        "data_ids": [d for d in data_ids if d],
    }


def reconcile_events(events: list[dict], threshold: float | None = None) -> list[dict]:
    """Return flagged BOL/Veeder mismatches from a list of fuel events.

    Two passes, no event counted twice:
      1. same-record — one event carries both a BOL and a Veeder figure.
      2. matched-by-date — within a site+report_date, a BOL-only event and a
         Veeder-only event are paired (the realistic delivery case).
    """
    if threshold is None:
        threshold = DEFAULT_THRESHOLD
    flagged: list[dict] = []
    consumed: set[int] = set()  # id() of events used by the same-record pass

    # Pass 1: both figures present on one record.
    for ev in events:
        bol, veeder = _num(ev.get("bol_gallons")), _num(ev.get("veeder_gallons"))
        if bol is not None and veeder is not None:
            consumed.add(id(ev))
            if abs(bol - veeder) > threshold:
                flagged.append(_mismatch(_site(ev), ev.get("report_date"), bol, veeder,
                                         "same-record", [ev.get("data_id")]))

    # Pass 2: pair BOL-only with Veeder-only events sharing site + report_date.
    groups: dict[tuple, dict[str, list]] = {}
    for ev in events:
        if id(ev) in consumed:
            continue
        date = ev.get("report_date")
        if not date:  # can't reliably pair undated readings across messages
            continue
        bol, veeder = _num(ev.get("bol_gallons")), _num(ev.get("veeder_gallons"))
        slot = groups.setdefault((_site(ev), date), {"bol": [], "veeder": []})
        if bol is not None:
            slot["bol"].append((bol, ev.get("data_id")))
        if veeder is not None:
            slot["veeder"].append((veeder, ev.get("data_id")))

    for (site, date), slot in groups.items():
        if not slot["bol"] or not slot["veeder"]:
            continue
        # Sum each side: a delivery may span multiple BOL tickets / tank drops.
        bol_total = round(sum(v for v, _ in slot["bol"]), 2)
        veeder_total = round(sum(v for v, _ in slot["veeder"]), 2)
        if abs(bol_total - veeder_total) > threshold:
            ids = [d for _, d in slot["bol"]] + [d for _, d in slot["veeder"]]
            flagged.append(_mismatch(site, date, bol_total, veeder_total,
                                     "matched-by-date", ids))

    flagged.sort(key=lambda m: m["discrepancy_gallons"], reverse=True)
    return flagged


def find_mismatches(threshold: float | None = None,
                    events: list[dict] | None = None) -> list[dict]:
    """Live entry point: reconcile all stored fuel_events (biggest gap first)."""
    if events is None:
        events = store.list_all("fuel_events")
    return reconcile_events(events, threshold)


def format_report(mismatches: list[dict]) -> str:
    """Human-readable summary suitable for a DM, alert, or digest line."""
    if not mismatches:
        return "✅ No BOL vs Veeder-Root fuel discrepancies detected."
    lines = [f"⛽ *Fuel discrepancies flagged ({len(mismatches)}):*"]
    for m in mismatches:
        when = f" {m['report_date']}" if m.get("report_date") else ""
        lines.append(
            f"• [{m['site']}]{when}: BOL {m['bol_gallons']} gal vs "
            f"Veeder {m['veeder_gallons']} gal — off by {m['discrepancy_gallons']} gal")
    return "\n".join(lines)
