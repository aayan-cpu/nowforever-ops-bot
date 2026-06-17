"""Fuel reconciliation: BOL (delivered) vs Veeder-Root (tank gauge).

`app/vision.py` already reconciles the case where ONE image carries both the
Bill-of-Lading total and the Veeder-Root reading. In practice the two numbers
usually arrive as SEPARATE messages — a BOL photo when the truck drops, a tank
reading later — landing as two `fuel_events` rows. This module pairs those
cross-event readings by site and date and flags deliveries whose delivered vs
gauged gallons differ by more than a threshold (the ~2,500 gal Channelview
case).

Pure stdlib, no external deps. `discrepancies()` reads the live `fuel_events`
collection; every other function is pure and takes its data as an argument, so
the logic is fully unit-testable without Firestore.
"""
from __future__ import annotations

import os
from datetime import date, datetime

# Same default as vision.DISCREPANCY_THRESHOLD so single-image and cross-event
# reconciliation agree on what counts as a mismatch.
THRESHOLD = int(os.getenv("OPS_BOL_THRESHOLD", "500"))
# How far apart (days) a BOL and a Veeder reading can be and still be considered
# the same delivery. Beyond this they're treated as unrelated.
PAIR_WINDOW_DAYS = int(os.getenv("OPS_BOL_PAIR_WINDOW_DAYS", "3"))


def _num(v):
    """Coerce a stored value to float, or None if not a real number."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


def _site_key(room_name: str) -> str:
    return (room_name or "Unknown").strip().lower()


def _parse_date(value):
    """Best-effort date parse; returns a date or None. Accepts 'YYYY-MM-DD' and
    ISO timestamps."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def compare(bol, veeder, threshold: int | None = None) -> dict:
    """Compare one delivered (BOL) vs gauged (Veeder) pair. Returns a verdict
    dict; `flagged` is True only when both numbers exist and differ by more than
    the threshold."""
    thr = THRESHOLD if threshold is None else threshold
    b, v = _num(bol), _num(veeder)
    if b is None or v is None:
        return {"bol_gallons": b, "veeder_gallons": v, "discrepancy_gallons": None,
                "flagged": False, "reason": "incomplete (missing BOL or Veeder reading)"}
    diff = round(abs(b - v), 2)
    flagged = diff > thr
    reason = (f"BOL {b:g} vs Veeder {v:g} differ by {diff:g} gal (> {thr})"
              if flagged else f"within tolerance ({diff:g} gal)")
    return {"bol_gallons": b, "veeder_gallons": v, "discrepancy_gallons": diff,
            "flagged": flagged, "reason": reason}


def _date_distance(a, b) -> int:
    da, db = _parse_date(a), _parse_date(b)
    if da is None or db is None:
        return 0  # undated readings can still pair (order preserved by caller)
    return abs((da - db).days)


def reconcile_events(events, threshold: int | None = None) -> list[dict]:
    """Pair BOL and Veeder readings across `fuel_events` and return one verdict
    per delivery, newest first.

    Pairing rules, per site:
    - An event already carrying BOTH numbers is reconciled on its own.
    - Remaining BOL-only and Veeder-only events are matched by nearest report
      date within PAIR_WINDOW_DAYS; each reading is used at most once.
    - Unmatched readings are returned as `incomplete` (pending the other half).
    """
    thr = THRESHOLD if threshold is None else threshold
    by_site: dict[str, dict[str, list]] = {}
    results: list[dict] = []

    for ev in events or []:
        bol, veeder = _num(ev.get("bol_gallons")), _num(ev.get("veeder_gallons"))
        site = _site_key(ev.get("room_name"))
        if bol is not None and veeder is not None:
            results.append(_verdict(ev, ev, bol, veeder, thr))
        elif bol is not None:
            by_site.setdefault(site, {"bol": [], "veeder": []})["bol"].append(ev)
        elif veeder is not None:
            by_site.setdefault(site, {"bol": [], "veeder": []})["veeder"].append(ev)

    for site, pools in by_site.items():
        bols = list(pools["bol"])
        veeders = list(pools["veeder"])
        used_v: set[int] = set()
        for bev in bols:
            best_i, best_d = None, None
            for i, vev in enumerate(veeders):
                if i in used_v:
                    continue
                d = _date_distance(bev.get("report_date"), vev.get("report_date"))
                if d <= PAIR_WINDOW_DAYS and (best_d is None or d < best_d):
                    best_i, best_d = i, d
            if best_i is None:
                results.append(_verdict(bev, None, _num(bev.get("bol_gallons")), None, thr))
            else:
                vev = veeders[best_i]
                used_v.add(best_i)
                results.append(_verdict(bev, vev, _num(bev.get("bol_gallons")),
                                        _num(vev.get("veeder_gallons")), thr))
        for i, vev in enumerate(veeders):
            if i not in used_v:
                results.append(_verdict(vev, None, None, _num(vev.get("veeder_gallons")), thr))

    results.sort(key=lambda r: r.get("report_date") or "", reverse=True)
    return results


def _verdict(primary: dict, other: dict | None, bol, veeder, thr: int) -> dict:
    cmp = compare(bol, veeder, thr)
    report_date = (primary.get("report_date")
                   or (other or {}).get("report_date"))
    return {
        "room_name": primary.get("room_name") or (other or {}).get("room_name"),
        "report_date": report_date,
        **cmp,
    }


def discrepancies(events=None, threshold: int | None = None) -> list[dict]:
    """Flagged mismatches only (delivered vs gauged differ beyond threshold).
    Reads the live `fuel_events` collection when `events` is None."""
    if events is None:
        from app import store
        events = store.list_all("fuel_events")
    return [r for r in reconcile_events(events, threshold) if r["flagged"]]


def summarize(events=None, threshold: int | None = None, limit: int = 20) -> str:
    """Human-readable flagged-mismatch report for digests / the AI brain."""
    flagged = discrepancies(events, threshold)
    if not flagged:
        return "No BOL vs Veeder-Root discrepancies above threshold."
    lines = [f"⛽ Fuel discrepancies ({len(flagged)} flagged):"]
    for r in flagged[:limit]:
        when = f" {r['report_date']}" if r.get("report_date") else ""
        lines.append(f"• [{r['room_name']}]{when} {r['reason']}")
    return "\n".join(lines)
