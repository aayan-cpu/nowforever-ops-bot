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
import socket
import ssl
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta


def now_central() -> str:
    """Current time in Texas (US Central), DST-aware, dependency-free."""
    utc = datetime.now(timezone.utc)
    y = utc.year

    def nth_sunday(month: int, n: int) -> int:
        first = datetime(y, month, 1, tzinfo=timezone.utc)
        return 1 + ((6 - first.weekday()) % 7) + (n - 1) * 7

    dst_start = datetime(y, 3, nth_sunday(3, 2), 8, tzinfo=timezone.utc)   # 2am CST -> 08:00 UTC
    dst_end = datetime(y, 11, nth_sunday(11, 1), 7, tzinfo=timezone.utc)   # 2am CDT -> 07:00 UTC
    cdt = dst_start <= utc < dst_end
    local = utc + timedelta(hours=(-5 if cdt else -6))
    return local.strftime("%A, %B %-d, %Y, %-I:%M %p") + (" CDT" if cdt else " CST")

from app import reports, store

API_KEY_ENV = "ANTHROPIC_API_KEY"
MODEL = os.getenv("OPS_BRAIN_MODEL", "claude-opus-4-8")
ENDPOINT = "https://api.anthropic.com/v1/messages"
_ctx = ssl.create_default_context()

# Resilience for the Claude REST call: a transient API hiccup (rate limit,
# overloaded, gateway, network blip, timeout) shouldn't silently drop a user's
# reply. Retry those with exponential backoff; never retry a real client error
# (400/401/403/404) since it won't fix itself. All tunable via env.
BRAIN_TIMEOUT = float(os.getenv("OPS_BRAIN_TIMEOUT", "45"))
BRAIN_MAX_ATTEMPTS = max(1, int(os.getenv("OPS_BRAIN_MAX_ATTEMPTS", "3")))
BRAIN_BACKOFF_BASE = float(os.getenv("OPS_BRAIN_BACKOFF_BASE", "1.0"))
BRAIN_BACKOFF_MAX = float(os.getenv("OPS_BRAIN_BACKOFF_MAX", "30"))
_RETRY_STATUS = {429, 500, 502, 503, 504, 529}
_sleep = time.sleep  # indirection so tests don't actually wait

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
    "- GROUNDING IS ABSOLUTE. State ONLY facts literally present in OPS DATA or returned by a "
    "tool. Never invent or guess a task number, store name, quantity, gallon figure, time, or "
    "quote. Do not infer that a problem exists at a store unless it is actually in the data.\n"
    "- For ANY 'which store / busiest / overview / how many' question, answer from the PER-STORE "
    "and BOARD TOTALS section (those are complete). NEVER generalize the whole board from the "
    "SAMPLE task list — it is only a slice. If two answers would differ, the COMPLETE counts win.\n"
    "- If you don't have something, say so plainly and offer to pull it with a tool (you can "
    "look up any store). 'I don't see that in the data' is always better than a guess.\n"
    "- You understand the operation's structure: use get_org for which room maps to which "
    "store, what each room is for (store chat vs all-captains vs marketing), who is active "
    "in each store (likely works there), and who the admins/managers are — for any "
    "'who works at X', 'who's the manager', or 'who is <person>' question.\n"
    "- For ANY question about a specific store ('what's happening at X', 'issues at X', "
    "'whats the <thing> issue at X'), you MUST call lookup_site for that store FIRST and "
    "answer from its result. The SAMPLE in OPS DATA is incomplete per store — NEVER answer "
    "a store-specific question from the sample alone, and never say 'the rest isn't broken "
    "out' — call the tool. For each issue, give WHEN it was reported (the date/time in the "
    "tool result) and include the 🔗 link to that store's chat. For 'where did <person> say "
    "<thing>' use search_history and quote who + when with the 🔗 link. Always give the "
    "date/time and the link.\n"
    "- You can act: close or assign tasks directly when asked — just do it and confirm "
    "naturally."
)


def enabled() -> bool:
    return bool(os.getenv(API_KEY_ENV))


