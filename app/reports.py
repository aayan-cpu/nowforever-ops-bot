from __future__ import annotations

import html
import sqlite3
from collections import defaultdict
from typing import Iterable

from app.database import connect


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict]:
    return [dict(r) for r in rows]


def dashboard(db_path: str = "data/ops_bot.sqlite3") -> dict:
    with connect(db_path) as conn:
        totals = dict(conn.execute("SELECT COUNT(*) messages, COALESCE(SUM(attachment_count),0) attachments, SUM(is_duplicate) duplicates FROM messages").fetchone())
        task_counts = rows_to_dicts(conn.execute("SELECT status, COUNT(*) count FROM tasks GROUP BY status ORDER BY status"))
        priority_counts = rows_to_dicts(conn.execute("SELECT priority, COUNT(*) count FROM messages GROUP BY priority ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END"))
        top_rooms = rows_to_dicts(conn.execute("""
            SELECT room_name, COUNT(*) messages, COALESCE(SUM(attachment_count),0) attachments,
                   SUM(CASE WHEN priority='high' THEN 1 ELSE 0 END) high,
                   SUM(CASE WHEN is_task=1 THEN 1 ELSE 0 END) tasks
            FROM messages GROUP BY room_name ORDER BY messages DESC LIMIT 12
        """))
        category_counts = defaultdict(int)
        for row in conn.execute("SELECT categories FROM messages WHERE COALESCE(is_duplicate,0)=0"):
            for cat in (row[0] or "general").split(';'):
                category_counts[cat] += 1
        return {
            "totals": totals,
            "tasks": task_counts,
            "priorities": priority_counts,
            "top_rooms": top_rooms,
            "categories": dict(sorted(category_counts.items(), key=lambda x: x[1], reverse=True)),
        }


def open_tasks(db_path: str = "data/ops_bot.sqlite3", room: str | None = None, limit: int = 50, status: str = "open") -> list[dict]:
    with connect(db_path) as conn:
        where = ["status=?"]
        params: list = [status]
        if room:
            where.append("room_name LIKE ?")
            params.append(f"%{room}%")
        params.append(limit)
        rows = conn.execute(f"""
            SELECT id, room_name, priority, category, sender, task_title, task_text, assigned_hint, assignee, status, confidence
            FROM tasks WHERE {' AND '.join(where)}
            ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, id DESC LIMIT ?
        """, params).fetchall()
        return rows_to_dicts(rows)


def high_priority(db_path: str = "data/ops_bot.sqlite3", limit: int = 50) -> list[dict]:
    with connect(db_path) as conn:
        rows = conn.execute("""
            SELECT room_name, timestamp_raw, sender, message, categories, attachment_count, assigned_hint, confidence
            FROM messages WHERE priority='high' AND COALESCE(is_duplicate,0)=0
            ORDER BY id DESC LIMIT ?
        """, (limit,)).fetchall()
        return rows_to_dicts(rows)


def room_summary(db_path: str, room: str) -> dict:
    with connect(db_path) as conn:
        stats = conn.execute("""
            SELECT room_name, COUNT(*) messages, COALESCE(SUM(attachment_count),0) attachments,
                   SUM(CASE WHEN priority='high' THEN 1 ELSE 0 END) high,
                   SUM(CASE WHEN is_task=1 THEN 1 ELSE 0 END) tasks
            FROM messages WHERE room_name LIKE ? GROUP BY room_name ORDER BY messages DESC LIMIT 1
        """, (f"%{room}%",)).fetchone()
        recent = rows_to_dicts(conn.execute("""
            SELECT timestamp_raw, sender, priority, categories, message, attachments, assigned_hint, confidence
            FROM messages WHERE room_name LIKE ? AND COALESCE(is_duplicate,0)=0
            ORDER BY id DESC LIMIT 30
        """, (f"%{room}%",)).fetchall())
        tasks = open_tasks(db_path, room, 30)
        return {"stats": dict(stats) if stats else None, "open_tasks": tasks, "recent": recent}


def task_action(db_path: str, task_id: int, action: str, assignee: str | None = None) -> dict:
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            return {"ok": False, "error": "task not found"}
        if action == "close":
            conn.execute("UPDATE tasks SET status='closed', closed_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE id=?", (task_id,))
        elif action == "open":
            conn.execute("UPDATE tasks SET status='open', closed_at=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?", (task_id,))
        elif action == "assign":
            conn.execute("UPDATE tasks SET assignee=?, status='assigned', updated_at=CURRENT_TIMESTAMP WHERE id=?", (assignee or "", task_id))
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
