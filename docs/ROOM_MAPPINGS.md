# Room to Site Mappings

This document tracks the mapping between Google Chat Space IDs and the physical gas station sites they correspond to.

> **Status (2026-06-17):** The planned `app/room_mappings.py` module was **never
> created** — it was superseded before it shipped. At runtime each Google Chat
> event already carries the room's `displayName`, which `app/chat_live.py`
> records directly, and `app/sites.py` canonicalizes any site reference ("11",
> "Windchase", "11 N&F Windchase" → one site). This file remains useful as a
> human reference of confirmed Space IDs; the Python snippet below is illustrative
> only (no module imports it).

---

## Why This Matters

Google Chat identifies rooms by their **Space ID** (e.g., `AAAAayKiMyg`), not by their display name. When the bot receives a webhook event, it receives the Space ID. To show human-readable site names in the dashboard and alerts, the Space ID must be mapped to a site name.

Historically this was meant to live in a static `app/room_mappings.py` dictionary; in practice the bot reads the room's live `displayName` from each event and resolves it through `app/sites.py` (see status note above).

---

## Current Mappings (Confirmed)

| Space ID | Room Name | Site # | Location | Status |
|---|---|---|---|---|
| `AAAAAyLVEg0` | 11 N&F Windchase | 11 | Windchase area | Confirmed |
| `AAAAayKiMyg` | 4 Channelview | 4 | Channelview | Confirmed |
| `AAAAhO6H0_Y` | All Captains Chat | N/A | Company-wide | Confirmed |
| `AAAA3s2JArA` | 12 S Main Stafford | 12 | S Main St, Stafford | Confirmed |
| `AAAAox_RoBo` | 27 Fry | 27 | Fry Rd area | Confirmed |

---

## Sites Referenced in Vault Data (Mapping Needed)

The following sites appeared in message content during the Vault data analysis but do not yet have confirmed Space ID mappings. They need to be identified by checking the Google Chat admin console.

| Site # | Name | Notes |
|---|---|---|
| 1 | Coastal Mart | Gas price/logo remote broken (high priority) |
| 9 | Bissonnet | Ice machine down (high priority) |
| 18 | Harwin & Gessener | Machine #1 down, tickets not printing (high priority) |
| 24 | Galveston | Needs gas delivery (high priority) |
| 29 | Westheimer | 4-hour power outage (high priority) |
| TBD | Additional sites 2–27 | Need Space IDs from Chat admin |

---

## How to Find a Room's Space ID

### Method 1: Google Chat Admin Console (Recommended)
1. Go to [admin.google.com](https://admin.google.com)
2. Navigate to **Apps > Google Workspace > Google Chat**
3. Click **Spaces**
4. Find the room and look at the URL — the Space ID is in the URL path

### Method 2: From the Vault Export
The mbox export contains Space IDs in message headers. Look for lines like:
```
X-Original-Sender: spaces/AAAAayKiMyg/members/...
```

### Method 3: Via Bot
Once the bot is deployed and added to a room, it receives the Space ID in every webhook event. Add a `/spaceid` command to the bot that returns the current room's Space ID.

---

## Room Mappings Python Code (illustrative — not in the codebase)

This is the static-dict approach that was originally planned. It is **not**
implemented: no `app/room_mappings.py` exists and nothing imports it. Site
resolution is handled live by `app/sites.py` instead. Kept here only to document
the confirmed Space IDs and the shape such a lookup would take:

```python
# app/room_mappings.py
# Maps Google Chat Space IDs to human-readable site names

ROOM_MAPPINGS = {
    # Confirmed mappings
    "AAAAAyLVEg0": "11 N&F Windchase",
    "AAAAayKiMyg": "4 Channelview",
    "AAAAhO6H0_Y": "All Captains Chat",
    "AAAA3s2JArA": "12 S Main Stafford",
    "AAAAox_RoBo": "27 Fry",

    # TODO: Add Space IDs for remaining sites
    # "SPACE_ID_HERE": "1 Coastal Mart",
    # "SPACE_ID_HERE": "9 Bissonnet",
    # "SPACE_ID_HERE": "18 Harwin & Gessener",
    # "SPACE_ID_HERE": "24 Galveston",
    # "SPACE_ID_HERE": "29 Westheimer",
}

def get_site_name(space_id: str) -> str:
    """Return site name for a given Space ID, or the Space ID itself if unknown."""
    return ROOM_MAPPINGS.get(space_id, f"Unknown Site ({space_id})")

def get_space_id(site_name: str) -> str | None:
    """Return Space ID for a given site name, or None if not found."""
    reverse = {v: k for k, v in ROOM_MAPPINGS.items()}
    return reverse.get(site_name)
```

---

## Company Site Numbering Convention

Based on Vault data analysis, Now & Forever / Khawar & Sons uses a numeric site identifier (1, 4, 9, 11, 12, 18, 24, 27, 29, etc.). The numbers are not sequential — they likely reflect acquisition order or internal numbering.

**Known site numbers from message data:** 1, 4, 9, 11, 12, 18, 24, 27, 29, and others.

---

## Priority for Completing This Mapping

High priority rooms to map first (based on current open issues):

1. **29 Westheimer** — 4-hour power outage
2. **18 Harwin & Gessener** — Machine #1 down
3. **1 Coastal Mart** — Gas price remote broken
4. **9 Bissonnet** — Ice machine down
5. **24 Galveston** — Gas delivery needed

---

*Update this file whenever a new Space ID is confirmed. (Runtime resolution is handled by `app/sites.py` from the event's live `displayName`; there is no `app/room_mappings.py` to keep in sync.)*
