from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any

from app.classifier import classify_message, category_string, clean_text, normalize_sender
from app import store, vision, chat_media, brain
from app.ingest import pick_primary_category
from app.reports import dashboard, high_priority, open_tasks, room_summary, task_action

DB_PATH = "data/ops_bot.sqlite3"

# Roles. The OWNER is the top of the hierarchy and is always an admin — no role
# or env change can place anyone above the owner. ADMINS get full powers
# (commands, close/assign, AI actions). Both are editable via env vars so people
# can be added/removed without a code change. (Future: scoped, position-based
# roles below admin — see docs/ROLES.md.)
OWNER_EMAIL = os.getenv("OPS_OWNER_EMAIL", "aayan@khawarsons.com").lower().strip()
ADMIN_EMAILS = {e.strip().lower() for e in os.getenv(
    "OPS_ADMIN_EMAILS",
    "aayan@khawarsons.com,admin1@nowandforever.com,admin2@nowandforever.com",
).split(",") if e.strip()}
ADMIN_EMAILS.add(OWNER_EMAIL)  # owner is always an admin

# Quiet mode: while testing, the bot ingests/classifies every space message
# (tasks, dashboard, alerts keep working) but posts NOTHING visible in rooms.
# It still replies in DMs so the admin can verify functionality. Flip this on
# later (env var OPS_REPLY_IN_SPACES=true) to let it talk in spaces.
REPLY_IN_SPACES = os.getenv("OPS_REPLY_IN_SPACES", "false").lower() in {"1", "true", "yes"}


def is_admin(sender: str) -> bool:
    return (sender or "").lower().strip() in ADMIN_EMAILS


def is_owner(sender: str) -> bool:
    return (sender or "").lower().strip() == OWNER_EMAIL


def remember_admin_dm(email: str, space_id: str) -> None:
    """When an admin DMs the bot, record their DM space so digests can reach them."""
    if not email or not space_id or not space_id.startswith("spaces/"):
        return
    try:
        cid = email.lower().replace("/", "_")
        payload = {"email": email.lower(), "space": space_id}
        if store.get("admin_dms", cid):
            store.patch("admin_dms", cid, payload)
        else:
            store.create("admin_dms", payload, doc_id=cid)
    except Exception as e:
        print(f"[admin_dm] {e}", flush=True)


def _get(obj: dict, path: str, default: Any = None) -> Any:
    cur: Any = obj
    for part in path.split('.'):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def extract_chat_event(event: dict) -> dict:
    """Normalize a Google Chat HTTP event into our internal message shape.

    Supports both traditional Chat API format and Workspace Add-on (gsuiteaddons) format.
    """
    import sys
    print(f"[raw_event] {json.dumps(event)[:3000]}", flush=True)
    sys.stdout.flush()

    # Workspace Add-on wraps everything under event["chat"]
    chat_wrapper = event.get("chat") or {}
    if chat_wrapper:
        event = {**event, **chat_wrapper}

    # Add-on uses messagePayload.message, not message directly
    message_payload = event.get("messagePayload") or {}
    message_obj = message_payload.get("message") or event.get("message") or {}
    space_obj = message_payload.get("space") or event.get("space") or message_obj.get("space") or {}
    user_obj = event.get("user") or message_obj.get("sender") or event.get("sender") or {}

    event_type = (
        "MESSAGE" if message_payload or event.get("message")
        else event.get("type") or event.get("eventType") or "MESSAGE"
    )

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
        "image_attachments": chat_media.image_attachments(message_obj),
        "data_id": str(data_id),
        "raw_event": event,
    }


# Operational signal: words that mean a photo is worth auto-reading (reports,
# deliveries, equipment, money). Non-operational photos are logged but only read
# on demand when someone asks about them.
_OPS_KW = re.compile(
    r"\b(report|bol|veeder|gas|gallons?|diesel|fuel|delivery|deliver|pump|tank|"
    r"broke|broken|not working|down|power|outage|ice|machine|printer|register|"
    r"deposit|sales|invoice|sscs|price|meter|reading|shift|closing)\b", re.I)
