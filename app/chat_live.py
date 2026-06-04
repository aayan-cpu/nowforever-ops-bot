from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from app.classifier import classify_message, category_string, clean_text, normalize_sender
from app.database import connect, init_db
from app.ingest import pick_primary_category
from app.reports import dashboard, high_priority, open_tasks, room_summary, task_action

DB_PATH = "data/ops_bot.sqlite3"

ADMIN_EMAILS = {"aayan@khawarsons.com", "aayan@khawar-sons.com"}


def is_admin(sender: str) -> bool:
    return (sender or "").lower().strip() in ADMIN_EMAILS


def _get(obj: dict, path: str, default: Any = None) -> Any:
    cur: Any = obj
    for part in path.split('.'):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def extract_chat_event(event: dict) -> dict:
    """Normalize a Google Chat HTTP event into our internal message shape.

    This supports real Google Chat events and simple local test payloads.
    """
    event_type = event.get("type") or event.get("eventType") or "MESSAGE"
    message_obj = event.get("message") or {}
    space_obj = event.get("space") or message_obj.get("space") or {}
    user_obj = event.get("user") or message_obj.get("sender") or event.get("sender") or {}

    text = (
        event.get("text")
        or message_obj.get("argumentText")
        or message_obj.get("text")
        or event.get("messageText")
        or ""
    )
    text = clean_text(text)

    room_name = (
        event.get("room_name")
        or event.get("room")
        or space_obj.get("displayName")
        or space_obj.get("spaceDetails", {}).get("displayName")
        or space_obj.get("name")
        or "Direct Message / Unknown Space"
    )
    room_id = event.get("room_id") or space_obj.get("name") or room_name

    sender = (
        event.get("sender")
        or user_obj.get("email")
        or user_obj.get("displayName")
        or user_obj.get("name")
        or message_obj.get("sender", {}).get("displayName")
        or "unknown"
    )

    attachments = []
    for a in message_obj.get("attachment", []) or message_obj.get("attachments", []) or event.get("attachments", []) or []:
        if isinstance(a, dict):
            attachments.append(a.get("contentName") or a.get("name") or a.get("filename") or "attachment")
        else:
            attachments.append(str(a))

    timestamp = (
        event.get("timestamp_raw")
        or message_obj.get("createTime")
        or event.get("eventTime")
        or datetime.now(timezone.utc).isoformat()
    )
    data_id = message_obj.get("name") or event.get("data_id") or f"live-{datetime.now(timezone.utc).timestamp()}"

    return {
        "event_type": event_type,
        "room_id": str(room_id),
        "room_name": str(room_name),
        "sender": normalize_sender(str(sender)),
        "timestamp_raw": str(timestamp),
        "message": text,
        "attachments": " | ".join(attachments),
        "attachment_count": len(attachments),
        "data_id": str(data_id),
        "raw_event": event,
    }


