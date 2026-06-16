"""Conversational AI brain (Claude) for the ops bot.

When a user addresses the bot in plain English, we pull a compact snapshot of
live ops data from Firestore and let Claude answer naturally — turning the bot
from a fixed-command machine into a real assistant.

Dependency-free: calls the Claude Messages REST API directly (the `anthropic`
SDK's deps don't build on the dev machine's Python 3.14). Gated on
ANTHROPIC_API_KEY — if unset, enabled() is False and callers fall back to the
deterministic keyword replies.
"""
from __future__ import annotations

import json
import os
import ssl
import urllib.request
import urllib.error

from app import reports, store

API_KEY_ENV = "ANTHROPIC_API_KEY"
MODEL = os.getenv("OPS_BRAIN_MODEL", "claude-opus-4-8")
ENDPOINT = "https://api.anthropic.com/v1/messages"
_ctx = ssl.create_default_context()

# Stable persona — sent as a cacheable system block to keep cost down.
PERSONA = (
    "You are the NowAndForever Ops Bot — a sharp, trusted operations right-hand for the "
    "owner and managers of the Now & Forever / Hawar & Sons chain of 20+ Texas gas stations. "
    "You know fuel deliveries (BOL vs Veeder-Root), equipment, daily reports, and per-store "
    "activity cold.\n\n"
    "TALK LIKE A SMART HUMAN COLLEAGUE OVER TEXT — never like a database or a robot.\n"
    "- Be natural and conversational. Use real sentences. Do NOT dump templated, "
    "bracketed lists like '#2224 [24 Galveston]'. That reads as robotic.\n"
    "- IDENTIFY ISSUES BY MEANING, NOT NUMBERS. Refer to each issue by its store, type, and "
    "a short description — 'the gas delivery at Galveston', 'Windchase's power outage', 'the "
    "AC at 24'. Do NOT show task ID numbers at all unless the user explicitly asks for an ID. "
    "Internally the issues have numbers (you need them for tools), but keep them out of what "
    "you say.\n"
    "- ORGANIZE BY CATEGORY. Group related issues by type (Fuel/deliveries, Equipment, Power, "
    "Reports, Cash/deposits, Compliance) and by store, most urgent first. Think in categories, "
    "not a flat numbered list.\n"
    "- When the user refers to an issue in plain language ('close the AC at Galveston', "
    "'assign the printer problem at 16'), use find_tasks to resolve it to the real task, do "
    "the action, and confirm in plain language ('Done — closed the AC issue at Galveston'). "
    "Never make the user type a number.\n"
    "- Only use a bullet list when you're genuinely listing several things and it helps; "
    "otherwise write in flowing sentences. Keep it tight — this is Google Chat.\n"
    "- No markdown headers (#), tables, or code blocks — Chat doesn't render them.\n"
    "- Be genuinely smart and contextual: use the conversation history and the person's "
    "saved preferences, infer what they really want, connect related issues into the bigger "
    "picture (e.g. 'the outage is what's blocking the pumps and SSCS'), and suggest the next "
    "step. Prioritize; don't just enumerate.\n"
    "- Answer from the OPS DATA and tool results. If you don't have something, say so briefly "
    "and offer to look it up (you have a tool to pull any store). Never invent numbers, "
    "gallons, or store names.\n"
    "- You can act: close or assign tasks directly when asked — just do it and confirm "
    "naturally."
)


def enabled() -> bool:
    return bool(os.getenv(API_KEY_ENV))


def _snapshot(room_name: str | None) -> str:
    """Compact live ops context for the model. Kept small to limit tokens."""
    lines: list[str] = []
    try:
        tasks = reports.open_tasks(limit=20)
        lines.append(f"OPEN TASKS ({len(tasks)} shown):")
        for t in tasks:
            lines.append(f"• #{t.get('id')} [{t.get('room_name')}] "
                         f"{(t.get('task_title') or t.get('task_text') or '')[:120]} "
                         f"(priority={t.get('priority')}, status={t.get('status')})")
    except Exception:
        lines.append("(open tasks unavailable)")
    try:
        alerts = reports.high_priority(limit=8)
        if alerts:
            lines.append("\nHIGH-PRIORITY ALERTS:")
            for a in alerts:
                lines.append(f"• [{a.get('room_name')}] {(a.get('message') or '')[:140]}")
    except Exception:
        pass
    if room_name:
        try:
            rs = reports.room_summary(None, room_name)
            s = rs.get("stats")
            if s:
                lines.append(f"\nROOM '{s['room_name']}': {s['messages']} msgs, "
                             f"{s['tasks']} task-msgs, {s['high']} high-priority.")
            for m in rs.get("recent", [])[:10]:
                lines.append(f"  - {m.get('sender')}: {(m.get('message') or '')[:120]}")
        except Exception:
            pass
    return "\n".join(lines) if lines else "(no ops data available)"


