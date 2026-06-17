"""Message sync — read what the webhook never delivers.

Google Chat only pushes a message to a bot when it is @mentioned, so the bot
never sees a room's day-to-day traffic (day reports, deposits, etc.). This module
PULLS recent messages from every room via the Chat API and feeds anything new
through the normal ingest path, so every store is actually tracked.

- Spaces come from the app token (rooms the bot is a member of).
- Messages are read with the chat.messages.readonly token (impersonating an admin
  who is in the rooms) — the same read scope used for attachment downloads.
- ingest_live_event() dedupes by message id, so re-running is safe (no dupes).
"""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request

from app import chat_media, store

_ctx = ssl.create_default_context()
_API = "https://chat.googleapis.com/v1"


def _api_get(url: str, token: str) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    return json.loads(urllib.request.urlopen(req, context=_ctx, timeout=20).read())


def list_recent_messages(space: str, token: str, n: int = 25) -> list[dict]:
    """Most recent `n` messages in a space (newest first), read as the admin."""
    url = (f"{_API}/{space}/messages?pageSize={int(n)}"
           "&orderBy=createTime%20desc")
    try:
        return _api_get(url, token).get("messages", []) or []
    except urllib.error.HTTPError as e:
        print(f"[sync] list {space}: {e.code} {e.read().decode()[:150]}", flush=True)
        return []
    except Exception as e:
        print(f"[sync] list {space}: {e}", flush=True)
        return []


def to_event(space: str, m: dict) -> dict:
    """Map a Chat API Message resource to the webhook event shape ingest expects."""
    sender = m.get("sender") or {}
    return {
        "type": "MESSAGE",
        "space": {"name": space},
        "message": {
            "name": m.get("name"),
            "text": m.get("text") or m.get("argumentText") or m.get("formattedText") or "",
            "createTime": m.get("createTime"),
            "sender": sender,
            "attachment": m.get("attachment") or m.get("attachments") or [],
        },
        "user": sender,
    }


def _already_have(message_name: str) -> bool:
    if not message_name:
        return False
    try:
        return bool(store.find("messages", "data_id", message_name, limit=1))
    except Exception:
        return False


def sync_once(per_room: int = 25, max_new_per_room: int = 40) -> dict:
    """Pull recent messages from every bot room and ingest anything new.
    Returns {spaces, scanned, ingested, errors}. Safe to run on a schedule."""
    from app.chat_live import ingest_live_event  # late import (heavy deps)

    spaces = chat_media.list_bot_spaces()          # app token: rooms the bot is in
    read_tok = chat_media.get_download_token()      # read scope (as admin)
    scanned = ingested = errors = 0
    if not spaces or not read_tok:
        return {"spaces": len(spaces), "scanned": 0, "ingested": 0,
                "errors": 0, "note": "no spaces or no read token"}

    for space, _name in spaces:
        msgs = list_recent_messages(space, read_tok, per_room)
        new_here = 0
        # oldest-first so tasks/threads land in chronological order
        for m in reversed(msgs):
            scanned += 1
            if _already_have(m.get("name")):
                continue
            try:
                ingest_live_event(to_event(space, m), analyze=False)  # text-only: fast + cheap
                ingested += 1
                new_here += 1
                if new_here >= max_new_per_room:
                    break
            except Exception as e:
                errors += 1
                print(f"[sync] ingest err {m.get('name')}: {e}", flush=True)
    result = {"spaces": len(spaces), "scanned": scanned,
              "ingested": ingested, "errors": errors}
    print(f"[sync] {result}", flush=True)
    return result