def ingest_live_event(event: dict, db_path: str = DB_PATH) -> dict:
    """Classify + store one Google Chat event. Creates a task if action-worthy."""
    init_db(db_path)
    msg = extract_chat_event(event)
    c = classify_message(msg["message"], msg["attachment_count"], msg["room_name"])
    category = pick_primary_category(c.categories)

    with connect(db_path) as conn:
        # Avoid creating duplicate tasks if Google retries the same event.
        existing = conn.execute(
            "SELECT id FROM messages WHERE data_id=? OR fingerprint=? LIMIT 1",
            (msg["data_id"], c.fingerprint),
        ).fetchone()
        if existing:
            return {"ok": True, "duplicate": True, "message_id": existing["id"], "reply": build_reply(msg, c, None, db_path)}

        cur = conn.execute(
            """
            INSERT INTO messages (
                source_idx, room_id, room_name, data_id, sender, timestamp_raw, message,
                attachments, attachment_count, categories, priority, is_task,
                extracted_amounts, extracted_gallons, extracted_prices, assigned_hint,
                fingerprint, confidence, is_duplicate
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                None, msg["room_id"], msg["room_name"], msg["data_id"], msg["sender"], msg["timestamp_raw"], msg["message"],
                msg["attachments"], msg["attachment_count"], category_string(c.categories), c.priority, 1 if c.is_task else 0,
                json.dumps(c.extracted_amounts), json.dumps(c.extracted_gallons), json.dumps(c.extracted_prices), c.assigned_hint,
                c.fingerprint, c.confidence, 0,
            ),
        )
        message_id = cur.lastrowid
        task_id = None
        if c.is_task or c.priority == "high":
            tcur = conn.execute(
                """
                INSERT INTO tasks (message_id, room_name, sender, task_title, task_text, category, priority, assigned_hint, assignee, source_fingerprint, confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (message_id, msg["room_name"], msg["sender"], c.task_title, msg["message"][:4000], category, c.priority, c.assigned_hint, c.assigned_hint, c.fingerprint, c.confidence),
            )
            task_id = tcur.lastrowid

    return {
        "ok": True,
        "duplicate": False,
        "message_id": message_id,
        "task_id": task_id,
        "priority": c.priority,
        "categories": c.categories,
        "is_task": c.is_task,
        "reply": build_reply(msg, c, task_id, db_path),
    }


def google_chat_response(text: str) -> dict:
    # Workspace Add-on response format (userAgent: Google-gsuiteaddons)
    if not text:
        return {}
    return {
        "hostAppDataAction": {
            "chatDataAction": {
                "createMessageAction": {
                    "message": {
                        "text": text[:3900]
                    }
                }
            }
        }
    }


def should_reply(event: dict, c_priority: str | None = None) -> bool:
    text = (_get(event, "message.text", "") or event.get("text") or "").lower()
    if "nowforever" in text or "ops bot" in text or "@" in text:
        return True
    if c_priority == "high":
        return True
    return False


def build_reply(msg: dict, c, task_id: int | None, db_path: str = DB_PATH) -> str:
    text = msg["message"] or ""
    lower = text.lower()
    admin = is_admin(msg["sender"])

    # Admin-only commands.
    if re.search(r"\b(summary|dashboard|what happened)\b", lower):
        if not admin:
            return "⛔ Only the admin can run that command."
        d = dashboard(db_path)
        open_count = next((x["count"] for x in d["tasks"] if x["status"] == "open"), 0)
        high_count = next((x["count"] for x in d["priorities"] if x["priority"] == "high"), 0)
        top = d["top_rooms"][:5]
        lines = ["📊 Now & Forever Ops Summary", f"Messages: {d['totals'].get('messages', 0)}", f"Open tasks: {open_count}", f"High priority messages: {high_count}", "", "Top active rooms:"]
        for r in top:
            lines.append(f"• {r['room_name']}: {r['tasks']} tasks, {r['high']} high")
        return "\n".join(lines)

    if re.search(r"\b(alerts?|urgent)\b", lower):
        if not admin:
            return "⛔ Only the admin can run that command."
        alerts = high_priority(db_path, 8)
        if not alerts:
            return "No high-priority alerts found."
        lines = ["🚨 High Priority Alerts"]
        for a in alerts:
            lines.append(f"• [{a['room_name']}] {(a.get('message') or '')[:160]}")
        return "\n".join(lines)

    if re.search(r"\b(tasks?|open tasks?)\b", lower):
        if not admin:
            return "⛔ Only the admin can run that command."
        tasks = open_tasks(db_path, limit=10)
        if not tasks:
            return "No open tasks found."
        lines = ["✅ Open Tasks"]
        for t in tasks:
            lines.append(f"• #{t['id']} [{t['room_name']}] {t.get('task_title') or t.get('task_text')}")
        return "\n".join(lines)

    m = re.search(r"\bclose task\s*(\d+)\b|\bclose\s*(\d+)\b", lower)
    if m:
        if not admin:
            return "⛔ Only the admin can close tasks."
        task_id_to_close = int(m.group(1) or m.group(2))
        res = task_action(db_path, task_id_to_close, "close")
        return f"Closed task #{task_id_to_close}." if res.get("ok") else f"Could not close task #{task_id_to_close}: {res.get('error')}"

    m = re.search(r"\bassign task\s*(\d+)\s+(.+)$|\bassign\s*(\d+)\s+(.+)$", text, flags=re.I | re.S)
    if m:
        if not admin:
            return "⛔ Only the admin can assign tasks."
        task_id_to_assign = int(m.group(1) or m.group(3))
        assignee = (m.group(2) or m.group(4) or "").strip()
        res = task_action(db_path, task_id_to_assign, "assign", assignee)
        return f"Assigned task #{task_id_to_assign} to {assignee}." if res.get("ok") else f"Could not assign task #{task_id_to_assign}: {res.get('error')}"

    m = re.search(r"\bshow\s+(.+)$", text, flags=re.I)
    if m:
        if not admin:
            return "⛔ Only the admin can run that command."
        room = m.group(1).strip()
        rs = room_summary(db_path, room)
        if not rs.get("stats"):
            return f"I could not find room/site matching: {room}"
        s = rs["stats"]
        lines = [f"🏪 {s['room_name']}", f"Messages: {s['messages']} · Tasks: {s['tasks']} · High: {s['high']}"]
        for t in rs.get("open_tasks", [])[:8]:
            lines.append(f"• #{t['id']} {t.get('task_title') or t.get('task_text')}")
        return "\n".join(lines)

    # Automatic task/alert confirmation.
    if task_id:
        icon = "🚨" if c.priority == "high" else "📝"
        return f"{icon} Logged {c.priority} task #{task_id}\nSite/room: {msg['room_name']}\nCategory: {pick_primary_category(c.categories)}\nAssignee: {c.assigned_hint or 'unassigned'}"
    if c.priority == "high":
        return f"🚨 High-priority message detected in {msg['room_name']}. I logged it for review."
    return "Got it."


def is_direct_message(event: dict) -> bool:
    space = event.get("space") or event.get("message", {}).get("space") or {}
    return space.get("type") == "DM" or space.get("singleUserBotDm") is True


def handle_google_chat_event(event: dict, db_path: str = DB_PATH) -> dict:
    print(f"[chat_event] type={event.get('type')} space={event.get('space')} user={event.get('user')}")
    event_type = event.get("type") or event.get("eventType") or "MESSAGE"
    if event_type == "ADDED_TO_SPACE":
        space = event.get("space", {})
        name = space.get("displayName") or space.get("name") or "this space"
        return google_chat_response(f"NowAndForeverBot is active in {name}. Send me: summary, alerts, tasks, close task #, assign task #, or show <room>.")
    if event_type == "REMOVED_FROM_SPACE":
        return google_chat_response("")

    result = ingest_live_event(event, db_path)
    c_priority = result.get("priority")
    reply = result.get("reply") or "Got it. Try: summary, alerts, tasks, or show <room name>."
    # Always reply to DMs. In rooms, only reply if mentioned or high priority.
    if is_direct_message(event) or should_reply(event, c_priority):
        return google_chat_response(reply)
    # Fallback: always reply so Google Chat doesn't show "not responding"
    return google_chat_response(reply)
