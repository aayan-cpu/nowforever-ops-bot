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

from app import reports

API_KEY_ENV = "ANTHROPIC_API_KEY"
MODEL = os.getenv("OPS_BRAIN_MODEL", "claude-opus-4-8")
ENDPOINT = "https://api.anthropic.com/v1/messages"
_ctx = ssl.create_default_context()

# Stable persona — sent as a cacheable system block to keep cost down.
PERSONA = (
    "You are the NowAndForever Ops Bot, an operations assistant for the Now & Forever / "
    "Hawar & Sons chain of 20+ Texas gas stations. You help managers and the owner stay on "
    "top of operations: open tasks, urgent issues, fuel deliveries (BOL vs Veeder-Root), "
    "equipment problems, daily reports, and per-store activity.\n\n"
    "You are talking inside Google Chat, so keep replies short, concrete, and skimmable — a "
    "few lines, use simple bullets with '•' if listing. No markdown headers or tables. "
    "Answer only from the OPS DATA provided in the user's message; if the data doesn't cover "
    "the question, say so plainly and suggest what to check. Never invent task numbers, "
    "gallon figures, or store names. If the user wants to close or assign a task, tell them "
    "to use 'close task <id>' or 'assign task <id> <name>'."
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


# Action tools the brain can call — only offered to admins, since they change state.
_TOOLS = [
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


def _run_tool(name: str, args: dict) -> str:
    from app import reports
    try:
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
        "max_tokens": 800,
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


def answer(user_msg: str, room_name: str | None, sender: str, is_admin: bool) -> str | None:
    """Return Claude's reply, executing close/assign tools if it requests them
    (admins only). Returns None on failure so the caller can fall back."""
    if not enabled() or not (user_msg or "").strip():
        return None
    snapshot = _snapshot(room_name)
    user_block = (
        f"OPS DATA (current):\n{snapshot}\n\n"
        f"---\nUser ({sender}{', admin' if is_admin else ''}) in "
        f"room '{room_name or 'DM'}' says:\n{user_msg}"
    )
    messages = [{"role": "user", "content": user_block}]
    tools = _TOOLS if is_admin else None  # only admins can mutate tasks
    try:
        for _ in range(4):  # tool-use loop
            resp = _call_claude(messages, tools)
            if resp.get("stop_reason") == "tool_use":
                messages.append({"role": "assistant", "content": resp["content"]})
                results = []
                for block in resp["content"]:
                    if block.get("type") == "tool_use":
                        out = _run_tool(block["name"], block.get("input", {}))
                        results.append({"type": "tool_result", "tool_use_id": block["id"], "content": out})
                messages.append({"role": "user", "content": results})
                continue
            text = "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")
            return text.strip() or None
        return None
    except urllib.error.HTTPError as e:
        print(f"[brain] {e.code}: {e.read().decode()[:200]}", flush=True)
        return None
    except Exception as e:
        print(f"[brain] error: {e}", flush=True)
        return None