def _snapshot(room_name: str | None) -> str:
    """Compact live ops context for the model.

    Leads with the COMPLETE per-store aggregate (same source as the /summary
    command) so the model answers "which store / overview / how many" from real
    totals — never from the small task sample. Feeding only a 20-of-240 task
    sample is what made the bot name a different "dominant store" every call and
    invent counts; the aggregate fixes that at the root.
    """
    lines: list[str] = []
    # 1) COMPLETE board aggregate — the source of truth for any overview question.
    try:
        d = reports.dashboard()
        tcounts = {x["status"]: x["count"] for x in d.get("tasks", [])}
        open_total = tcounts.get("open", 0)
        high_total = next((x["count"] for x in d.get("priorities", [])
                           if x["priority"] == "high"), 0)
        lines.append(f"BOARD TOTALS (complete — all stores): {open_total} open tasks, "
                     f"{high_total} high-priority messages, "
                     f"{d.get('totals', {}).get('messages', 0)} messages total.")
        lines.append("PER-STORE counts (COMPLETE, over ALL data — use THIS for any "
                     "'which store / busiest / how many' question, never the SAMPLE below):")
        for r in d.get("top_rooms", []):
            lines.append(f"• {r['room_name']}: {r['tasks']} task-msgs, "
                         f"{r['high']} high-priority, {r['messages']} msgs")
    except Exception:
        lines.append("(board totals unavailable)")
    # 2) Deterministic SAMPLE of top-priority tasks — for detail only, NOT for counting.
    try:
        tasks = reports.open_tasks(limit=25)
        lines.append(f"\nSAMPLE — top {len(tasks)} highest-priority open tasks (a SAMPLE only; "
                     f"do NOT derive per-store totals or 'dominant store' from this list — "
                     f"use PER-STORE above):")
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
        "name": "read_image",
        "description": "Read the most recent photo posted in this conversation when the user "
                       "refers to 'this photo', 'the image I sent', 'read that', 'what does "
                       "this say', etc. Returns what the image shows.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_scorecard",
        "description": "Per-store scorecard / health: open task count, high-priority count, "
                       "top recurring issue types, and activity volume. Use for 'how is store "
                       "X doing', store performance, or comparison questions.",
        "input_schema": {
            "type": "object",
            "properties": {"store": {"type": "string", "description": "Store name/number"}},
            "required": ["store"],
        },
    },
    {
        "name": "get_fuel",
        "description": "Get fuel delivery & tank data — BOL gallons delivered, Veeder-Root "
                       "tank readings, and any flagged BOL-vs-Veeder discrepancies — for "
                       "reconciliation / shrinkage / loss-prevention questions. Optionally "
                       "filter by store.",
        "input_schema": {
            "type": "object",
            "properties": {"store": {"type": "string", "description": "Optional store filter"}},
            "required": [],
        },
    },
    {
        "name": "get_org",
        "description": "Understand the operation's structure: which rooms are which "
                       "(store chats vs all-captains vs marketing), what store each maps to, "
                       "who is active in each store (likely works there), and who the "
                       "admins/managers are. Use for 'who works at X', 'who's the manager of "
                       "X', 'what rooms/stores do we have', or 'who is <person>' questions. "
                       "Optionally filter by a store or person.",
        "input_schema": {
            "type": "object",
            "properties": {"store": {"type": "string", "description": "Optional store or person filter"}},
            "required": [],
        },
    },
    {
        "name": "get_cash_reconcile",
        "description": "Reconcile day-report CASH against bank DEPOSITS — flags where the "
                       "deposit came in SHORT of (or over) the cash a store reported, matched "
                       "by store and date. Use for cash-shortage, missing/late-deposit, or "
                       "loss-prevention questions. Optionally filter by store.",
        "input_schema": {
            "type": "object",
            "properties": {"store": {"type": "string", "description": "Optional store filter"}},
            "required": [],
        },
    },
    {
        "name": "get_reports",
        "description": "Get extracted daily/closing report figures — fuel gallons sold, "
                       "inside (store) sales, fuel sales, total sales — read from report "
                       "photos. Optionally filter by store. Use for questions about volumes, "
                       "sales numbers, or daily report data.",
        "input_schema": {
            "type": "object",
            "properties": {"store": {"type": "string", "description": "Optional store name/number to filter by"}},
            "required": [],
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
    {
        "name": "search_history",
        "description": "Search the FULL message history across all stores by keywords (e.g. "
                       "'ice machine 16', 'power outage windchase', 'who reported the leak'). "
                       "Use for questions about past events, trends, or 'find everything about X'.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
]

# Action tools — only offered to admins, since they change state.
_ACTION_TOOLS = [
    {
        "name": "create_task",
        "description": "Create/log a new task or follow-up when an admin asks to add one "
                       "(e.g. 'add a task to fix the sign at 12 by Friday').",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "What needs doing"},
                "store": {"type": "string", "description": "Store/room it's for, if any"},
                "priority": {"type": "string", "enum": ["high", "medium", "normal"]},
                "due": {"type": "string", "description": "Optional due date/time in plain text"},
            },
            "required": ["title"],
        },
    },
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
    {
        "name": "message_user",
        "description": "Proactively send a Google Chat DM to ANY person in the organization "
                       "by name or email — even someone who has never messaged the bot. Use "
                       "when an admin asks to message / tell / DM / notify / let someone know "
                       "something (e.g. 'tell Abdul Moiz the delivery is here'). The name is "
                       "resolved against the org directory; if it's ambiguous you'll get back "
                       "candidates to confirm before resending.",
        "input_schema": {
            "type": "object",
            "properties": {
                "person": {"type": "string", "description": "Who to message — a name or email, e.g. 'Abdul Moiz' or 'moiz@khawarsons.com'"},
                "message": {"type": "string", "description": "The message to send them"},
            },
            "required": ["person", "message"],
        },
    },
    {
        "name": "broadcast",
        "description": "Announce a message to Chat rooms. scope='all_stores' (default) posts it "
                       "into EVERY store chat the bot is in — use this when the admin says to tell "
                       "all stores / every store / everyone. scope='captains' posts only to the "
                       "all-captains space. For one person, use message_user instead.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "The announcement text"},
                "scope": {"type": "string", "enum": ["all_stores", "captains"],
                          "description": "all_stores = every store chat (default); captains = all-captains space only"},
            },
            "required": ["message"],
        },
    },
]