def _pref_id(email: str) -> str:
    return (email or "anon").lower().replace("/", "_")[:200]


def _load_prefs(email: str) -> list[str]:
    try:
        d = store.get("preferences", _pref_id(email))
        if d and d.get("notes"):
            return json.loads(d["notes"])
    except Exception:
        pass
    return []


def _save_pref(email: str, note: str) -> str:
    try:
        cid = _pref_id(email)
        notes = _load_prefs(email)
        notes.append(note.strip())
        notes = notes[-25:]
        payload = {"email": (email or "").lower(), "notes": json.dumps(notes)}
        if store.get("preferences", cid):
            store.patch("preferences", cid, payload)
        else:
            store.create("preferences", payload, doc_id=cid)
        return "Saved. I'll keep that in mind for you going forward."
    except Exception as e:
        return f"Couldn't save that: {e}"


# Read-only / self-service tools — offered to everyone. The bot can answer about
# ANY store on demand, and each user can teach it their own preferences.
_READ_TOOLS = [
    {
        "name": "remember_preference",
        "description": "Save a lasting preference for THIS user about how the bot should "
                       "help them — e.g. what to focus on, which stores they care about, "
                       "what to include in their daily summary, formatting, alert topics. "
                       "Call this whenever the user says to always/from now on do something "
                       "for them.",
        "input_schema": {
            "type": "object",
            "properties": {"preference": {"type": "string", "description": "The preference to remember, in plain language."}},
            "required": ["preference"],
        },
    },
    {
        "name": "lookup_site",
        "description": "Look up current open tasks, counts, and recent activity for a "
                       "specific store/site by name or number (e.g. '11', 'Windchase', "
                       "'4 Channelview'). Use this whenever the user asks about a particular store.",
        "input_schema": {
            "type": "object",
            "properties": {"site": {"type": "string", "description": "Store name or number"}},
            "required": ["site"],
        },
    },
    {
        "name": "find_tasks",
        "description": "Search OPEN tasks by keywords (store, issue type, words from the "
                       "user's message) to find the specific task the user means in plain "
                       "language. Use this to resolve references like 'the AC at Galveston' "
                       "or 'the printer issue at 16' into the actual task BEFORE closing or "
                       "assigning it — so the user never has to type an ID number.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Keywords: store + issue, e.g. 'galveston ac' or 'printer 16'"}},
            "required": ["query"],
        },
    },
]

# Action tools — only offered to admins, since they change state.
_ACTION_TOOLS = [
    {
        "name": "close_task",
        "description": "Close/resolve an open task by its numeric id.",
        "input_schema": {
            "type": "object",
            "properties": {"task_id": {"type": "integer", "description": "The task number, e.g. 868"}},
            "required": ["task_id"],
        },
    },
    {
        "name": "assign_task",
        "description": "Assign an open task to a person by task id.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer"},
                "assignee": {"type": "string", "description": "Who to assign it to, e.g. 'Moin' or '@Admin 4'"},
            },
            "required": ["task_id", "assignee"],
        },
    },
]


def _run_tool(name: str, args: dict, sender: str = "") -> str:
    from app import reports
    try:
        if name == "remember_preference":
            return _save_pref(sender, str(args.get("preference", "")))
        if name == "find_tasks":
            terms = str(args.get("query", "")).lower().split()
            hits = []
            for t in reports.open_tasks(limit=400):
                hay = f"{t.get('room_name','')} {t.get('task_title','')} {t.get('task_text','')} {t.get('category','')}".lower()
                if all(term in hay for term in terms):
                    hits.append(t)
            if not hits:
                return "No matching open tasks."
            return "\n".join(
                f"{t.get('room_name')} | {t.get('category')} | "
                f"{t.get('task_title') or t.get('task_text')} (id {t['id']}, {t.get('priority')})"
                for t in hits[:12])
        if name == "lookup_site":
            rs = reports.room_summary(None, str(args.get("site", "")))
            s = rs.get("stats")
            if not s:
                return f"No data found for site '{args.get('site')}'."
            out = [f"{s['room_name']}: {s['messages']} msgs, {s['tasks']} task-msgs, {s['high']} high-priority."]
            for t in rs.get("open_tasks", [])[:12]:
                out.append(f"#{t['id']} ({t.get('priority')}) {t.get('task_title') or t.get('task_text')}")
            return "\n".join(out)
        if name == "close_task":
            r = reports.task_action(None, int(args["task_id"]), "close")
            return f"Closed task #{args['task_id']}." if r.get("ok") else f"Failed: {r.get('error')}"
        if name == "assign_task":
            r = reports.task_action(None, int(args["task_id"]), "assign", str(args.get("assignee", "")))
            return (f"Assigned task #{args['task_id']} to {args.get('assignee')}."
                    if r.get("ok") else f"Failed: {r.get('error')}")
    except Exception as e:
        return f"Tool error: {e}"
    return f"Unknown tool {name}"


