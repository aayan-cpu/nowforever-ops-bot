"""Google Chat live connection stub for v2.

This is intentionally not wired to your Workspace credentials yet. It defines the
shape of the live event path so v3 can plug into Google Chat without rewriting
the parser/classifier.

Live flow:
  Google Chat event JSON -> handle_chat_event() -> classify -> store -> decide reply
"""
from __future__ import annotations

from dataclasses import dataclass
from app.classifier import classify_message

@dataclass
class ChatDecision:
    should_reply: bool
    reply_text: str
    priority: str
    categories: list[str]
    is_task: bool


def handle_chat_event(event: dict) -> ChatDecision:
    message = event.get("message", {}) or {}
    text = message.get("text", "") or message.get("argumentText", "") or ""
    room_name = ((event.get("space") or {}).get("displayName") or "Unknown space")
    attachment_count = len(message.get("attachment", []) or [])
    c = classify_message(text, attachment_count, room_name)

    if c.priority == "high":
        reply = f"🚨 High priority noted. I created a task for: {c.task_title}"
        return ChatDecision(True, reply, c.priority, c.categories, c.is_task)
    if c.is_task:
        reply = f"✅ Task captured: {c.task_title}"
        return ChatDecision(True, reply, c.priority, c.categories, c.is_task)
    return ChatDecision(False, "", c.priority, c.categories, c.is_task)
