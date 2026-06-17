"""Cash reconciliation: day-report CASH vs bank DEPOSIT for the same store+date.

A day/closing report states the cash that should have been collected; the bank
deposit is what actually hit the account. If they don't match, cash is missing
(or a deposit is late/unrecorded) — exactly the kind of leak loss-prevention
cares about. This pairs the two by site and date — the report's `cash_amount`
(OCR'd in app/vision.py) against `deposits` parsed from 'deposit_cash_bank' chat
messages — and flags gaps over a dollar threshold.

Mirrors app/reconcile.py (fuel BOL vs Veeder). Pure stdlib; `discrepancies()`
reads live Firestore collections, every other function is pure and takes its data
as an argument, so the logic is fully unit-testable without Firestore.
"""
from __future__ import annotations

import os
import re
from datetime import date, datetime

# Flag a cash-vs-deposit gap above this many dollars.
THRESHOLD = float(os.getenv("OPS_CASH_THRESHOLD", "20"))
# How far apart (days) a report and a deposit can be and still pair — deposits
# often post a day or two after the report date.
PAIR_WINDOW_DAYS = int(os.getenv("OPS_CASH_PAIR_WINDOW_DAYS", "3"))

_MONEY_RE = re.compile(r"\$?\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)")
_DATE_RE = re.compile(r"\b(\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)\b")


def _num(v):
    """Coerce a stored value to float, or None if not a real number."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except (ValueError, AttributeError):
        return None


def _site_key(room_name: str) -> str:
    return (room_name or "Unknown").strip().lower()


def _parse_date(value):
    """Best-effort date parse; returns a date or None."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%m/%d/%y", "%m/%d"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def parse_deposit(text: str) -> dict | None:
    """Pull a deposit {amount, deposit_date} out of a 'deposit_cash_bank' message
    like '$4,940 bank deposit for 10/22'. Returns None if no dollar amount found.
    Picks the largest dollar figure (the deposit total) and the first date seen."""
    if not text:
        return None
    amounts = [a for a in (_num(m) for m in _MONEY_RE.findall(text)) if a is not None]
    if not amounts:
        return None
    dm = _DATE_RE.search(text)
    return {"amount": max(amounts), "deposit_date": dm.group(1) if dm else None}


def compare_cash(report_cash, deposit_amount, threshold: float | None = None) -> dict:
    """Compare one report's cash vs one deposit. `flagged` is True only when both
    exist and differ by more than the threshold. Positive shortfall => the deposit
    came in SHORT of the reported cash (the worrying direction)."""
    thr = THRESHOLD if threshold is None else threshold
    r, d = _num(report_cash), _num(deposit_amount)
    if r is None or d is None:
        return {"report_cash": r, "deposit_amount": d, "shortfall": None,
                "flagged": False, "reason": "incomplete (missing report cash or deposit)"}
    diff = round(r - d, 2)
    flagged = abs(diff) > thr
    if flagged:
        kind = "SHORT" if diff > 0 else "OVER"
        reason = (f"report cash ${r:,.2f} vs deposit ${d:,.2f} — deposit {kind} "
                  f"by ${abs(diff):,.2f} (> ${thr:g})")
    else:
        reason = f"matches within ${thr:g} (diff ${abs(diff):,.2f})"
    return {"report_cash": r, "deposit_amount": d, "shortfall": diff,
            "flagged": flagged, "reason": reason}


def _date_distance(a, b) -> int:
    da, db = _parse_date(a), _parse_date(b)
    if da is None or db is None:
        return 0
    return abs((da - db).days)


def reconcile(reports, deposits, threshold: float | None = None) -> list[dict]:
    """Pair each day-report (with cash_amount) to the nearest bank deposit for the
    same site within PAIR_WINDOW_DAYS; flag gaps over threshold. Each deposit is
    used at most once. Reports with no matching deposit come back as incomplete
    (the deposit may not have posted yet). Newest report first."""
    thr = THRESHOLD if threshold is None else threshold
    by_site: dict[str, dict] = {}
    for r in reports or []:
        if _num(r.get("cash_amount")) is None:
            continue
        by_site.setdefault(_site_key(r.get("room_name")),
                           {"reports": [], "deposits": []})["reports"].append(r)
    for d in deposits or []:
        if _num(d.get("amount")) is None:
            continue
        by_site.setdefault(_site_key(d.get("room_name")),
                           {"reports": [], "deposits": []})["deposits"].append(d)

    results: list[dict] = []
    for _site, pools in by_site.items():
        deps = list(pools["deposits"])
        used: set[int] = set()
        for rep in pools["reports"]:
            best_i, best_d = None, None
            for i, dep in enumerate(deps):
                if i in used:
                    continue
                dist = _date_distance(rep.get("report_date"), dep.get("deposit_date"))
                if dist <= PAIR_WINDOW_DAYS and (best_d is None or dist < best_d):
                    best_i, best_d = i, dist
            if best_i is None:
                v = compare_cash(rep.get("cash_amount"), None, thr)
            else:
                used.add(best_i)
                v = compare_cash(rep.get("cash_amount"), deps[best_i].get("amount"), thr)
                v["deposit_date"] = deps[best_i].get("deposit_date")
            v.update({"room_name": rep.get("room_name"), "report_date": rep.get("report_date")})
            results.append(v)
    results.sort(key=lambda x: str(x.get("report_date") or ""), reverse=True)
    return results


def discrepancies(threshold: float | None = None, only_flagged: bool = True) -> list[dict]:
    """Live: reconcile `day_reports` (cash_amount) vs `deposits` from Firestore."""
    from app import store
    reports = store.list_all("day_reports")
    deposits = store.list_all("deposits")
    out = reconcile(reports, deposits, threshold)
    return [r for r in out if r["flagged"]] if only_flagged else out
