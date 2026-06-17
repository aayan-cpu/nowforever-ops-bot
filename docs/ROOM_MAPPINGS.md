# Room to Site Mappings

This document tracks the mapping between Google Chat Space IDs and the physical gas station sites they correspond to.

---

## Why This Matters

Google Chat events carry both a **Space ID** (e.g., `spaces/AAAAayKiMyg`) and,
in most events, the room's **display name**. The live bot reads the human-readable
room name straight from the event (`space.displayName` in
`app/chat_live.py:extract_chat_event`), falling back to the Space ID only when no
display name is present.

There is **no** `app/room_mappings.py` module. Canonical site identity — unifying
"11", "Windchase", and "11 N&F Windchase" into one site — lives in `app/sites.py`,
which is seeded from the confirmed sites in this document. The Space ID ↔ site
table below is reference data for that seed and for back-filling room names on
events that arrive without a display name.

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

## Space ID ↔ Site reference data

The live bot does not need a hand-maintained Space ID → name dictionary — it
reads the display name from each event. This table is reference data: it seeds
`app/sites.py` (canonical site identity) and documents the confirmed Space IDs
for back-filling room names on events that lack a display name.

```python
# Confirmed Space ID -> room display name (reference; see app/sites.py for the
# canonical site registry built from these).
SPACE_NAMES = {
    "AAAAAyLVEg0": "11 N&F Windchase",
    "AAAAayKiMyg": "4 Channelview",
    "AAAAhO6H0_Y": "All Captains Chat",
    "AAAA3s2JArA": "12 S Main Stafford",
    "AAAAox_RoBo": "27 Fry",
    # Remaining sites (1 Coastal Mart, 9 Bissonnet, 18 Harwin & Gessener,
    # 24 Galveston, 29 Westheimer, ...) still need their Space IDs confirmed
    # from the Chat admin console.
}
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

*Update this file whenever a new Space ID is confirmed, and add the site to the
seed in `app/sites.py` if it introduces a new number/location alias.*
