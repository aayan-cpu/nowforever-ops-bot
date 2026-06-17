"""Org knowledge — what each room is, which store it maps to, who is active where,
and who the managers/admins are. Derived from the live message stream + role config
so the brain understands the operation's structure without it being hardcoded.

Pure functions take their data as arguments (unit-testable). The *_live wrappers
read Firestore. Store naming reuses app/sites.py.
"""
from __future__ import annotations

import os
import re
from collections import defaultdict

from app import sites


def room_purpose(room_name: str) -> str:
    """Classify a room by what it's for, from its name."""
    n = (room_name or "").strip().lower()
    if not n:
        return "other"
    if "captain" in n:
        return "all-captains"          # cross-store leadership channel
    if "marketing" in n:
        return "marketing"
    if sites.is_station(room_name):
        return "store"                 # an individual store's chat
    return "other"


def describe_rooms(rooms) -> list[dict]:
    """rooms: iterable of (space, room_name). Returns purpose + canonical store per
    room. Pure."""
    out = []
    for space, name in rooms or []:
        purpose = room_purpose(name)
        store = sites.canonical_name(name) if purpose == "store" else None
        out.append({"space": space, "room_name": name, "purpose": purpose, "store": store})
    return out


def roster(messages, admin_emails=None) -> dict:
    """Who's active where. From messages, build {person: {rooms, messages, is_admin,
    home_store}}. `home_store` = the store room they post in most (where they work).
    Pure."""
    admins = {(e or "").lower() for e in (admin_emails or set())}
    acc: dict[str, dict] = {}
    for m in messages or []:
        sender = (m.get("sender") or "").strip()
        if not sender or sender.lower() in {"updated on", "bot", "ops bot"}:
            continue
        rn = m.get("room_name") or "?"
        p = acc.setdefault(sender, {"rooms": defaultdict(int), "messages": 0})
        p["rooms"][rn] += 1
        p["messages"] += 1
    out = {}
    for sender, p in acc.items():
        store_rooms = {rn: n for rn, n in p["rooms"].items() if sites.is_station(rn)}
        home = max(store_rooms, key=store_rooms.get) if store_rooms else None
        out[sender] = {
            "rooms": dict(p["rooms"]),
            "messages": p["messages"],
            "is_admin": sender.lower() in admins,
            "home_store": sites.canonical_name(home) if home else None,
        }
    return out


def manager_by_store(messages) -> dict:
    """Heuristic: '@Admin 4' style mentions tie a manager handle to a store number.
    Returns {store_number: [handles]}. Pure."""
    by_store: dict[str, set] = defaultdict(set)
    for m in messages or []:
        hint = (m.get("assigned_hint") or "")
        for mm in re.finditer(r"admin\s*#?\s*(\d+)", hint, re.I):
            by_store[mm.group(1)].add(f"Admin {mm.group(1)}")
    return {k: sorted(v) for k, v in by_store.items()}


def summary(rooms, messages, admin_emails=None) -> str:
    """Compact org overview for the brain. Pure."""
    desc = describe_rooms(rooms)
    stores = [d for d in desc if d["purpose"] == "store"]
    other = [d for d in desc if d["purpose"] != "store"]
    lines = [f"ROOMS: {len(stores)} store chats" +
             (f" + " + ", ".join(sorted({d['purpose'] for d in other})) if other else "")]
    people = roster(messages, admin_emails)
    admins = sorted([s for s, v in people.items() if v["is_admin"]])
    if admins:
        lines.append("ADMINS/managers: " + ", ".join(admins))
    return "\n".join(lines)


# ---- live wrappers -------------------------------------------------------
def _room_pairs_live() -> list:
    from app.brain import store_room_spaces
    return store_room_spaces()


def describe_rooms_live() -> list[dict]:
    return describe_rooms(_room_pairs_live())


def roster_live() -> dict:
    from app import store
    admins = {e.strip().lower() for e in os.getenv(
        "OPS_ADMIN_EMAILS",
        "aayan@khawarsons.com,admin1@nowandforever.com,admin2@nowandforever.com",
    ).split(",") if e.strip()}
    admins.add(os.getenv("OPS_OWNER_EMAIL", "aayan@khawarsons.com").lower().strip())
    return roster(store.list_all("messages"), admins)
