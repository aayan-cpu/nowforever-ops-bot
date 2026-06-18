from __future__ import annotations

import html
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from app import store, sites, reconcile


def _sort_recent(rows: list[dict]) -> list[dict]:
    # Newest first: prefer numeric seq, fall back to created_at / timestamp_raw.
    return sorted(rows, key=lambda r: (r.get("seq") or 0, r.get("created_at") or r.get("timestamp_raw") or ""), reverse=True)


try:
    from zoneinfo import ZoneInfo
    _LOCAL_TZ = ZoneInfo(os.getenv("OPS_TIMEZONE", "America/Chicago"))
except Exception:
    _LOCAL_TZ = None


def fmt_ts(ts: str) -> str:
    """Format a stored UTC timestamp in the local timezone (default US Central),
    e.g. 'Jun 17, 2:03 PM'. Falls back to the raw string if it can't parse."""
    if not ts:
        return ""
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if _LOCAL_TZ:
            dt = dt.astimezone(_LOCAL_TZ)
        hh = dt.hour % 12 or 12
        return f"{dt.strftime('%b')} {dt.day}, {hh}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"
    except Exception:
        return str(ts)[:19]


def _local_today() -> str:
    """Today's date (YYYY-MM-DD) in the local timezone — not UTC, so an evening run
    (past midnight UTC) still uses the correct local day."""
    now = datetime.now(timezone.utc)
    if _LOCAL_TZ:
        now = now.astimezone(_LOCAL_TZ)
    return now.date().isoformat()


def _local_day(ts: str) -> str:
    """The local-timezone date (YYYY-MM-DD) of a stored UTC timestamp."""
    if not ts:
        return ""
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if _LOCAL_TZ:
            dt = dt.astimezone(_LOCAL_TZ)
        return dt.date().isoformat()
    except Exception:
        return str(ts)[:10]


_PRI_RANK = {"high": 0, "medium": 1}


def dashboard(db_path: str | None = None) -> dict:
    messages = store.list_all("messages")
    tasks = store.list_all("tasks")
    live = [m for m in messages if not m.get("is_duplicate")]

    totals = {
        "messages": len(messages),
        "attachments": sum(m.get("attachment_count") or 0 for m in messages),
        "duplicates": sum(1 for m in messages if m.get("is_duplicate")),
    }
    tc = defaultdict(int)
    for t in tasks:
        tc[t.get("status") or "open"] += 1
    task_counts = [{"status": s, "count": tc[s]} for s in sorted(tc)]

    pc = defaultdict(int)
    for m in messages:
        pc[m.get("priority") or "normal"] += 1
    priority_counts = [{"priority": p, "count": pc[p]}
                       for p in sorted(pc, key=lambda p: _PRI_RANK.get(p, 2))]

    rooms: dict[str, dict] = {}
    for m in messages:
        r = rooms.setdefault(m.get("room_name") or "Unknown", {"room_name": m.get("room_name") or "Unknown", "messages": 0, "attachments": 0, "high": 0, "tasks": 0})
        r["messages"] += 1
        r["attachments"] += m.get("attachment_count") or 0
        r["high"] += 1 if m.get("priority") == "high" else 0
        r["tasks"] += 1 if m.get("is_task") else 0
    top_rooms = sorted(rooms.values(), key=lambda r: r["messages"], reverse=True)[:12]

    category_counts = defaultdict(int)
    for m in live:
        for cat in (m.get("categories") or "general").split(";"):
            category_counts[cat] += 1
    return {
        "totals": totals,
        "tasks": task_counts,
        "priorities": priority_counts,
        "top_rooms": top_rooms,
        "categories": dict(sorted(category_counts.items(), key=lambda x: x[1], reverse=True)),
    }


