from __future__ import annotations

import html
from collections import defaultdict
from datetime import datetime, timezone

from app import store, sites


def _sort_recent(rows: list[dict]) -> list[dict]:
    # Newest first: prefer numeric seq, fall back to created_at / timestamp_raw.
    return sorted(rows, key=lambda r: (r.get("seq") or 0, r.get("created_at") or r.get("timestamp_raw") or ""), reverse=True)


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


def high_priority(db_path: str | None = None, limit: int = 50) -> list[dict]:
    rows = [m for m in store.list_all("messages")
            if m.get("priority") == "high" and not m.get("is_duplicate")]
    return _sort_recent(rows)[:limit]


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
    html_parts.append("<section><h2>High Priority Alerts</h2>")
    for a in alerts:
        html_parts.append(f"<article class='item highline'><b>{html.escape(a['room_name'])}</b> {_badge('high')} <small>{html.escape(a.get('timestamp_raw') or '')}</small><p>{html.escape(a.get('message') or '')}</p><small>Sender: {html.escape(a.get('sender') or '')} · Assigned hint: {html.escape(a.get('assigned_hint') or '')}</small></article>")
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
        parts.append(f"<article class='item highline'><b>{html.escape(a['room_name'])}</b> {_badge('high')} <small>{html.escape(a.get('timestamp_raw') or '')}</small><p>{html.escape(a.get('message') or '')}</p><small>Sender: {html.escape(a.get('sender') or '')} · Categories: {html.escape(a.get('categories') or '')}</small></article>")
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
        parts.append(f"<article class='item'><b>{html.escape(m.get('sender') or '')}</b> {_badge(m.get('priority') or 'normal')} <small>{html.escape(m.get('timestamp_raw') or '')}</small><p>{html.escape(m.get('message') or '')}</p><small>{html.escape(m.get('categories') or '')}</small></article>")
    parts.append("</main></body></html>")
    return "".join(parts)


HTML_HEAD = """
<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>
<title>Now & Forever Ops</title>
<style>
:root{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Arial,sans-serif;color:#111;background:#f6f7f9}body{margin:0}main{max-width:1150px;margin:0 auto;padding:28px}h1{font-size:34px;margin:8px 0 22px}h1 span{font-size:16px;color:#666}h2{margin-top:30px}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px}.card,.item,section{background:white;border:1px solid #e4e6eb;border-radius:14px;padding:16px;margin:12px 0;box-shadow:0 1px 2px rgba(0,0,0,.03)}.num{font-size:32px;font-weight:800}table{width:100%;border-collapse:collapse;background:white;border-radius:12px;overflow:hidden}td,th{padding:10px;border-bottom:1px solid #eee;text-align:left}.badge{display:inline-block;border-radius:999px;padding:2px 9px;font-size:12px;font-weight:700;background:#e8edf7}.badge.high{background:#ffe3e3;color:#9b111e}.badge.medium{background:#fff1cc;color:#7a5200}.cat,.chip{display:inline-block;background:#eef2f7;border-radius:999px;padding:3px 9px;margin:3px;font-size:12px}.highline{border-left:6px solid #d22}p{white-space:pre-wrap;line-height:1.35}small{color:#666}button{border:0;background:#111;color:white;border-radius:8px;padding:7px 11px;margin-top:8px;cursor:pointer}input{padding:7px;border:1px solid #ccc;border-radius:8px;margin-right:6px}form{display:inline-block;margin-right:8px}a{color:#0b57d0;text-decoration:none}
</style></head>
"""
