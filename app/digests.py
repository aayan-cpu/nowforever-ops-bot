"""Proactive scheduled briefings & reminders.

Triggered by Cloud Scheduler hitting /cron/<name> on the bot. Each builds content
from Firestore (deterministic) and, where it adds value, an AI narrative via the
Claude brain, then posts to the relevant Chat space.

Spaces are configurable via env so they can be retargeted without code changes.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from app import reports, chat_media, brain, store, reconcile

ESCALATE_HOURS = float(os.getenv("OPS_ESCALATE_HOURS", "36"))
# Hard floor: alerts ONLY consider issues posted on/after this date. Set to the
# deploy date so the bot ignores all the pre-deployment imported backlog and only
# alerts on issues from go-live onward (and keeps escalating them as they age).
ALERT_START = os.getenv("OPS_ALERT_START", "").strip()

ALL_CAPTAINS = os.getenv("OPS_ALL_CAPTAINS_SPACE", "spaces/AAAAhO6H0_Y")
OFFICES = os.getenv("OPS_OFFICES_SPACE", "spaces/AAAAaIRkgq8")
ADMIN_DM = os.getenv("OPS_ADMIN_DM_SPACE", "spaces/6AxGNyAAAAE")  # aayan ↔ bot DM
# Where the daily-report reminder nudge is posted (captains space by default).
REPORT_REMINDER_SPACE = os.getenv("OPS_REPORT_REMINDER_SPACE", ALL_CAPTAINS)


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
    """Midday — remind on still-open urgent items posted within the alert window."""
    tasks = [t for t in _high_open_tasks(300) if _after_start(t)][:20]
    if not tasks:
        return {"ok": True, "kind": "urgent_reminder", "skipped": "none open"}
    lines = ["🚨 *Still-open urgent items* — please update or resolve:"]
    lines += [f"• #{t['id']} [{t['room_name']}] {t.get('task_title') or t.get('task_text')}" for t in tasks[:15]]
    ok = chat_media.post_to_space(ALL_CAPTAINS, "\n".join(lines))
    return {"ok": ok, "kind": "urgent_reminder", "count": len(tasks)}


def missing_reports() -> dict:
    """Evening — DM the admin which stations have not posted a daily report today,
    and call out any that are overdue (no report for several days)."""
    status = reports.missing_daily_reports()
    missing, overdue = status["missing"], status["overdue"]
    if not missing:
        ok = chat_media.post_to_space(ADMIN_DM, "✅ All stations have posted a daily report today.")
        return {"ok": ok, "kind": "missing_reports", "missing": 0, "overdue": 0}
    lines = ["📋 *Stations missing a daily report today:*"] + [f"• {r}" for r in missing]
    if overdue:
        lines.append("")
        lines.append("⏰ *Overdue (no report in a while):*")
        for o in overdue:
            last = o["last_report"] or "never"
            since = f"{o['days_since']}d ago" if o["days_since"] is not None else "no report on record"
            lines.append(f"• {o['site']} — last report {last} ({since})")
    ok = chat_media.post_to_space(ADMIN_DM, "\n".join(lines))
    return {"ok": ok, "kind": "missing_reports", "missing": len(missing), "overdue": len(overdue)}


def report_reminder() -> dict:
    """Nudge the captains space to submit today's report. Posts only when some
    station still owes one, so it stays quiet on fully-reported days."""
    status = reports.missing_daily_reports()
    missing = status["missing"]
    if not missing:
        return {"ok": True, "kind": "report_reminder", "skipped": "all reported", "missing": 0}
    lines = ["🔔 *Daily report reminder* — these stations still owe today's report:"]
    lines += [f"• {r}" for r in missing]
    lines.append("\nPlease post your daily/shift report when you get a moment. Thank you!")
    ok = chat_media.post_to_space(REPORT_REMINDER_SPACE, "\n".join(lines))
    return {"ok": ok, "kind": "report_reminder", "missing": len(missing)}


def late_reports() -> dict:
    """After the cutoff — DM the admin which stations reported late today and
    which blew past their cutoff with nothing posted. Quiet when all on time."""
    status = reports.daily_report_lateness()
    late, missing = status["late"], status["missing_past_cutoff"]
    if not late and not missing:
        return {"ok": True, "kind": "late_reports", "skipped": "all on time",
                "late": 0, "missing": 0}
    lines = ["⏱️ *Daily report timeliness:*"]
    if late:
        lines.append("\n*Late (filed after cutoff):*")
        lines += [f"• {x['site']} — filed {x['filed']} (cutoff {x['cutoff']})" for x in late]
    if missing:
        lines.append("\n*Past cutoff, still missing:*")
        lines += [f"• {x['site']} (cutoff {x['cutoff']})" for x in missing]
    ok = chat_media.post_to_space(ADMIN_DM, "\n".join(lines))
    return {"ok": ok, "kind": "late_reports", "late": len(late), "missing": len(missing)}


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


def _issue_age_hours(t: dict, now: datetime | None = None) -> float:
    """Age by when the issue was actually POSTED (sent_at), falling back to when we
    logged it — so alerts reason about the real event time, not ingest time."""
    return _age_hours(t.get("sent_at") or t.get("created_at") or "", now)


def _after_start(t: dict) -> bool:
    """True if the issue was posted on/after OPS_ALERT_START (the go-live floor).
    Unconfigured → everything passes. Unparseable dates fail open (don't suppress)."""
    if not ALERT_START:
        return True
    try:
        start = datetime.fromisoformat(ALERT_START.replace("Z", "+00:00"))
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        ts = (t.get("sent_at") or t.get("created_at") or "")
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt >= start
    except Exception:
        return True


def escalation() -> dict:
    """Escalate high-priority tasks open past the SLA — only ones posted on/after the
    go-live floor (ignore pre-deployment imported backlog), and keep escalating them
    as they age (no upper cap)."""
    now = datetime.now(timezone.utc)
    stale = [(_issue_age_hours(t, now), t) for t in _high_open_tasks(300)]
    stale = sorted([(a, t) for a, t in stale
                    if a >= ESCALATE_HOURS and _after_start(t)], reverse=True)
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


def reconcile_alert() -> dict:
    """Proactively DM admins a high-priority alert when BOL vs Veeder-Root fuel
    deliveries differ beyond the threshold (builds on app/reconcile.py). Quiet
    when everything reconciles, so it's safe to run on a schedule."""
    flagged = reconcile.discrepancies()
    if not flagged:
        return {"ok": True, "kind": "reconcile_alert", "flagged": 0}
    msg = ("🛑 *Fuel reconciliation alert* — BOL vs Veeder-Root mismatch over threshold:\n"
           + reconcile.summarize())
    sent = sum(1 for tgt in _admin_dms() if chat_media.post_to_space(tgt["space"], msg))
    return {"ok": sent > 0, "kind": "reconcile_alert", "flagged": len(flagged), "sent": sent}


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


def sync_messages() -> dict:
    """Pull messages the webhook never delivered (Google Chat only forwards
    @mentions) from every room and ingest them, so every store is fully tracked."""
    from app import sync
    res = sync.sync_once()
    return {"ok": res.get("ingested", 0) >= 0, "kind": "sync_messages", **res}


def remap_rooms() -> dict:
    """Re-label messages stored under a raw space id to the friendly room name."""
    from app import sync
    return {"ok": True, "kind": "remap_rooms", **sync.remap_space_ids()}


def ocr_pass() -> dict:
    """Throttled OCR of day-report/BOL images the text-only sync skipped."""
    from app import sync
    return {"ok": True, "kind": "ocr_pass", **sync.ocr_pass()}


def purge_bot_echo() -> dict:
    """Downgrade the bot's own re-ingested posts so they stop showing as alerts."""
    from app import sync
    return {"ok": True, "kind": "purge_bot_echo", **sync.purge_bot_echo()}


def clear_dr_alerts() -> dict:
    """Clear day-report review/flag alerts (one-time)."""
    from app import sync
    return {"ok": True, "kind": "clear_dr_alerts", **sync.clear_day_report_alerts()}


def backfill_dms() -> dict:
    """Tag older DM messages so they show in the /dms view."""
    from app import sync
    return {"ok": True, "kind": "backfill_dms", **sync.backfill_dm_flag()}


JOBS = {
    "sync": sync_messages,
    "ocr-pass": ocr_pass,
    "remap-rooms": remap_rooms,
    "purge-bot-echo": purge_bot_echo,
    "clear-dr-alerts": clear_dr_alerts,
    "backfill-dms": backfill_dms,
    "morning-digest": morning_digest,
    "urgent-reminder": urgent_reminder,
    "missing-reports": missing_reports,
    "report-reminder": report_reminder,
    "late-reports": late_reports,
    "reconcile-alert": reconcile_alert,
    "ceo-summary": ceo_summary,
    "weekly-report": weekly_report,
    "weekly-digest": weekly_digest,
    "escalation": escalation,
}