_OPS_CATEGORIES = {"fuel_delivery_issue", "equipment_maintenance", "sales_issue",
                   "admin_request_task", "daily_shift_report", "deposit_cash_bank",
                   "fuel_price_competition"}


def _is_operational(c, text: str) -> bool:
    if c.is_task or c.priority in ("high", "medium"):
        return True
    if any(cat in c.categories for cat in _OPS_CATEGORIES):
        return True
    return bool(_OPS_KW.search(text or ""))


def _no_vision() -> dict:
    return {"results": [], "needs_review": False, "reason": "", "summary": "", "category": "image_review"}


def analyze_images(msg: dict) -> dict:
    """Download + AI-analyze any image attachments. Best-effort: never raises.

    Returns {"results": [...], "needs_review": bool, "reason": str, "summary": str}.
    No-op (empty) unless ANTHROPIC_API_KEY is set and there are image attachments.
    """
    out = {"results": [], "needs_review": False, "reason": "", "summary": "",
           "category": "image_review"}
    images = msg.get("image_attachments") or []
    if not images or not vision.enabled():
        return out
    lines = []
    for img in images[:5]:  # cap per message
        try:
            data = chat_media.download_attachment(img["resource_name"])
            if not data:
                continue
            res = vision.analyze_image(data, img.get("content_type", "image/jpeg"),
                                       context=f"Room: {msg.get('room_name')}. {msg.get('message','')}")
            out["results"].append(res)
            lines.append(f"📷 {res.get('doc_type','image')}: {res.get('summary','')}")
            # Log day-report figures so they're queryable (get_reports / volumes).
            if res.get("doc_type") == "day_report":
                try:
                    store.create("day_reports", {
                        "room_name": msg.get("room_name"), "report_date": res.get("report_date"),
                        "shift": res.get("shift"), "total_sales": res.get("total_sales"),
                        "inside_sales": res.get("inside_sales"), "fuel_sales": res.get("fuel_sales"),
                        "fuel_gallons_sold": res.get("fuel_gallons_sold"),
                        "summary": res.get("summary"), "data_id": msg.get("data_id"),
                    })
                except Exception as e:
                    print(f"[vision] day_report store: {e}", flush=True)
            # Log BOL/Veeder readings for fuel reconciliation / shrinkage tracking.
            if res.get("bol_gallons") is not None or res.get("veeder_gallons") is not None:
                try:
                    store.create("fuel_events", {
                        "room_name": msg.get("room_name"), "report_date": res.get("report_date"),
                        "doc_type": res.get("doc_type"), "bol_gallons": res.get("bol_gallons"),
                        "veeder_gallons": res.get("veeder_gallons"),
                        "discrepancy_gallons": res.get("discrepancy_gallons"),
                        "summary": res.get("summary"), "data_id": msg.get("data_id"),
                    })
                except Exception as e:
                    print(f"[vision] fuel_event store: {e}", flush=True)
            if res.get("needs_review"):
                out["needs_review"] = True
                out["reason"] = res.get("review_reason") or "image needs review"
                out["category"] = res.get("review_category") or "image_review"
        except Exception as e:  # vision/network failure must never break ingest
            print(f"[vision] error: {e}", flush=True)
    out["summary"] = "\n".join(lines)
    return out


