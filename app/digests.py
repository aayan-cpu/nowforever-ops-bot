"""Proactive scheduled briefings & reminders.

Triggered by Cloud Scheduler hitting /cron/<name> on the bot. Each builds content
from Firestore (deterministic) and, where it adds value, an AI narrative via the
Claude brain, then posts to the relevant Chat space.

Spaces are configurable via env so they can be retargeted without code changes.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timezone

from app import reports, chat_media, brain, store

ESCALATE_HOURS = float(os.getenv("OPS_ESCALATE_HOURS", "36"))

ALL_CAPTAINS = os.getenv("OPS_ALL_CAPTAINS_SPACE", "spaces/AAAAhO6H0_Y")
OFFICES = os.getenv("OPS_OFFICES_SPACE", "spaces/AAAAaIRkgq8")
ADMIN_DM = os.getenv("OPS_ADMIN_DM_SPACE", "spaces/6AxGNyAAAAE")  # aayan ↔ bot DM

# Spaces that are not individual stations (excluded from missing-report checks).
_NON_STATION = {"All Captains Chat", "SUMMERBELL CAMPUS COMMUNICATIONS GROUP"}


def _high_open_tasks(limit: int = 50) -> list[dict]:
    return [t for t in reports.open_tasks(limit=limit) if t.get("priority") == "high"]


def _admin_dms() -> list[dict]:
    """Known admin DM targets [{email, space}], learned when each admin DMs the bot.
    Falls back to the owner's DM space if none recorded yet."""
    try:
        rows = [r for r in store.list_all("admin_dms") if r.get("space")]
        if rows:
            return rows
    except Exception:
        pass
    return [{"email": "owner", "space": ADMIN_DM}]


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
    """Night — AI end-of-day summary, personalized per admin and DM'd to each."""
    targets = _admin_dms()
    sent = 0
    for t in targets:
        # Pass the admin's email as sender so the brain applies THEIR saved
        # preferences (what they care about / how they want it).
        text = brain.answer(
            "Write the END-OF-DAY summary for me. Cover the key issues today, what's "
            "still open and urgent, and which stores need follow-up tomorrow. Be concise "
            "and concrete; use task numbers and store names. Tailor it to my saved "
            "preferences if any.",
            None, t.get("email", "owner"), True, space_id=None)
        if not text:
            tasks = _high_open_tasks(15)
            text = ("Open high-priority items:\n" + "\n".join(
                f"• #{t2['id']} [{t2['room_name']}] {t2.get('task_title')}" for t2 in tasks)) \
                if tasks else "Quiet day — nothing urgent open."
        if chat_media.post_to_space(t["space"], f"📊 *Daily Summary*\n{text}"):
            sent += 1
    return {"ok": sent > 0, "kind": "ceo_summary", "recipients": len(targets), "sent": sent}


def _age_hours(created_at: str, now: datetime | None = None) -> float:
    try:
        dt = datetime.fromisoformat((created_at or "").replace("Z", "+00:00"))
        now = now or datetime.now(timezone.utc)
        return (now - dt).total_seconds() / 3600
    except Exception:
        return 0.0


def escalation() -> dict:
    """Escalate high-priority tasks still open past the SLA window to admins."""
    stale = [(_age_hours(t.get("created_at", "")), t)
             for t in _high_open_tasks(200)]
    stale = sorted([(a, t) for a, t in stale if a >= ESCALATE_HOURS], reverse=True)
    if not stale:
        return {"ok": True, "kind": "escalation", "stale": 0}
    lines = [f"⏰ *Escalation — {len(stale)} urgent item(s) open past {int(ESCALATE_HOURS)}h:*"]
    for age, t in stale[:15]:
        d, h = int(age // 24), int(age % 24)
        ago = (f"{d}d " if d else "") + f"{h}h"
        lines.append(f"• [{t.get('room_name')}] {t.get('task_title') or t.get('task_text')} — open {ago}")
    msg = "\n".join(lines)
    sent = sum(1 for tgt in _admin_dms() if chat_media.post_to_space(tgt["space"], msg))
    return {"ok": sent > 0, "kind": "escalation", "stale": len(stale)}


def weekly_report() -> dict:
    """Weekly — AI executive rollup, DM'd to each admin (tailored to their prefs)."""
    targets = _admin_dms()
    sent = 0
    for t in targets:
        text = brain.answer(
            "Write my WEEKLY EXECUTIVE REPORT: the week's biggest recurring issues by store, "
            "what got resolved vs what's still dragging, fuel/delivery and daily-report patterns, "
            "and the top 3 things to focus on next week. Concise and concrete, use the real data.",
            None, t.get("email", "owner"), True)
        if not text:
            text = "No data available for the weekly report."
        if chat_media.post_to_space(t["space"], f"📈 *Weekly Executive Report*\n{text}"):
            sent += 1
    return {"ok": sent > 0, "kind": "weekly_report", "sent": sent}


WEEKLY_DIGEST_SPACE = os.getenv("OPS_WEEKLY_DIGEST_SPACE", ALL_CAPTAINS)
WEEK_HOURS = 24 * 7


def _build_weekly_digest(tasks: list[dict], now: datetime | None = None) -> str:
    """Deterministic per-room rollup of open tasks: per station, how many are open,
    how many high-priority, how many opened in the last 7 days, plus up to 3 of the
    high-priority titles. Rooms are ordered by high-priority then open count so the
    busiest stations surface first. Kept pure (no I/O) so it is unit-testable."""
    now = now or datetime.now(timezone.utc)
    by_room: dict[str, dict] = {}
    for t in tasks:
        room = t.get("room_name") or "(unknown)"
        r = by_room.setdefault(room, {"open": 0, "high": 0, "new": 0, "high_titles": []})
        r["open"] += 1
        ca = t.get("created_at")
        if ca and _age_hours(ca, now) <= WEEK_HOURS:
            r["new"] += 1
        if t.get("priority") == "high":
            r["high"] += 1
            title = t.get("task_title") or t.get("task_text") or ""
            if title and len(r["high_titles"]) < 3:
                r["high_titles"].append(title)
    if not by_room:
        return "No open tasks this week — all clear. 🎉"
    ordered = sorted(by_room.items(), key=lambda kv: (kv[1]["high"], kv[1]["open"]), reverse=True)
    lines: list[str] = []
    for room, r in ordered:
        head = f"*{room}* — {r['open']} open"
        if r["high"]:
            head += f", {r['high']} high"
        if r["new"]:
            head += f", {r['new']} new this week"
        lines.append(head)
        for title in r["high_titles"]:
            lines.append(f"  • {title}")
    return "\n".join(lines)


def weekly_digest() -> dict:
    """Weekly — deterministic per-room digest of open work, posted to the captains
    space. Complements weekly_report (the AI executive rollup DM'd to admins)."""
    tasks = reports.open_tasks(limit=500)
    text = _build_weekly_digest(tasks)
    ok = chat_media.post_to_space(WEEKLY_DIGEST_SPACE, f"🗓️ *Weekly Per-Room Digest*\n{text}")
    rooms = len({t.get("room_name") for t in tasks if t.get("room_name")})
    return {"ok": ok, "kind": "weekly_digest", "rooms": rooms, "open_tasks": len(tasks)}


JOBS = {
    "morning-digest": morning_digest,
    "urgent-reminder": urgent_reminder,
    "missing-reports": missing_reports,
    "ceo-summary": ceo_summary,
    "weekly-report": weekly_report,
    "weekly-digest": weekly_digest,
    "escalation": escalation,
}
