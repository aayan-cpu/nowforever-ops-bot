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
import os
import ssl
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta

from app import chat_media, store

_ctx = ssl.create_default_context()
_API = "https://chat.googleapis.com/v1"

# The bot's own Chat user id — never ingest its own posts (broadcasts, digests,
# alert DMs), or they loop back in as "alerts". Also matched by sender.type == BOT.
BOT_USER_ID = os.getenv("OPS_BOT_USER_ID", "").strip()
# Prefixes/phrases the bot uses in its own output — used to clean up self-echoes
# that were ingested before the BOT filter existed.
_BOT_PREFIXES = ("📢", "📊", "⏰", "🚨", "📋", "🏪", "📘", "🌅", "✅")
_BOT_PHRASES = ("Ops Bot is now LIVE", "is now LIVE", "testing is over", "Ops Briefing",
                "High Priority Alerts", "Daily Summary", "Escalation —", "Stations missing",
                "AI assistant here to help")


def _is_bot_message(sender_dict: dict) -> bool:
    s = sender_dict or {}
    return s.get("type") == "BOT" or (BOT_USER_ID and s.get("name") == BOT_USER_ID)


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


def to_event(space: str, m: dict, display_name: str | None = None) -> dict:
    """Map a Chat API Message resource to the webhook event shape ingest expects.
    `display_name` is the room's friendly name so room_name resolves to e.g.
    '14 Synott' instead of the raw space id."""
    sender = m.get("sender") or {}
    return {
        "type": "MESSAGE",
        "space": {"name": space, "displayName": display_name or None},
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

    backfilled = 0
    for space, name in spaces:
        msgs = list_recent_messages(space, read_tok, per_room)
        new_here = 0
        # oldest-first so tasks/threads land in chronological order
        for m in reversed(msgs):
            scanned += 1
            if _is_bot_message(m.get("sender")):
                continue  # never ingest the bot's own posts (would loop back as alerts)
            found = store.find("messages", "data_id", m.get("name"), limit=1)
            if found:
                # Backfill OCR flag for image messages stored before refs were captured.
                doc = found[0]
                if (not doc.get("needs_ocr") and (doc.get("vision") in (None, "", "[]"))
                        and (m.get("attachment") or m.get("attachments"))):
                    refs = chat_media.image_attachments(m)
                    if refs:
                        try:
                            store.patch("messages", doc["id"],
                                        {"needs_ocr": True, "image_refs": json.dumps(refs)})
                            backfilled += 1
                        except Exception:
                            pass
                continue
            try:
                ingest_live_event(to_event(space, m, name), analyze=False)  # text-only: fast + cheap
                ingested += 1
                new_here += 1
                if new_here >= max_new_per_room:
                    break
            except Exception as e:
                errors += 1
                print(f"[sync] ingest err {m.get('name')}: {e}", flush=True)
    result = {"spaces": len(spaces), "scanned": scanned, "ingested": ingested,
              "ocr_backfilled": backfilled, "errors": errors}
    print(f"[sync] {result}", flush=True)
    return result


def ocr_pass(batch: int = 6) -> dict:
    """Throttled image OCR: read a few day-report/BOL photos the text-only sync
    skipped. Reuses analyze_images (download + AI + store day_reports/fuel_events +
    cash/vendor reconciliation + alerts), then clears the needs_ocr flag. Small batch
    per run keeps it cheap; runs on a schedule until the backlog drains."""
    from app.chat_live import analyze_images

    pending = [m for m in store.list_all("messages") if m.get("needs_ocr")]
    pending.sort(key=lambda m: m.get("seq") or 0, reverse=True)  # newest first
    processed = flagged = errors = 0
    for m in pending[:batch]:
        try:
            refs = json.loads(m.get("image_refs") or "[]")
        except Exception:
            refs = []
        synth = {"room_name": m.get("room_name"), "message": m.get("message") or "",
                 "data_id": m.get("data_id"), "image_attachments": refs}
        try:
            vis = analyze_images(synth)
            patch = {"needs_ocr": False, "image_refs": "[]",
                     "vision_summary": vis.get("summary") or "",
                     "vision": json.dumps(vis.get("results") or [])}
            if vis.get("needs_review"):
                patch.update(priority="high", is_task=True)
                flagged += 1
            store.patch("messages", m["id"], patch)
            processed += 1
        except Exception as e:
            errors += 1
            print(f"[ocr] {m.get('id')}: {e}", flush=True)
            try:
                store.patch("messages", m["id"], {"needs_ocr": False})  # don't retry-loop forever
            except Exception:
                pass
    result = {"pending": len(pending), "processed": processed,
              "flagged": flagged, "errors": errors}
    print(f"[ocr] {result}", flush=True)
    return result


def backfill_dm_flag() -> dict:
    """Tag existing messages that are DMs (is_dm=True) by matching their room_id
    against the bot's actual DM spaces from the Chat API — fixes the /dms view
    missing older DMs that were ingested before DM detection existed."""
    tok = chat_media.get_chat_token()
    dm_spaces = set()
    page = ""
    while tok:
        url = _API + '/spaces?pageSize=100&filter=space_type%20%3D%20%22DIRECT_MESSAGE%22'
        if page:
            url += "&pageToken=" + page
        try:
            data = _api_get(url, tok)
        except Exception as e:
            print(f"[dm-backfill] list: {e}", flush=True)
            break
        for s in data.get("spaces", []):
            if s.get("name"):
                dm_spaces.add(s["name"])
        page = data.get("nextPageToken", "")
        if not page:
            break
    if not dm_spaces:
        return {"dm_spaces": 0, "tagged": 0, "note": "no DM spaces from Chat API"}
    tagged = 0
    for m in store.list_all("messages"):
        if m.get("is_dm"):
            continue
        if (m.get("room_id") or "") in dm_spaces:
            try:
                store.patch("messages", m["id"], {"is_dm": True})
                tagged += 1
            except Exception:
                pass
    print(f"[dm-backfill] {len(dm_spaces)} DM spaces, tagged {tagged}", flush=True)
    return {"dm_spaces": len(dm_spaces), "tagged": tagged}


def clear_day_report_alerts() -> dict:
    """One-time: clear day-report REVIEW/flag alerts (the noisy 'needs review' /
    flagged-field items) — closing the tasks and pulling their messages out of the
    alerts list. Does NOT touch real issues (pumps/gas/etc.) or the separate
    'store didn't send a report at all' detection. Per owner: only a totally-missing
    report should alert, not field-level review flags."""
    review_titles = ("Attachment/report needs review",)
    closed = downgraded = 0
    for t in store.list_all("tasks"):
        if (t.get("status") or "open") != "open":
            continue
        title = (t.get("task_title") or "")
        if title in review_titles or title.startswith("REVIEW:"):
            try:
                store.patch("tasks", t["id"], {"status": "closed"})
                closed += 1
            except Exception:
                pass
            mid = t.get("message_id")
            if mid:
                try:
                    store.patch("messages", mid,
                                {"priority": "normal", "is_task": False, "is_duplicate": True})
                    downgraded += 1
                except Exception:
                    pass
    print(f"[clear-dr] closed {closed} review tasks, downgraded {downgraded} msgs", flush=True)
    return {"review_tasks_closed": closed, "messages_downgraded": downgraded}


def clear_dm_tasks() -> dict:
    """Close issues/alerts that came from DM messages (the owner's own DM commands
    shouldn't become store issues). Downgrades the DM messages and closes any open
    task that originated from one."""
    dm_ids = set()
    downgraded = 0
    for m in store.list_all("messages"):
        if m.get("is_dm"):
            dm_ids.add(m.get("id"))
            if m.get("priority") == "high" or m.get("is_task"):
                try:
                    store.patch("messages", m["id"], {"priority": "normal", "is_task": False})
                    downgraded += 1
                except Exception:
                    pass
    closed = 0
    for t in store.list_all("tasks"):
        if (t.get("status") or "open") == "open" and t.get("message_id") in dm_ids:
            try:
                store.patch("tasks", t["id"], {"status": "closed"})
                closed += 1
            except Exception:
                pass
    print(f"[clear-dm] downgraded {downgraded} msgs, closed {closed} tasks", flush=True)
    return {"messages_downgraded": downgraded, "dm_tasks_closed": closed}


def backfill_send_times() -> dict:
    """Repair the 'first reported' time. Most imported messages have an empty
    sent_at, so displays fell back to created_at (the bot's LOGGING time) and made
    old issues look like they happened today. Set sent_at from the message's real
    timestamp_raw, and copy that onto each task from its source message."""
    # Build message_id -> real send time (read-only). timestamp_raw is the message's
    # own time; created_at is the logging time (last resort).
    msg_ts: dict = {}
    for m in store.list_all("messages"):
        msg_ts[m.get("id")] = m.get("sent_at") or m.get("timestamp_raw") or m.get("created_at") or ""

    # TASKS FIRST — they have no timestamp_raw, so lookup_site can't floor them until
    # sent_at is repaired. This is the part that fixes "first reported"; do it before
    # the slow message pass so a request timeout can't starve it.
    fixed_tasks = 0
    for t in store.list_all("tasks"):
        if t.get("sent_at"):
            continue
        src = msg_ts.get(t.get("message_id"))
        if src:
            try:
                store.patch("tasks", t["id"], {"sent_at": store.normalize_ts(src)})
                fixed_tasks += 1
            except Exception as e:
                print(f"[backfill-ts] task {t.get('id')}: {e}", flush=True)

    # Messages second — cosmetic (high_priority already floors on timestamp_raw).
    # Capped so the request returns; re-run to continue (idempotent, skips fixed).
    fixed_msgs = 0
    for m in store.list_all("messages"):
        if m.get("sent_at"):
            continue
        real = m.get("timestamp_raw") or m.get("created_at") or ""
        if real:
            try:
                store.patch("messages", m["id"], {"sent_at": store.normalize_ts(real)})
                fixed_msgs += 1
            except Exception as e:
                print(f"[backfill-ts] msg {m.get('id')}: {e}", flush=True)
            if fixed_msgs >= 4000:  # stay under the request timeout; re-run for the rest
                break
    print(f"[backfill-ts] fixed {fixed_tasks} tasks, {fixed_msgs} msgs", flush=True)
    return {"tasks_fixed": fixed_tasks, "messages_fixed": fixed_msgs}


def dedupe_tasks(stale_days: int = 14) -> dict:
    """Collapse the historical task backlog into one live issue per (store, category).
    The bulk sync created a task for every action-worthy message, so the same problem
    piled up into thousands of open tasks. This keeps the most-recent open task per
    (store, category), closes the older duplicates as 'merged', and closes survivors
    that have gone stale (no activity in `stale_days`, not high priority)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=stale_days)).isoformat()
    open_tasks = [t for t in store.list_all("tasks") if (t.get("status") or "open") == "open"]
    groups: dict[tuple, list] = {}
    for t in open_tasks:
        groups.setdefault((t.get("room_name") or "", t.get("category") or ""), []).append(t)

    merged = stale = 0
    for key, ts in groups.items():
        ts.sort(key=lambda x: (x.get("updated_at") or x.get("created_at") or ""), reverse=True)
        survivor, dupes = ts[0], ts[1:]
        for t in dupes:
            try:
                store.patch("tasks", t["id"], {"status": "closed", "closed_reason": "merged-duplicate"})
                merged += 1
            except Exception as e:
                print(f"[dedupe-tasks] merge {t.get('id')}: {e}", flush=True)
        # Close the survivor too if it's old and not high priority (resolved-by-silence).
        last = survivor.get("updated_at") or survivor.get("created_at") or ""
        if last and last < cutoff and survivor.get("priority") != "high":
            try:
                store.patch("tasks", survivor["id"], {"status": "closed", "closed_reason": "auto-stale"})
                stale += 1
            except Exception as e:
                print(f"[dedupe-tasks] stale {survivor.get('id')}: {e}", flush=True)
    remaining = len(open_tasks) - merged - stale
    print(f"[dedupe-tasks] merged {merged} dups, closed {stale} stale, {remaining} open remain", flush=True)
    return {"merged": merged, "stale_closed": stale, "open_remaining": remaining}


def purge_bot_echo() -> dict:
    """Downgrade the bot's OWN posts (broadcasts/digests/alerts) that the sync
    re-ingested before the BOT filter existed, so they stop showing as alerts/tasks.
    Matches by bot user id and by the bot's output prefixes/phrases."""
    downgraded = 0
    bot_msg_ids: set = set()
    for m in store.list_all("messages"):
        if m.get("is_duplicate"):
            # already-downgraded bot echoes still count for closing their tasks
            sender0 = m.get("sender") or ""
            txt0 = (m.get("message") or "").strip()
            if (BOT_USER_ID and sender0 == BOT_USER_ID) or txt0.startswith(_BOT_PREFIXES) \
                    or any(p in txt0 for p in _BOT_PHRASES):
                bot_msg_ids.add(m.get("id"))
            continue
        sender = m.get("sender") or ""
        txt = (m.get("message") or "").strip()
        is_bot = (BOT_USER_ID and sender == BOT_USER_ID) \
            or txt.startswith(_BOT_PREFIXES) \
            or any(p in txt for p in _BOT_PHRASES)
        if is_bot:
            bot_msg_ids.add(m.get("id"))
            try:
                store.patch("messages", m["id"],
                            {"is_duplicate": True, "priority": "normal", "is_task": False})
                downgraded += 1
            except Exception as e:
                print(f"[purge] {m.get('id')}: {e}", flush=True)
    # Close any OPEN tasks spawned from the bot's own posts (e.g. the 'now LIVE'
    # announcement that showed up as a high-priority issue). Match by source
    # message id, and by the bot's own phrases in the task text.
    closed = 0
    for t in store.list_all("tasks"):
        if (t.get("status") or "open") != "open":
            continue
        txt = f"{t.get('task_title') or ''} {t.get('task_text') or ''}".strip()
        if t.get("message_id") in bot_msg_ids or txt.startswith(_BOT_PREFIXES) \
                or any(p in txt for p in _BOT_PHRASES):
            try:
                store.patch("tasks", t["id"], {"status": "closed", "closed_reason": "bot-echo"})
                closed += 1
            except Exception as e:
                print(f"[purge] task {t.get('id')}: {e}", flush=True)
    print(f"[purge] downgraded {downgraded} bot-echo messages, closed {closed} bot-echo tasks", flush=True)
    return {"downgraded": downgraded, "tasks_closed": closed}


def remap_space_ids() -> dict:
    """Maintenance: messages synced before display names were captured got
    room_name = the raw 'spaces/...' id. Re-label them to the room's friendly name."""
    name_by_id = {sid: nm for sid, nm in chat_media.list_bot_spaces()
                  if nm and not nm.startswith("spaces/")}
    fixed = 0
    for m in store.list_all("messages"):
        rn = m.get("room_name") or ""
        if rn.startswith("spaces/") and rn in name_by_id:
            try:
                store.patch("messages", m["id"], {"room_name": name_by_id[rn]})
                fixed += 1
            except Exception as e:
                print(f"[remap] {m.get('id')}: {e}", flush=True)
    print(f"[remap] fixed {fixed} of {len(name_by_id)} rooms", flush=True)
    return {"fixed": fixed, "named_rooms": len(name_by_id)}