def _rooms_from_messages(messages, dm_spaces) -> list:
    """(space, room_name) for the distinct group rooms in `messages`, excluding DM
    spaces. Pure + unit-testable; first room_name seen for a space wins."""
    seen: dict[str, str] = {}
    for m in messages or []:
        sp = (m.get("room_id") or "")
        if sp.startswith("spaces/") and sp not in dm_spaces and sp not in seen:
            seen[sp] = m.get("room_name") or sp
    return list(seen.items())


def store_room_spaces() -> list:
    """Live: the rooms the bot has ingested from (members of), minus DM spaces.
    Includes all-captains / marketing too (used by org). Excludes is_dm messages."""
    dm = {os.getenv("OPS_ADMIN_DM_SPACE", "")}
    dm |= {d.get("space") for d in store.list_all("admin_dms") if d.get("space")}
    msgs = [m for m in store.list_all("messages") if not m.get("is_dm")]
    return _rooms_from_messages(msgs, dm)


def store_chat_spaces() -> list:
    """Rooms a broadcast posts to. PREFERS the Chat API spaces.list — every room the
    bot is a member of, *including ones that have been quiet* (so we don't miss a
    store just because it hasn't posted lately). Falls back to message-derived
    station rooms only if the API is unavailable (which also excludes DM/test junk)."""
    from app import chat_media
    live = chat_media.list_bot_spaces()
    if live:
        return live
    from app import sites
    return [(sp, rn) for sp, rn in store_room_spaces() if sites.is_station(rn)]


