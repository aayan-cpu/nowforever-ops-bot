"""Proactive scheduled briefings & reminders.

Triggered by Cloud Scheduler hitting /cron/<name> on the bot. Each builds content
from Firestore (deterministic) and, where it adds value, an AI narrative via the
Claude brain, then posts to the relevant Chat space.

Spaces are configurable via env so they can be retargeted without code changes.
"""
from __future__ import annotations

import os
from datetime import date

from app import reports, chat_media, brain, store

ALL_CAPTAINS = os.getenv("OPS_ALL_CAPTAINS_SPACE", "spaces/AAAAhO6H0_Y")
OFFICES = os.getenv("OPS_OFFICES_SPACE", "spaces/AAAAaIRkgq8")
ADMIN_DM = os.getenv("OPS_ADMIN_DM_SPACE", "spaces/6AxGNyAAAAE")  # aayan ↔ bot DM

# Spaces that are not individual stations (excluded from missing-report checks).
_NON_STATION = {"All Captains Chat", "SUMMERBELL CAMPUS COMMUNICATIONS GROUP"}


def _high_open_tasks(limit: int = 50) -> list[dict]:
    return [t for t in reports.open_tasks(limit=limit) if t.get("priority") == "high"]


def morning_digest() -> dict:
    """8 AM — AI-written ops briefing to all captains."""
    text = brain.answer(
        "Write a brief MORNING ops briefing for the station captains. Cover: how many "
        "open tasks, the top high-priority issues by store, and the 2-3 things to "
        "prioritize today. Keep it under 12 short lines, skimmable.",
        None, "scheduler", True)
    if not text:
        tasks = _high_open_tasks(12)
        lines = ["Open high-priority items:"] + [f"• #{t['id']} [{t['room_name']}] {t.get('task_title')}" for t in tasks]
        text = "\n".join(lines) if tasks else "No high-priority items open. Have a good day."
    ok = chat_media.post_to_space(ALL_CAPTAINS, f"🌅 *Morning Ops Briefing*\n{text}")
    return {"ok": ok, "kind": "morning_digest"}


def urgent_reminder() -> dict:
    """Midday — remind on still-open urgent items."""
    tasks = _high_open_tasks(20)
    if not tasks:
        return {"ok": True, "kind": "urgent_reminder", "skipped": "none open"}
    lines = ["🚨 *Still-open urgent items* — please update or resolve:"]
    lines += [f"• #{t['id']} [{t['room_name']}] {t.get('task_title') or t.get('task_text')}" for t in tasks[:15]]
    ok = chat_media.post_to_space(ALL_CAPTAINS, "\n".join(lines))
    return {"ok": ok, "kind": "urgent_reminder", "count": len(tasks)}


def missing_reports() -> dict:
    """Evening — which stations have not posted a daily report today."""
    today = date.today().isoformat()
    msgs = store.list_all("messages")
    rooms, reported = set(), set()
    for m in msgs:
        rn = m.get("room_name") or ""
        if not rn or rn in _NON_STATION or rn.lower().startswith("direct message") or rn.startswith("spaces/"):
            continue
        rooms.add(rn)
        ts = (m.get("created_at") or m.get("timestamp_raw") or "")[:10]
        cats = m.get("categories") or ""
        if ts == today and ("daily_shift_report" in cats or "day_report" in cats):
            reported.add(rn)
    missing = sorted(rooms - reported)
    if not missing:
        ok = chat_media.post_to_space(ADMIN_DM, "✅ All stations have posted a daily report today.")
        return {"ok": ok, "kind": "missing_reports", "missing": 0}
    lines = ["📋 *Stations missing a daily report today:*"] + [f"• {r}" for r in missing]
    ok = chat_media.post_to_space(ADMIN_DM, "\n".join(lines))
    return {"ok": ok, "kind": "missing_reports", "missing": len(missing)}


def ceo_summary() -> dict:
    """Night — AI end-of-day summary, DM'd to the owner."""
    text = brain.answer(
        "Write the END-OF-DAY summary for the owner. Cover: the key issues today, what "
        "is still open and urgent, and which stores need follow-up tomorrow. Be concise "
        "and concrete; use the task numbers and store names from the data.",
        None, "scheduler", True)
    if not text:
        tasks = _high_open_tasks(15)
        text = "Open high-priority items:\n" + "\n".join(
            f"• #{t['id']} [{t['room_name']}] {t.get('task_title')}" for t in tasks) if tasks else "Quiet day — nothing urgent open."
    ok = chat_media.post_to_space(ADMIN_DM, f"📊 *Daily Summary*\n{text}")
    return {"ok": ok, "kind": "ceo_summary"}


JOBS = {
    "morning-digest": morning_digest,
    "urgent-reminder": urgent_reminder,
    "missing-reports": missing_reports,
    "ceo-summary": ceo_summary,
}