def open_tasks(db_path: str | None = None, room: str | None = None, limit: int = 50, status: str = "open") -> list[dict]:
    tasks = [t for t in store.list_all("tasks") if (t.get("status") or "open") == status]
    if room:
        tasks = [t for t in tasks if room.lower() in (t.get("room_name") or "").lower()]
    tasks.sort(key=lambda t: (_PRI_RANK.get(t.get("priority"), 2), -(t.get("id") or 0)))
    return tasks[:limit]


def issue_time(item: dict) -> str:
    """The REAL time an issue was posted: the captain's send time, never the bot's
    logging time. sent_at → timestamp_raw (actual Chat createTime) → created_at last.
    created_at is when the sync LOGGED it (often days/years after the fact for the
    imported backlog), so it must never win — that's what made old issues look new."""
    return item.get("sent_at") or item.get("timestamp_raw") or item.get("created_at") or ""


_ISSUE_FLOOR = os.getenv("OPS_ALERT_START", "").strip()


def after_floor(item: dict) -> bool:
    """True if the issue was posted on/after OPS_ALERT_START, judged by its REAL send
    time (issue_time), so pre-go-live imported backlog (2023-2025) stops surfacing as
    a current alert. No floor set, or unparseable time → passes (fail open)."""
    if not _ISSUE_FLOOR:
        return True
    try:
        start = datetime.fromisoformat(_ISSUE_FLOOR.replace("Z", "+00:00"))
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        ts = issue_time(item)
        if not ts:
            return True
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt >= start
    except Exception:
        return True


def high_priority(db_path: str | None = None, limit: int = 50) -> list[dict]:
    rows = [m for m in store.list_all("messages")
            if m.get("priority") == "high" and not m.get("is_duplicate")
            and not m.get("is_dm")  # DMs to the bot are commands, not store alerts
            and after_floor(m)]      # drop pre-go-live imported backlog
    return _sort_recent(rows)[:limit]


def fuel_discrepancies(db_path: str | None = None, threshold: int | None = None) -> list[dict]:
    """Flagged BOL-vs-Veeder mismatches for the dashboard (delegates to
    app.reconcile, which reads the live ``fuel_events`` collection)."""
    return reconcile.discrepancies(threshold=threshold)


def store_scorecards(db_path: str | None = None, limit: int = 20) -> list[dict]:
    """Per-station health rows for the dashboard: message volume, high-priority
    count, open-task count, and the top open issue type. Keyed by canonical site
    so "11" and "11 N&F Windchase" collapse into one card. Busiest first."""
    cards: dict[str, dict] = {}

    def _card(name: str) -> dict:
        key = sites.canonical_name(name) if sites.is_station(name) else (name or "Unknown")
        return cards.setdefault(key, {"room_name": key, "messages": 0, "high": 0,
                                      "open_tasks": 0, "high_tasks": 0, "_cats": Counter()})

    for m in store.list_all("messages"):
        if m.get("is_duplicate"):
            continue
        c = _card(m.get("room_name") or "Unknown")
        c["messages"] += 1
        if m.get("priority") == "high":
            c["high"] += 1
    for t in store.list_all("tasks"):
        if (t.get("status") or "open") != "open":
            continue
        c = _card(t.get("room_name") or "Unknown")
        c["open_tasks"] += 1
        if t.get("priority") == "high":
            c["high_tasks"] += 1
        c["_cats"][t.get("category") or "other"] += 1

    out = []
    for c in cards.values():
        cats = c.pop("_cats")
        c["top_issue"] = cats.most_common(1)[0][0] if cats else "—"
        out.append(c)
    out.sort(key=lambda c: (c["open_tasks"], c["high"], c["messages"]), reverse=True)
    return out[:limit]


# Categories that count as a station's daily/shift report being posted.
_REPORT_CATEGORIES = ("daily_shift_report", "day_report")
# A site is "overdue" once it hasn't reported for this many days (incl. today).
OVERDUE_DAYS = 2


def _is_report(m: dict) -> bool:
    return any(c in (m.get("categories") or "") for c in _REPORT_CATEGORIES)