def ingest_live_event(event: dict, db_path: str = DB_PATH) -> dict:
    """Classify + store one Google Chat event in Firestore. Creates a task if action-worthy."""
    msg = extract_chat_event(event)
    c = classify_message(msg["message"], msg["attachment_count"], msg["room_name"])
    category = pick_primary_category(c.categories)

    # Avoid duplicate tasks if Google retries the same event.
    existing = store.find("messages", "data_id", msg["data_id"], limit=1) or \
        store.find("messages", "fingerprint", c.fingerprint, limit=1)
    if existing:
        cmd = build_reply(msg, c, None, db_path)
        return {"ok": True, "duplicate": True, "message_id": existing[0]["id"],
                "reply": cmd or "Got it.", "command_matched": cmd is not None,
                "text": msg["message"], "room_name": msg["room_name"], "sender": msg["sender"]}

    # Auto-read only OPERATIONAL images (reports, BOLs, deliveries, equipment, money).
    # Other photos are still logged; the bot reads them on demand if someone asks.
    vis = analyze_images(msg) if _is_operational(c, msg["message"]) else _no_vision()
    priority = "high" if vis["needs_review"] else c.priority
    is_task = c.is_task or vis["needs_review"]

    now = datetime.now(timezone.utc).isoformat()
    message_doc = store.create("messages", {
        "seq": store.next_seq("messages"),
        "room_id": msg["room_id"], "room_name": msg["room_name"], "data_id": msg["data_id"],
        "sender": msg["sender"], "timestamp_raw": msg["timestamp_raw"], "message": msg["message"],
        "attachments": msg["attachments"], "attachment_count": msg["attachment_count"],
        "categories": category_string(c.categories), "priority": priority,
        "is_task": bool(is_task),
        "extracted_amounts": json.dumps(c.extracted_amounts),
        "extracted_gallons": json.dumps(c.extracted_gallons),
        "extracted_prices": json.dumps(c.extracted_prices),
        "assigned_hint": c.assigned_hint, "fingerprint": c.fingerprint,
        "confidence": c.confidence, "is_duplicate": False, "created_at": now,
        "vision_summary": vis["summary"], "vision": json.dumps(vis["results"]),
    })
    message_id = message_doc["id"]

    task_id = None
    if is_task or priority == "high":
        title = (f"REVIEW: {vis['reason']}" if vis["needs_review"] else c.task_title)
        body = msg["message"][:4000]
        if vis["summary"]:
            body = (body + "\n" + vis["summary"]).strip()[:4000]
        task_id = store.next_seq("tasks")
        store.create("tasks", {
            "id": task_id, "message_id": message_id, "room_name": msg["room_name"],
            "sender": msg["sender"], "task_title": title, "task_text": body,
            "category": (vis["category"] if vis["needs_review"] else category),
            "priority": priority, "assigned_hint": c.assigned_hint,
            "assignee": c.assigned_hint, "status": "open", "source_fingerprint": c.fingerprint,
            "confidence": c.confidence, "created_at": now, "updated_at": now,
        }, doc_id=str(task_id))

    # Instant high-priority alert: DM the owner the moment something urgent lands.
    if (priority == "high" and task_id
            and os.getenv("OPS_INSTANT_ALERTS", "true").lower() in {"1", "true", "yes"}):
        try:
            chat_media.post_to_space(
                os.getenv("OPS_ADMIN_DM_SPACE", "spaces/6AxGNyAAAAE"),
                f"🚨 New high-priority #{task_id} [{msg['room_name']}]\n{title}")
        except Exception as e:
            print(f"[alert] {e}", flush=True)

    cmd = build_reply(msg, c, task_id, db_path)
    reply = cmd if cmd is not None else default_ack(msg, c, task_id)
    if vis["summary"]:
        reply = (reply + "\n" + vis["summary"]).strip()
    return {
        "ok": True,
        "duplicate": False,
        "message_id": message_id,
        "task_id": task_id,
        "priority": priority,
        "categories": c.categories,
        "is_task": is_task,
        "vision": vis["results"],
        "vision_summary": vis["summary"],
        "reply": reply,
        "command_matched": cmd is not None,
        "text": msg["message"],
        "room_name": msg["room_name"],
        "sender": msg["sender"],
        "space_id": msg["room_id"],
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
    # In a room, only reply when the bot is explicitly addressed by name.
    # High-priority messages are still ingested/logged silently — we just don't
    # auto-chime-in on every captain's message (that would be spammy).
    mp = event.get("messagePayload") or {}
    msg = mp.get("message") or event.get("message") or {}
    text = (msg.get("text") or msg.get("argumentText") or event.get("text") or "").lower()
    return ("nowforever" in text or "ops bot" in text or "@now" in text)


# Bare read-only command keywords the bot understands. Typed on their own these
# must always do something real (for admins) or route to the brain / a helpful
# hint — NEVER a blank "Got it." ack. Early logs showed "report"/"reports" (and
# "alerts" for non-admins) dead-acking because they matched no handler here.
# "report"/"reports" are treated as synonyms for the ops summary/dashboard.
_SUMMARY_CMDS = {"summary", "dashboard", "what happened", "what happened today",
                 "status", "report", "reports", "overview", "recap"}
_ALERT_CMDS = {"alerts", "alert", "urgent", "urgents", "high priority"}
_TASK_CMDS = {"tasks", "open tasks", "task list", "list tasks", "open items"}
_READ_ONLY_CMDS = _SUMMARY_CMDS | _ALERT_CMDS | _TASK_CMDS

_BOT_MENTION_RE = re.compile(
    r"(?i)@?\s*now\s*(and|&)?\s*forever(\s*ops\s*bot)?|@?\s*ops\s*bot")


def _strip_bot_mention(text: str) -> str:
    """Drop a leading bot mention: 'NowForever Ops Bot tasks' -> 'tasks'."""
    return _BOT_MENTION_RE.sub("", text or "").strip()


def _command_word(text: str) -> str:
    """Normalize a message to its bare command form for keyword matching."""
    return _strip_bot_mention(text).lower().strip(" :,.!?")


def is_readonly_command(text: str) -> bool:
    """True if the whole message is one of the recognized read-only keywords."""
    return _command_word(text) in _READ_ONLY_CMDS


def build_reply(msg: dict, c, task_id: int | None, db_path: str = DB_PATH) -> str | None:
    """Return a reply for an EXACT command, or None for anything conversational
    (so the caller routes it to the AI brain). Commands must be the whole message
    — a sentence that merely contains 'task'/'summary' is not a command."""
    text = msg["message"] or ""
    # Strip a leading bot mention: "NowForever Ops Bot tasks" -> "tasks".
    norm = _strip_bot_mention(text)
    low = norm.lower().strip(" :,.!?")
    admin = is_admin(msg["sender"])

    # Explicit actions (must contain the verb + a task number).
    m = re.fullmatch(r"(?:please\s+)?close\s+(?:task\s+)?#?(\d+)\.?", low)
    if m:
        if not admin:
            return "⛔ Only the admin can close tasks."
        tid = int(m.group(1))
        res = task_action(db_path, tid, "close")
        return f"Closed task #{tid}." if res.get("ok") else f"Could not close #{tid}: {res.get('error')}"

    m = re.fullmatch(r"(?:please\s+)?assign\s+(?:task\s+)?#?(\d+)\s+(?:to\s+)?(.+)", norm.strip(), flags=re.I)
    if m:
        if not admin:
            return "⛔ Only the admin can assign tasks."
        tid, assignee = int(m.group(1)), m.group(2).strip()
        res = task_action(db_path, tid, "assign", assignee)
        return f"Assigned #{tid} to {assignee}." if res.get("ok") else f"Could not assign #{tid}: {res.get('error')}"

    # Quick read-only commands — only when the message IS the command.
    if low in _SUMMARY_CMDS:
        if not admin:
            return None  # let the AI answer non-admins instead of refusing
        d = dashboard(db_path)
        open_count = next((x["count"] for x in d["tasks"] if x["status"] == "open"), 0)
        high_count = next((x["count"] for x in d["priorities"] if x["priority"] == "high"), 0)
        lines = ["📊 Now & Forever Ops Summary", f"Messages: {d['totals'].get('messages', 0)}",
                 f"Open tasks: {open_count}", f"High priority: {high_count}", "", "Top active rooms:"]
        for r in d["top_rooms"][:5]:
            lines.append(f"• {r['room_name']}: {r['tasks']} tasks, {r['high']} high")
        return "\n".join(lines)

    if low in _ALERT_CMDS:
        if not admin:
            return None
        alerts = high_priority(db_path, 8)
        if not alerts:
            return "No high-priority alerts found."
        return "\n".join(["🚨 High Priority Alerts"] +
                         [f"• [{a['room_name']}] {(a.get('message') or '')[:160]}" for a in alerts])

    if low in _TASK_CMDS:
        if not admin:
            return None
        tasks = open_tasks(db_path, limit=10)
        if not tasks:
            return "No open tasks found."
        return "\n".join(["✅ Open Tasks"] +
                         [f"• #{t['id']} [{t['room_name']}] {t.get('task_title') or t.get('task_text')}" for t in tasks])

    # Everything else (incl. "show me…", "what's going on at 4?") → AI brain.
    return None


def default_ack(msg: dict, c, task_id: int | None) -> str:
    """Fallback acknowledgement used when the AI brain is unavailable."""
    if task_id:
        icon = "🚨" if c.priority == "high" else "📝"
        return f"{icon} Logged {c.priority} task #{task_id}\nSite/room: {msg['room_name']}\nCategory: {pick_primary_category(c.categories)}\nAssignee: {c.assigned_hint or 'unassigned'}"
    if c.priority == "high":
        return f"🚨 High-priority message detected in {msg['room_name']}. I logged it for review."
    # A bare recognized keyword (e.g. "report", "alerts") that reached here was
    # gated to non-admins or hit while the brain was offline — guide the user
    # instead of a blank "Got it." that looks like the command was ignored.
    if is_readonly_command(msg.get("message", "")):
        return ("I can show you: *summary* (ops overview), *alerts* (high-priority "
                "items), or *tasks* (open items). Some commands are admin-only.")
    return "Got it."


def is_direct_message(event: dict) -> bool:
    # Space can live at top level (classic) or under messagePayload (add-on).
    mp = event.get("messagePayload") or {}
    space = (
        event.get("space")
        or mp.get("space")
        or mp.get("message", {}).get("space")
        or event.get("message", {}).get("space")
        or {}
    )
    return (
        space.get("type") == "DM"
        or space.get("spaceType") == "DIRECT_MESSAGE"
        or space.get("singleUserBotDm") is True
    )


def handle_google_chat_event(event: dict, db_path: str = DB_PATH) -> dict:
    # Unwrap Workspace Add-on envelope
    if "chat" in event:
        event = {**event, **event["chat"]}
    # Add-on: MESSAGE = has messagePayload, ADDED_TO_SPACE = has addedToSpacePayload
    if event.get("messagePayload"):
        event_type = "MESSAGE"
    elif event.get("addedToSpacePayload"):
        event_type = "ADDED_TO_SPACE"
    else:
        event_type = event.get("type") or event.get("eventType") or "MESSAGE"
    if event_type == "ADDED_TO_SPACE":
        space = event.get("space", {})
        name = space.get("displayName") or space.get("name") or "this space"
        return google_chat_response(f"NowAndForeverBot is active in {name}. Send me: summary, alerts, tasks, close task #, assign task #, or show <room>.")
    if event_type == "REMOVED_FROM_SPACE":
        return google_chat_response("")

    # Always ingest/classify so tasks, dashboard, and alerts stay accurate.
    result = ingest_live_event(event, db_path)
    # Learn each admin's DM space the first time they message, so digests reach them.
    if is_direct_message(event) and is_admin(result.get("sender", "")):
        remember_admin_dm(result.get("sender", ""), result.get("space_id", ""))
    c_priority = result.get("priority")
    reply = result.get("reply") or "Got it. Try: summary, alerts, tasks, or show <room name>."

    # Decide whether we'll actually post a reply: always in DMs; in rooms only
    # when addressed (and reply-in-spaces enabled).
    will_reply = is_direct_message(event) or (REPLY_IN_SPACES and should_reply(event, c_priority))

    # Conversational AI: if no exact command matched, let the Claude brain answer.
    if will_reply and not result.get("command_matched") and brain.enabled():
        ai = brain.answer(result.get("text", ""), result.get("room_name"),
                          result.get("sender", "unknown"), is_admin(result.get("sender", "")),
                          space_id=result.get("space_id"), image_note=result.get("vision_summary", ""))
        if ai:
            reply = ai

    if will_reply:
        return google_chat_response(reply)
    return google_chat_response("")  # empty -> {} -> no visible message in the room