def _call_claude(messages: list, tools: list | None) -> dict:
    body = {
        "model": MODEL,
        "max_tokens": 1200,
        # Adaptive thinking: Opus decides when to reason (smarter on hard questions,
        # still fast on simple ones).
        "thinking": {"type": "adaptive"},
        "system": [{"type": "text", "text": PERSONA, "cache_control": {"type": "ephemeral"}}],
        "messages": messages,
    }
    if tools:
        body["tools"] = tools
    req = urllib.request.Request(ENDPOINT, data=json.dumps(body).encode(), headers={
        "x-api-key": os.environ[API_KEY_ENV],
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    })
    return json.loads(urllib.request.urlopen(req, context=_ctx, timeout=45).read())


def _conv_id(space_id: str) -> str:
    return (space_id or "dm").replace("/", "_")[:1400]


def _load_turns(space_id: str | None) -> list[dict]:
    if not space_id:
        return []
    try:
        d = store.get("conversations", _conv_id(space_id))
        if d and d.get("turns"):
            return json.loads(d["turns"])
    except Exception:
        pass
    return []


def _save_turn(space_id: str | None, user_text: str, assistant_text: str) -> None:
    if not space_id:
        return
    try:
        cid = _conv_id(space_id)
        turns = _load_turns(space_id)
        turns.append({"role": "user", "content": user_text[:2000]})
        turns.append({"role": "assistant", "content": assistant_text[:2000]})
        turns = turns[-6:]  # keep last 3 exchanges
        payload = {"turns": json.dumps(turns)}
        if store.get("conversations", cid):
            store.patch("conversations", cid, payload)
        else:
            store.create("conversations", payload, doc_id=cid)
    except Exception as e:
        print(f"[brain] save turns: {e}", flush=True)


def answer(user_msg: str, room_name: str | None, sender: str, is_admin: bool,
           space_id: str | None = None) -> str | None:
    """Return Claude's reply, executing close/assign tools if it requests them
    (admins only), with short-term memory of the last few turns in this space.
    Returns None on failure so the caller can fall back."""
    if not enabled() or not (user_msg or "").strip():
        return None
    snapshot = _snapshot(room_name)
    prefs = _load_prefs(sender)
    prefs_block = ("\nThis user's saved preferences (honor them):\n" +
                   "\n".join(f"- {p}" for p in prefs) + "\n") if prefs else ""
    user_block = (
        f"OPS DATA (current):\n{snapshot}\n{prefs_block}\n"
        f"---\nUser ({sender}{', admin' if is_admin else ''}) in "
        f"room '{room_name or 'DM'}' says:\n{user_msg}"
    )
    # Prior turns give multi-turn continuity ("what about site 11?").
    messages = _load_turns(space_id) + [{"role": "user", "content": user_block}]
    # Everyone gets read tools; only admins can mutate tasks.
    tools = _READ_TOOLS + (_ACTION_TOOLS if is_admin else [])
    try:
        for _ in range(4):  # tool-use loop
            resp = _call_claude(messages, tools)
            if resp.get("stop_reason") == "tool_use":
                messages.append({"role": "assistant", "content": resp["content"]})
                results = []
                for block in resp["content"]:
                    if block.get("type") == "tool_use":
                        out = _run_tool(block["name"], block.get("input", {}), sender)
                        results.append({"type": "tool_result", "tool_use_id": block["id"], "content": out})
                messages.append({"role": "user", "content": results})
                continue
            text = "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text").strip()
            if text:
                _save_turn(space_id, user_msg, text)
            return text or None
        return None
    except urllib.error.HTTPError as e:
        print(f"[brain] {e.code}: {e.read().decode()[:200]}", flush=True)
        return None
    except Exception as e:
        print(f"[brain] error: {e}", flush=True)
        return None