def report_status(messages: list[dict], as_of: str, overdue_days: int = OVERDUE_DAYS) -> dict:
    """Pure: from a message list, work out per-station daily-report standing.

    A station is any room that ``sites.is_station`` accepts, keyed by canonical
    name so "11" and "11 N&F Windchase" count once. ``as_of`` is a YYYY-MM-DD day.

    Returns ``{as_of, sites, reported, missing, overdue}`` where ``overdue`` is
    ``[{site, last_report, days_since}]`` for stations whose most recent report
    is ``overdue_days`` or more days old (``last_report`` None = never reported).
    """
    last_report: dict[str, str] = {}   # canonical site -> latest report date seen
    seen: set[str] = set()
    for m in messages:
        rn = m.get("room_name") or ""
        if not sites.is_station(rn):
            continue
        site = sites.canonical_name(rn)
        seen.add(site)
        if _is_report(m):
            day = _local_day(m.get("sent_at") or m.get("created_at") or m.get("timestamp_raw"))
            if day and day > last_report.get(site, ""):
                last_report[site] = day

    reported = sorted(s for s in seen if last_report.get(s) == as_of)
    missing = sorted(s for s in seen if last_report.get(s) != as_of)

    overdue = []
    for s in sorted(seen):
        last = last_report.get(s)
        days = _days_between(last, as_of) if last else None
        if days is None or days >= overdue_days:
            overdue.append({"site": s, "last_report": last, "days_since": days})
    return {"as_of": as_of, "sites": sorted(seen),
            "reported": reported, "missing": missing, "overdue": overdue}


def _days_between(start_day: str, end_day: str) -> int | None:
    try:
        a = datetime.strptime(start_day[:10], "%Y-%m-%d")
        b = datetime.strptime(end_day[:10], "%Y-%m-%d")
        return (b - a).days
    except (ValueError, TypeError):
        return None


def missing_daily_reports(as_of: str | None = None, overdue_days: int = OVERDUE_DAYS) -> dict:
    """Live entry point: report_status over all stored messages for ``as_of``
    (defaults to today, UTC)."""
    as_of = as_of or _local_today()
    return report_status(store.list_all("messages"), as_of, overdue_days)


# --- Report cutoff / late flagging ---------------------------------------
# Stations are expected to post their daily report by a local-time cutoff. A
# report filed after it is "late"; once the cutoff passes with no report, the
# station is "missing past cutoff". Default cutoff + per-site overrides via env.
DEFAULT_CUTOFF = os.getenv("OPS_REPORT_CUTOFF", "22:00")


def _site_cutoffs() -> dict[str, str]:
    """Per-site cutoff overrides keyed by site_key, e.g. {"11": "21:30"}."""
    raw = os.getenv("OPS_REPORT_CUTOFFS")
    if not raw:
        return {}
    try:
        d = json.loads(raw)
        return {str(k): str(v) for k, v in d.items()} if isinstance(d, dict) else {}
    except (ValueError, TypeError):
        return {}


def _central_offset_hours(utc_dt: datetime) -> int:
    """US Central UTC offset (-5 CDT / -6 CST), DST-aware, dependency-free.
    Mirrors the rule in brain.now_central (kept local to avoid a circular import)."""
    y = utc_dt.year

    def nth_sunday(month: int, n: int) -> int:
        first = datetime(y, month, 1, tzinfo=timezone.utc)
        return 1 + ((6 - first.weekday()) % 7) + (n - 1) * 7

    dst_start = datetime(y, 3, nth_sunday(3, 2), 8, tzinfo=timezone.utc)
    dst_end = datetime(y, 11, nth_sunday(11, 1), 7, tzinfo=timezone.utc)
    return -5 if dst_start <= utc_dt < dst_end else -6


def _cutoff_minutes(hhmm: str) -> int:
    try:
        h, m = hhmm.strip().split(":")
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return 22 * 60


def _local_minutes(utc_dt: datetime) -> int:
    """Minutes-since-midnight in US Central for a UTC datetime."""
    local = utc_dt + timedelta(hours=_central_offset_hours(utc_dt))
    return local.hour * 60 + local.minute