def _room_link(room_id: str = "", room_name: str = "", is_dm: bool = False) -> str:
    """Google Chat link to a conversation. Prefers Google's OWN spaceUri (reliable —
    opens the actual chat); falls back to a constructed URL."""
    try:
        from app import chat_media
        m = chat_media.space_uri_map()
        uri = m.get(room_id) or m.get(room_name)
        if uri:
            return uri
    except Exception:
        pass
    space = (room_id or "").replace("spaces/", "").strip()
    if space and "/" not in space and not space.startswith(("live-", "Direct")):
        return f"https://chat.google.com/{'dm' if is_dm else 'room'}/{space}"
    return ""


def _message_link(m: dict) -> str:
    """Link to the Google Chat conversation a stored message is in (room or DM)."""
    return _room_link(m.get("room_id", ""), m.get("room_name", ""), bool(m.get("is_dm")))


def _run_tool(name: str, args: dict, sender: str = "", space_id: str = "") -> str:
    from app import reports
    try:
        if name == "remember_preference":
            return _save_pref(sender, str(args.get("preference", "")))
        if name == "read_image":
            from app import chat_media, vision
            if not space_id:
                return "No conversation context to find an image."
            img = chat_media.latest_image(space_id)
            if not img:
                return "I don't see a recent photo in this conversation."
            data = chat_media.download_attachment(img["resource_name"])
            if not data:
                return "I found a photo but couldn't open it."
            res = vision.analyze_image(data, img.get("content_type", "image/jpeg"))
            return res.get("summary", "(couldn't read the image)")
        if name == "get_scorecard":
            sq = str(args.get("store", "")).lower().strip()
            tasks = [t for t in reports.open_tasks(limit=600) if sq in (t.get("room_name") or "").lower()]
            msgs = [m for m in store.list_all("messages") if sq in (m.get("room_name") or "").lower()]
            from collections import Counter
            cats = Counter(t.get("category") or "other" for t in tasks)
            high = sum(1 for t in tasks if t.get("priority") == "high")
            top = ", ".join(f"{c} ({n})" for c, n in cats.most_common(5)) or "none"
            return (f"{args.get('store')}: {len(tasks)} open tasks ({high} high-priority), "
                    f"{len(msgs)} messages on record. Top open issue types: {top}.")
        if name == "get_fuel":
            rows = store.list_all("fuel_events")
            sq = str(args.get("store", "")).lower().strip()
            if sq:
                rows = [r for r in rows if sq in (r.get("room_name") or "").lower()]
            if not rows:
                return "No BOL or Veeder-Root fuel readings captured yet."
            rows = sorted(rows, key=lambda r: r.get("report_date") or "", reverse=True)[:30]
            out = []
            for r in rows:
                p = [str(r.get("room_name"))]
                if r.get("report_date"): p.append(str(r["report_date"]))
                if r.get("bol_gallons") is not None: p.append(f"BOL {r['bol_gallons']} gal")
                if r.get("veeder_gallons") is not None: p.append(f"Veeder {r['veeder_gallons']} gal")
                if r.get("discrepancy_gallons"): p.append(f"DIFF {r['discrepancy_gallons']} gal")
                out.append(" · ".join(p))
            return "\n".join(out)
        if name == "get_org":
            from app import org
            q = str(args.get("store", "")).lower().strip()
            rooms = org.describe_rooms_live()
            people = org.roster_live()
            stores = [r for r in rooms if r["purpose"] == "store"]
            other = sorted({r["purpose"] for r in rooms if r["purpose"] != "store"})
            if q:
                stores = [r for r in stores if q in (r["room_name"] or "").lower()
                          or q in (r.get("store") or "").lower()]
            lines = [f"ROOMS — {len(stores)} store chats"
                     + (f", plus {', '.join(other)}" if other and not q else "") + ":"]
            for r in stores[:30]:
                lines.append(f"• {r['room_name']} → {r.get('store') or '?'}")
            sel = {s: v for s, v in people.items()
                   if not q or q in s.lower() or (v.get("home_store") and q in v["home_store"].lower())}
            admins = sorted([s for s, v in sel.items() if v["is_admin"]])
            if admins:
                lines.append("Admins/managers: " + ", ".join(admins))
            top = sorted(sel.items(), key=lambda kv: kv[1]["messages"], reverse=True)[:15]
            if top:
                lines.append("People (most active → likely home store):")
                for s, v in top:
                    lines.append(f"• {s}{' [admin]' if v['is_admin'] else ''} — "
                                 f"{v.get('home_store') or 'multiple/unknown'}")
            return "\n".join(lines) if len(lines) > 1 else "No org data captured yet."
        if name == "get_cash_reconcile":
            from app import cash_reconcile
            rows = cash_reconcile.discrepancies(only_flagged=False)
            sq = str(args.get("store", "")).lower().strip()
            if sq:
                rows = [r for r in rows if sq in (r.get("room_name") or "").lower()]
            if not rows:
                return "No day-report cash vs deposit data to reconcile yet."
            flagged = [r for r in rows if r.get("flagged")]
            shown = (flagged or rows)[:30]
            out = []
            for r in shown:
                tag = "⚠️ " if r.get("flagged") else ""
                p = [f"{tag}{r.get('room_name')}"]
                if r.get("report_date"):
                    p.append(str(r["report_date"]))
                p.append(r.get("reason", ""))
                out.append(" · ".join(p))
            header = (f"{len(flagged)} flagged cash/deposit mismatch(es):\n" if flagged
                      else "No cash/deposit mismatches over threshold. Recent:\n")
            return header + "\n".join(out)
        if name == "get_reports":
            rows = store.list_all("day_reports")
            store_q = str(args.get("store", "")).lower().strip()
            if store_q:
                rows = [r for r in rows if store_q in (r.get("room_name") or "").lower()]
            if not rows:
                return ("No daily-report figures available yet. (Report photos may not be "
                        "scanned, or none posted for that store.)")
            rows = sorted(rows, key=lambda r: r.get("report_date") or "", reverse=True)[:30]
            out = []
            for r in rows:
                parts = [f"{r.get('room_name')}"]
                if r.get("report_date"): parts.append(f"date {r['report_date']}")
                if r.get("fuel_gallons_sold") is not None: parts.append(f"{r['fuel_gallons_sold']} gal")
                if r.get("inside_sales") is not None: parts.append(f"inside ${r['inside_sales']}")
                if r.get("fuel_sales") is not None: parts.append(f"fuel ${r['fuel_sales']}")
                if r.get("total_sales") is not None: parts.append(f"total ${r['total_sales']}")
                out.append(" · ".join(parts))
            return "\n".join(out)
        if name == "search_history":
            terms = str(args.get("query", "")).lower().split()
            hits = []
            for m in store.list_all("messages"):
                hay = f"{m.get('room_name','')} {m.get('message','')} {m.get('sender','')}".lower()
                if all(t in hay for t in terms):
                    hits.append(m)
            if not hits:
                return "Nothing in the history matches that."
            hits = sorted(hits, key=lambda m: (m.get("seq") or 0, m.get("created_at") or ""), reverse=True)[:15]
            out = []
            for m in hits:
                day = (m.get("sent_at") or m.get("created_at") or m.get("timestamp_raw") or "")[:10]
                line = (f"[{m.get('room_name')}] {m.get('sender')} ({day}): "
                        f"{(m.get('message') or '')[:160]}")
                link = _message_link(m)
                if link:
                    line += f"\n  🔗 open {m.get('room_name')}: {link}"
                out.append(line)
            return "\n".join(out)
        if name == "create_task":
            tid = store.next_seq("tasks")
            now = datetime.now(timezone.utc).isoformat()
            store.create("tasks", {
                "id": tid, "room_name": args.get("store", ""), "sender": sender,
                "task_title": args.get("title", ""), "task_text": args.get("title", ""),
                "category": "manual", "priority": args.get("priority", "normal"),
                "status": "open", "due": args.get("due"),
                "created_at": now, "updated_at": now,
            }, doc_id=str(tid))
            bits = []
            if args.get("store"): bits.append(f"for {args['store']}")
            if args.get("due"): bits.append(f"due {args['due']}")
            return f"Logged it{(' ' + ', '.join(bits)) if bits else ''}."
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
            link = _room_link(room_name=s["room_name"])
            out = [f"{s['room_name']}: {s['messages']} msgs, {s['tasks']} task-msgs, {s['high']} high-priority."
                   + (f"  🔗 {link}" if link else "")]
            for t in rs.get("open_tasks", [])[:12]:
                when = reports.fmt_ts(t.get("sent_at") or t.get("created_at"))
                out.append(f"#{t['id']} ({t.get('priority')}) {t.get('task_title') or t.get('task_text')}"
                           + (f"  — {when}" if when else ""))
            return "\n".join(out)
        if name == "close_task":
            r = reports.task_action(None, int(args["task_id"]), "close")
            return f"Closed task #{args['task_id']}." if r.get("ok") else f"Failed: {r.get('error')}"
        if name == "assign_task":
            r = reports.task_action(None, int(args["task_id"]), "assign", str(args.get("assignee", "")))
            return (f"Assigned task #{args['task_id']} to {args.get('assignee')}."
                    if r.get("ok") else f"Failed: {r.get('error')}")
        if name == "message_user":
            from app import directory
            person = str(args.get("person", "")).strip()
            text = str(args.get("message", "")).strip()
            if not person or not text:
                return "I need both who to message and what to say."
            res = directory.message_person(person, text)
            if res.get("ok"):
                return f"Sent your message to {res.get('matched_name') or res.get('email')}."
            if res.get("error") == "ambiguous":
                opts = "; ".join(f"{c.get('name')} <{c.get('email')}>" for c in res.get("candidates", []))
                return f"More than one person matches '{person}': {opts}. Who did you mean?"
            if res.get("error") == "not_found":
                return f"I couldn't find anyone matching '{person}' in the directory."
            return f"Couldn't message {person}: {res.get('error')}"
        if name == "broadcast":
            from app import chat_media
            text = str(args.get("message", "")).strip()
            if not text:
                return "What should I announce?"
            body = f"📢 {text}"
            scope = str(args.get("scope", "all_stores")).lower()
            if scope == "captains":
                space = os.getenv("OPS_ALL_CAPTAINS_SPACE", "spaces/AAAAhO6H0_Y")
                return ("Announcement posted to all-captains."
                        if chat_media.post_to_space(space, body) else "Couldn't post the announcement.")
            rooms = store_chat_spaces()
            if not rooms:
                return "I don't have any store rooms on record to post to yet."
            sent, failed = [], []
            for sp, rn in rooms:
                (sent if chat_media.post_to_space(sp, body) else failed).append(rn)
            res = f"📢 Sent to {len(sent)} store chats: {', '.join(sorted(sent))}."
            if failed:
                res += (f" Couldn't reach {len(failed)} (bot may have been removed from these "
                        f"rooms): {', '.join(sorted(failed))}.")
            res += (" Any store NOT listed here isn't a room I've been added to — add me to its "
                    "chat and I'll reach it next time.")
            return res
    except Exception as e:
        return f"Tool error: {e}"
    return f"Unknown tool {name}"


