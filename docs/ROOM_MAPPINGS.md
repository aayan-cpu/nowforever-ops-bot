# Room to Site Mappings

This document tracks the mapping between Google Chat Space IDs and the physical gas station sites they correspond to.

---

## Why This Matters

Google Chat identifies rooms by their **Space ID** (e.g., `AAAAayKiMyg`), not by their display name. When the bot receives a webhook event, it receives the Space ID. To show human-readable site names in the dashboard and alerts, the Space ID must be mapped to a site name.

This mapping is implemented in `app/sites.py` — the canonical site resolver (the
list below is its source of truth).

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

## Where this lives in code (`app/sites.py`)

Site resolution is implemented in `app/sites.py`. Rather than a raw Space-ID → name
dictionary, it resolves any free-form reference (a bare number `"11"`, a place
`"Windchase"`, or a full room name `"11 N&F Windchase"`) to one canonical station,
so reports and digests don't double-count a station referred to several ways.

The station registry is `_BASE_SITES` (site number, canonical name, and alias
words). Public API:

```python
from app import sites

sites.canonical_name("windchase")   # -> "11 N&F Windchase"
sites.site_key("11 N&F Windchase")   # -> "11"   (stable grouping key)
sites.same_site("11", "Windchase")   # -> True
sites.is_station("All Captains Chat")  # -> False (company-wide room, not a station)
sites.resolve("24 Galveston")          # -> {"number": 24, "name": "24 Galveston", "key": "24"}
```

**To add a station:** add an entry to `_BASE_SITES` in `app/sites.py`, or — without a
code change — set the `OPS_SITES_EXTRA` env var to a JSON array of
`{"number": 7, "name": "7 Somewhere", "aliases": ["somewhere"]}`.

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

*Update this file whenever a new Space ID is confirmed. Keep the site registry in `app/sites.py` in sync.*