def _parse_dt(s: str | None) -> datetime | None:
    try:
        dt = datetime.fromisoformat((s or "").replace("Z", "+00:00"))
        return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def report_lateness(messages: list[dict], now_utc: datetime,
                    cutoffs: dict[str, str] | None = None,
                    default_cutoff: str = DEFAULT_CUTOFF) -> dict:
    """Pure: classify each station's report for *today* (Central) against its
    cutoff. Uses the message's send time (``timestamp_raw``/``created_at``).

    Returns ``{as_of, on_time, late, missing_past_cutoff}`` where ``late`` is
    ``[{site, filed, cutoff}]`` (HH:MM Central) and ``missing_past_cutoff`` is
    ``[{site, cutoff}]`` for stations with no report once their cutoff has passed.
    """
    cutoffs = cutoffs or {}
    today = (now_utc + timedelta(hours=_central_offset_hours(now_utc))).date().isoformat()
    now_min = _local_minutes(now_utc)

    # Latest report send-time today, per canonical site; and all seen stations.
    seen: set[str] = set()
    filed_min: dict[str, int] = {}
    for m in messages:
        rn = m.get("room_name") or ""
        if not sites.is_station(rn):
            continue
        site = sites.canonical_name(rn)
        seen.add(site)
        if not _is_report(m):
            continue
        dt = _parse_dt(m.get("timestamp_raw") or m.get("created_at"))
        if not dt:
            continue
        local = dt + timedelta(hours=_central_offset_hours(dt))
        if local.date().isoformat() != today:
            continue
        mins = local.hour * 60 + local.minute
        if mins > filed_min.get(site, -1):
            filed_min[site] = mins

    def _hhmm(mins: int) -> str:
        return f"{mins // 60:02d}:{mins % 60:02d}"

    on_time, late, missing = [], [], []
    for site in sorted(seen):
        cutoff = cutoffs.get(sites.site_key(site), default_cutoff)
        cmin = _cutoff_minutes(cutoff)
        if site in filed_min:
            (late if filed_min[site] > cmin else on_time).append(
                {"site": site, "filed": _hhmm(filed_min[site]), "cutoff": cutoff}
                if filed_min[site] > cmin else site)
        elif now_min >= cmin:  # window closed, nothing filed
            missing.append({"site": site, "cutoff": cutoff})
    return {"as_of": today, "on_time": on_time, "late": late,
            "missing_past_cutoff": missing}


def daily_report_lateness(now_utc: datetime | None = None) -> dict:
    """Live entry point: report_lateness over stored messages, now, and env cutoffs."""
    now_utc = now_utc or datetime.now(timezone.utc)
    return report_lateness(store.list_all("messages"), now_utc, _site_cutoffs(), DEFAULT_CUTOFF)


def room_summary(db_path: str | None, room: str) -> dict:
    needle = (room or "").lower()
    target_key = sites.site_key(room)  # e.g. "windchase" and "11" both -> "11"

    def _hit(m: dict) -> bool:
        rn = m.get("room_name") or ""
        if needle in rn.lower():  # preserve original substring match (incl. "" -> all)
            return True
        return bool(target_key) and sites.site_key(rn) == target_key

    matched = [m for m in store.list_all("messages") if _hit(m)]
    stats = None
    if matched:
        # Pick the busiest matching room name as the canonical one.
        by_room: dict[str, list] = defaultdict(list)
        for m in matched:
            by_room[m.get("room_name") or "Unknown"].append(m)
        room_name, msgs = max(by_room.items(), key=lambda kv: len(kv[1]))
        stats = {
            "room_name": room_name,
            "messages": len(msgs),
            "attachments": sum(m.get("attachment_count") or 0 for m in msgs),
            "high": sum(1 for m in msgs if m.get("priority") == "high"),
            "tasks": sum(1 for m in msgs if m.get("is_task")),
        }
    recent = _sort_recent([m for m in matched if not m.get("is_duplicate")])[:30]
    tasks = open_tasks(None, room, 30)
    return {"stats": stats, "open_tasks": tasks, "recent": recent}