def _post_once(payload: bytes) -> dict:
    """Single POST to the Claude Messages endpoint. Raises on HTTP/network error."""
    req = urllib.request.Request(ENDPOINT, data=payload, headers={
        "x-api-key": os.environ[API_KEY_ENV],
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    })
    return json.loads(urllib.request.urlopen(req, context=_ctx, timeout=BRAIN_TIMEOUT).read())


def _retry_after(err: urllib.error.HTTPError) -> float | None:
    """Honor a numeric Retry-After header (seconds) if the server sent one."""
    try:
        v = err.headers.get("Retry-After")
        return float(v) if v else None
    except (TypeError, ValueError, AttributeError):
        return None


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
    payload = json.dumps(body).encode()

    for attempt in range(1, BRAIN_MAX_ATTEMPTS + 1):
        try:
            return _post_once(payload)
        except urllib.error.HTTPError as e:
            # Client errors (bad request, auth) won't fix themselves — fail fast.
            # The caller (answer) reads the body, so don't consume it here.
            if e.code not in _RETRY_STATUS or attempt == BRAIN_MAX_ATTEMPTS:
                raise
            delay = _retry_after(e) or BRAIN_BACKOFF_BASE * (2 ** (attempt - 1))
            reason = f"HTTP {e.code}"
        except (urllib.error.URLError, TimeoutError, socket.timeout) as e:
            if attempt == BRAIN_MAX_ATTEMPTS:
                raise
            delay = BRAIN_BACKOFF_BASE * (2 ** (attempt - 1))
            reason = type(e).__name__
        delay = min(delay, BRAIN_BACKOFF_MAX)
        print(f"[brain] transient {reason} (attempt {attempt}/{BRAIN_MAX_ATTEMPTS}); "
              f"retrying in {delay:.1f}s", flush=True)
        _sleep(delay)
    # Loop always returns or raises above; this satisfies type-checkers.
    raise RuntimeError("unreachable: claude retry loop exited without result")