def task_action(db_path: str | None, task_id: int, action: str, assignee: str | None = None) -> dict:
    t = store.get("tasks", task_id)
    if not t:
        return {"ok": False, "error": "task not found"}
    now = datetime.now(timezone.utc).isoformat()
    if action == "close":
        store.patch("tasks", task_id, {"status": "closed", "closed_at": now, "updated_at": now})
    elif action == "open":
        store.patch("tasks", task_id, {"status": "open", "closed_at": None, "updated_at": now})
    elif action == "assign":
        store.patch("tasks", task_id, {"assignee": assignee or "", "status": "assigned", "updated_at": now})
    else:
        return {"ok": False, "error": "unknown action"}
    return {"ok": True, "task_id": task_id, "action": action, "assignee": assignee}


def render_text_report(db_path: str = "data/ops_bot.sqlite3") -> str:
    d = dashboard(db_path)
    lines = []
    lines.append("# Now & Forever Ops Dashboard v3")
    lines.append("")
    lines.append(f"Messages parsed: {d['totals'].get('messages', 0)}")
    lines.append(f"Attachment references: {d['totals'].get('attachments', 0)}")
    lines.append(f"Duplicates detected: {d['totals'].get('duplicates', 0)}")
    lines.append("")
    lines.append("## Open task counts")
    for row in d['tasks']:
        lines.append(f"- {row['status']}: {row['count']}")
    lines.append("")
    lines.append("## Top categories")
    for cat, count in list(d['categories'].items())[:12]:
        lines.append(f"- {cat}: {count}")
    lines.append("")
    lines.append("## Top rooms")
    for r in d['top_rooms']:
        lines.append(f"- {r['room_name']}: {r['messages']} messages, {r['tasks']} task-like, {r['high']} high priority")
    lines.append("")
    lines.append("## High priority")
    for item in high_priority(db_path, 30):
        msg = (item['message'] or '').replace('\n', ' ')[:240]
        lines.append(f"- [{item['room_name']}] {msg}")
    return "\n".join(lines)


def _g(v) -> str:
    """Format a gallon value for the dashboard: blank for None, trimmed float."""
    if v is None:
        return "—"
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return html.escape(f"{v:,}" if isinstance(v, (int, float)) else str(v))


def _badge(priority: str) -> str:
    return f"<span class='badge {html.escape(priority or 'normal')}'>{html.escape(priority or 'normal')}</span>"


def render_dashboard_html(db_path: str = "data/ops_bot.sqlite3") -> str:
    d = dashboard(db_path)
    alerts = high_priority(db_path, 20)
    tasks = open_tasks(db_path, limit=35)
    cats = list(d['categories'].items())[:10]
    html_parts = [HTML_HEAD, "<body><main>"]
    html_parts.append("<h1>Now & Forever Ops Dashboard <span>v3 live-ready</span></h1>")
    totals = d['totals']
    open_count = next((x['count'] for x in d['tasks'] if x['status']=='open'), 0)
    html_parts.append(f"""
    <section class='cards'>
      <div class='card'><div class='num'>{totals.get('messages',0)}</div><div>Messages</div></div>
      <div class='card'><div class='num'>{totals.get('attachments',0)}</div><div>Attachments</div></div>
      <div class='card'><div class='num'>{open_count}</div><div>Open Tasks</div></div>
      <div class='card'><div class='num'>{sum(1 for a in alerts)}</div><div>High Alerts Shown</div></div>
    </section>
    """)
    html_parts.append("<section><h2>Top Rooms</h2><table><tr><th>Room</th><th>Messages</th><th>Tasks</th><th>High</th><th>Attachments</th></tr>")
    for r in d['top_rooms']:
        room_url = "/rooms/" + html.escape(r['room_name']).replace(' ', '%20').replace('&', '%26')
        html_parts.append(f"<tr><td><a href='{room_url}'>{html.escape(r['room_name'])}</a></td><td>{r['messages']}</td><td>{r['tasks']}</td><td>{r['high']}</td><td>{r['attachments']}</td></tr>")
    html_parts.append("</table></section>")
    html_parts.append("<section><h2>Category Mix</h2><div class='chips'>")
    for cat, count in cats:
        html_parts.append(f"<span class='chip'>{html.escape(cat)} <b>{count}</b></span>")
    html_parts.append("</div></section>")

    # Fuel reconciliation: flagged BOL-vs-Veeder mismatches.
    flagged = fuel_discrepancies(db_path)
    html_parts.append(f"<section><h2>Fuel Reconciliation <span class='cat'>{len(flagged)} flagged</span></h2>")
    if not flagged:
        html_parts.append("<p><small>No BOL vs Veeder-Root discrepancies above threshold.</small></p>")
    else:
        html_parts.append("<table><tr><th>Store</th><th>Date</th><th>BOL</th><th>Veeder</th><th>Diff (gal)</th></tr>")
        for r in flagged:
            html_parts.append(
                f"<tr class='highline'><td>{html.escape(str(r.get('room_name') or ''))}</td>"
                f"<td>{html.escape(str(r.get('report_date') or ''))}</td>"
                f"<td>{_g(r.get('bol_gallons'))}</td><td>{_g(r.get('veeder_gallons'))}</td>"
                f"<td><b>{_g(r.get('discrepancy_gallons'))}</b></td></tr>")
        html_parts.append("</table>")
    html_parts.append("</section>")

    # Per-store scorecard.
    cards = store_scorecards(db_path)
    html_parts.append("<section><h2>Store Scorecard</h2><table><tr><th>Store</th><th>Open Tasks</th><th>High</th><th>Top Issue</th><th>Messages</th></tr>")
    for c in cards:
        room_url = "/rooms/" + html.escape(c['room_name']).replace(' ', '%20').replace('&', '%26')
        html_parts.append(
            f"<tr><td><a href='{room_url}'>{html.escape(c['room_name'])}</a></td>"
            f"<td>{c['open_tasks']}</td><td>{c['high_tasks']}</td>"
            f"<td><span class='cat'>{html.escape(c['top_issue'])}</span></td><td>{c['messages']}</td></tr>")
    html_parts.append("</table></section>")

    html_parts.append("<section><h2>High Priority Alerts</h2>")
    for a in alerts:
        html_parts.append(f"<article class='item highline'><b>{html.escape(a['room_name'])}</b> {_badge('high')} <small>{html.escape(fmt_ts(a.get('timestamp_raw')))}</small><p>{html.escape(a.get('message') or '')}</p><small>Sender: {html.escape(a.get('sender') or '')} · Assigned hint: {html.escape(a.get('assigned_hint') or '')}</small></article>")
    html_parts.append("</section>")
    html_parts.append("<section><h2>Open Tasks</h2>")
    for t in tasks:
        html_parts.append(task_card(t))
    html_parts.append("</section>")
    html_parts.append("</main></body></html>")
    return "".join(html_parts)


def task_card(t: dict) -> str:
    return f"""
    <article class='item'>
      <div><b>#{t['id']} · {html.escape(t['room_name'] or '')}</b> {_badge(t.get('priority') or 'normal')} <span class='cat'>{html.escape(t.get('category') or '')}</span></div>
      <p>{html.escape(t.get('task_title') or t.get('task_text') or '')}</p>
      <small>Sender: {html.escape(t.get('sender') or '')} · Assignee: {html.escape(t.get('assignee') or t.get('assigned_hint') or 'unassigned')} · Confidence: {t.get('confidence') or 0}</small>
      <form method='POST' action='/tasks/{t['id']}/close'><button>Close</button></form>
      <form method='POST' action='/tasks/{t['id']}/assign'><input name='assignee' placeholder='assign to'><button>Assign</button></form>
    </article>
    """