def _conv_id(space_id: str, sender: str = "") -> str:
    # Per-user within a space: in a shared room each captain keeps their own
    # short-term thread, so one person's follow-up ("and the other one?") never
    # pulls another person's turns (also avoids leaking one user's context).
    raw = f"{space_id or 'dm'}|{(sender or '').lower()}"
    return raw.replace("/", "_")[:1400]


def _load_turns(space_id: str | None, sender: str = "") -> list[dict]:
    if not space_id:
        return []
    try:
        d = store.get("conversations", _conv_id(space_id, sender))
        if d and d.get("turns"):
            return json.loads(d["turns"])
    except Exception:
        pass
    return []


def _save_turn(space_id: str | None, sender: str, user_text: str, assistant_text: str) -> None:
    if not space_id:
        return
    try:
        cid = _conv_id(space_id, sender)
        turns = _load_turns(space_id, sender)
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
           space_id: str | None = None, image_note: str = "") -> str | None:
    """Return Claude's reply, executing close/assign tools if it requests them
    (admins only), with short-term memory of the last few turns in this space.
    Returns None on failure so the caller can fall back."""
    if not enabled() or not (user_msg or "").strip():
        return None
    snapshot = _snapshot(room_name)
    prefs = _load_prefs(sender)
    prefs_block = ("\nThis user's saved preferences (honor them):\n" +
                   "\n".join(f"- {p}" for p in prefs) + "\n") if prefs else ""
    image_block = (f"\nThe user attached photo(s); your vision system already read them:\n"
                   f"{image_note}\nIncorporate this into your reply naturally.\n") if image_note else ""
    user_block = (
        f"RIGHT NOW it is {now_central()} (Texas time). Use this for any 'today', "
        f"'this week', 'overdue', or 'how long ago' reasoning.\n\n"
        f"OPS DATA (current):\n{snapshot}\n{prefs_block}{image_block}\n"
        f"---\nUser ({sender}{', admin' if is_admin else ''}) in "
        f"room '{room_name or 'DM'}' says:\n{user_msg}"
    )
    # Prior turns give multi-turn continuity ("what about site 11?"), scoped to
    # this user so a shared room doesn't cross-contaminate threads.
    messages = _load_turns(space_id, sender) + [{"role": "user", "content": user_block}]
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
                        out = _run_tool(block["name"], block.get("input", {}), sender, space_id or "")
                        results.append({"type": "tool_result", "tool_use_id": block["id"], "content": out})
                messages.append({"role": "user", "content": results})
                continue
            text = "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text").strip()
            if text:
                _save_turn(space_id, sender, user_msg, text)
            return text or None
        return None
    except urllib.error.HTTPError as e:
        print(f"[brain] {e.code}: {e.read().decode()[:200]}", flush=True)
        return None
    except Exception as e:
        print(f"[brain] error: {e}", flush=True)
        return None