def render_tasks_html(db_path: str = "data/ops_bot.sqlite3", room: str | None = None) -> str:
    tasks = open_tasks(db_path, room=room, limit=150)
    parts = [HTML_HEAD, "<body><main><h1>Open Tasks</h1><p><a href='/dashboard'>← Dashboard</a></p>"]
    if room:
        parts.append(f"<h2>{html.escape(room)}</h2>")
    for t in tasks:
        parts.append(task_card(t))
    parts.append("</main></body></html>")
    return "".join(parts)


def render_alerts_html(db_path: str = "data/ops_bot.sqlite3") -> str:
    alerts = high_priority(db_path, 100)
    parts = [HTML_HEAD, "<body><main><h1>High Priority Alerts</h1><p><a href='/dashboard'>← Dashboard</a></p>"]
    for a in alerts:
        parts.append(f"<article class='item highline'><b>{html.escape(a['room_name'])}</b> {_badge('high')} <small>{html.escape(fmt_ts(a.get('timestamp_raw')))}</small><p>{html.escape(a.get('message') or '')}</p><small>Sender: {html.escape(a.get('sender') or '')} · Categories: {html.escape(a.get('categories') or '')}</small></article>")
    parts.append("</main></body></html>")
    return "".join(parts)


def render_room_html(db_path: str, room: str) -> str:
    data = room_summary(db_path, room)
    parts = [HTML_HEAD, f"<body><main><h1>{html.escape(room)}</h1><p><a href='/dashboard'>← Dashboard</a> · <a href='/tasks?room={html.escape(room)}'>Tasks only</a></p>"]
    if data['stats']:
        s = data['stats']
        parts.append(f"<section class='cards'><div class='card'><div class='num'>{s['messages']}</div><div>Messages</div></div><div class='card'><div class='num'>{s['tasks']}</div><div>Tasks</div></div><div class='card'><div class='num'>{s['high']}</div><div>High</div></div></section>")
    parts.append("<h2>Open tasks</h2>")
    for t in data['open_tasks']:
        parts.append(task_card(t))
    parts.append("<h2>Recent messages</h2>")
    for m in data['recent']:
        parts.append(f"<article class='item'><b>{html.escape(m.get('sender') or '')}</b> {_badge(m.get('priority') or 'normal')} <small>{html.escape(fmt_ts(m.get('timestamp_raw')))}</small><p>{html.escape(m.get('message') or '')}</p><small>{html.escape(m.get('categories') or '')}</small></article>")
    parts.append("</main></body></html>")
    return "".join(parts)


def render_messages_html(db_path=None, room=None, q=None, dms_only=False, limit=400) -> str:
    msgs = store.list_all("messages")
    if dms_only:
        msgs = [m for m in msgs if m.get("is_dm")]
    if room:
        msgs = [m for m in msgs if room.lower() in (m.get("room_name") or "").lower()]
    if q:
        ql = q.lower()
        msgs = [m for m in msgs if ql in (m.get("message") or "").lower()
                or ql in (m.get("sender") or "").lower()]
    msgs = _sort_recent(msgs)[:limit]
    title = "Bot DMs" if dms_only else "All Messages"
    parts = [HTML_HEAD, f"<body><main><h1>{html.escape(title)} <span>({len(msgs)})</span></h1>",
             "<p><a href='/dashboard'>← Dashboard</a> · <a href='/messages'>All</a> · <a href='/dms'>DMs</a></p>",
             "<form method='get'><input name='q' placeholder='search text or sender' value=\""
             + html.escape(q or "") + "\"><button>Search</button></form>"]
    for m in msgs:
        dm = " 🔒DM" if m.get("is_dm") else ""
        ts = html.escape((m.get("sent_at") or m.get("timestamp_raw") or "")[:19])
        parts.append(
            f"<article class='item'><div><b>{html.escape(m.get('sender') or '?')}</b> "
            f"<small>{html.escape(m.get('room_name') or '')}{dm} · {ts}</small></div>"
            f"<p>{html.escape((m.get('message') or '')[:1500])}</p></article>")
    parts.append("</main></body></html>")
    return "".join(parts)


def _is_bot_msg(m: dict) -> bool:
    return bool(m.get("is_bot_reply")) or "Ops Bot" in (m.get("sender") or "")


def render_dms_html(db_path=None) -> str:
    msgs = [m for m in store.list_all("messages") if m.get("is_dm")]
    # Group by DM space so each person's conversation (both sides) is together.
    by_space: dict = {}
    for m in msgs:
        by_space.setdefault(m.get("room_id") or m.get("sender") or "?", []).append(m)

    def person_of(ms):
        for m in ms:
            if not _is_bot_msg(m) and (m.get("sender") or ""):
                return m["sender"]
        return ms[0].get("sender") or "?"

    # newest conversation first
    convos = sorted(by_space.values(),
                    key=lambda ms: max((x.get("sent_at") or "") for x in ms), reverse=True)
    parts = [HTML_HEAD, f"<body><main><h1>Bot DMs <span>({len(convos)} conversations · {len(msgs)} msgs)</span></h1>",
             "<p><a href='/dashboard'>← Dashboard</a> · <a href='/messages'>All messages</a></p>",
             "<p><small>Full DM threads — the person's messages and the bot's replies. "
             "(Replies are stored from now on; older threads show the person's side only — "
             "Google Vault has the complete history.)</small></p>"]
    for ms in convos:
        person = person_of(ms)
        ms_sorted = sorted(ms, key=lambda x: (x.get("sent_at") or "", x.get("seq") or 0))
        parts.append(f"<section><h2>{html.escape(person)} <small>({len(ms)})</small></h2>")
        for m in ms_sorted[-60:]:
            ts = html.escape(fmt_ts(m.get("sent_at") or m.get("timestamp_raw")))
            bot = _is_bot_msg(m)
            who = "🤖 Bot" if bot else f"🧑 {html.escape(person)}"
            style = " style='background:#eef5ff'" if bot else ""
            parts.append(f"<article class='item'{style}><small>{who} · {ts}</small>"
                         f"<p>{html.escape((m.get('message') or '')[:1200])}</p></article>")
        parts.append("</section>")
    parts.append("</main></body></html>")
    return "".join(parts)


HTML_HEAD = """
<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>
<title>Now & Forever Ops</title>
<style>
:root{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Arial,sans-serif;color:#111;background:#f6f7f9}body{margin:0}main{max-width:1150px;margin:0 auto;padding:28px}h1{font-size:34px;margin:8px 0 22px}h1 span{font-size:16px;color:#666}h2{margin-top:30px}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px}.card,.item,section{background:white;border:1px solid #e4e6eb;border-radius:14px;padding:16px;margin:12px 0;box-shadow:0 1px 2px rgba(0,0,0,.03)}.num{font-size:32px;font-weight:800}table{width:100%;border-collapse:collapse;background:white;border-radius:12px;overflow:hidden}td,th{padding:10px;border-bottom:1px solid #eee;text-align:left}.badge{display:inline-block;border-radius:999px;padding:2px 9px;font-size:12px;font-weight:700;background:#e8edf7}.badge.high{background:#ffe3e3;color:#9b111e}.badge.medium{background:#fff1cc;color:#7a5200}.cat,.chip{display:inline-block;background:#eef2f7;border-radius:999px;padding:3px 9px;margin:3px;font-size:12px}.highline{border-left:6px solid #d22}p{white-space:pre-wrap;line-height:1.35}small{color:#666}button{border:0;background:#111;color:white;border-radius:8px;padding:7px 11px;margin-top:8px;cursor:pointer}input{padding:7px;border:1px solid #ccc;border-radius:8px;margin-right:6px}form{display:inline-block;margin-right:8px}a{color:#0b57d0;text-decoration:none}
</style></head>
"""
