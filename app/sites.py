"""Canonical site-name resolution.

The chain's stations are referred to inconsistently across chat rooms, message
text, and dashboards — by bare number ("11"), by place ("Windchase"), or by the
full room name ("11 N&F Windchase"). This module gives one place to collapse all
of those to a single canonical site so reports, digests, and the brain stop
double-counting one station as several.

Pure stdlib, no I/O — safe to import anywhere and trivial to unit-test.

Public API
----------
    site_key(name)      -> str   stable grouping key (e.g. "11", "galveston")
    canonical_name(name)-> str   friendly display name (e.g. "11 N&F Windchase")
    resolve(name)       -> dict | None   full record, or None for non-stations
    same_site(a, b)     -> bool  do two strings refer to the same station?
    is_station(name)    -> bool  False for company-wide / DM / system spaces

Extending the registry without a code change: set env ``OPS_SITES_EXTRA`` to a
JSON array of ``{"number": 7, "name": "7 Somewhere", "aliases": ["somewhere"]}``.
"""
from __future__ import annotations

import json
import os
import re

# --- Known stations -------------------------------------------------------
# Sourced from docs/ROOM_MAPPINGS.md (confirmed + Vault-referenced sites).
# Each entry: site number, canonical display name, and place/alias words that
# appear on their own ("Windchase", "Harwin"). Numbers are the strongest key;
# aliases catch references that omit the number.
_BASE_SITES: list[dict] = [
    {"number": 1, "name": "1 Coastal Mart", "aliases": ["coastal mart", "coastal"]},
    {"number": 4, "name": "4 Channelview", "aliases": ["channelview"]},
    {"number": 9, "name": "9 Bissonnet", "aliases": ["bissonnet"]},
    {"number": 11, "name": "11 N&F Windchase", "aliases": ["windchase"]},
    {"number": 12, "name": "12 S Main Stafford", "aliases": ["stafford", "s main", "s main stafford"]},
    {"number": 18, "name": "18 Harwin & Gessener", "aliases": ["harwin", "gessener", "harwin & gessener"]},
    {"number": 24, "name": "24 Galveston", "aliases": ["galveston"]},
    {"number": 27, "name": "27 Fry", "aliases": ["fry"]},
    {"number": 29, "name": "29 Westheimer", "aliases": ["westheimer"]},
]

# Names that are not individual stations — company-wide rooms, DMs, raw space
# ids, campus groups. resolve()/site_key() treat these as non-stations.
_NON_STATION_NAMES = {
    "all captains chat",
    "summerbell campus communications group",
}


def _load_sites() -> list[dict]:
    sites = [dict(s) for s in _BASE_SITES]
    extra = os.getenv("OPS_SITES_EXTRA")
    if extra:
        try:
            for s in json.loads(extra):
                if isinstance(s, dict) and ("number" in s or "name" in s):
                    s.setdefault("aliases", [])
                    sites.append(s)
        except Exception:
            pass  # never let a bad env var break resolution
    return sites


_SITES = _load_sites()
# number -> site record, and lowered-alias -> site record, built once.
_BY_NUMBER: dict[int, dict] = {}
_BY_ALIAS: dict[str, dict] = {}
for _s in _SITES:
    if _s.get("number") is not None:
        _BY_NUMBER[int(_s["number"])] = _s
    for _a in _s.get("aliases", []):
        _BY_ALIAS[_a.lower()] = _s


def _normalize(name: str | None) -> str:
    """Lowercase, strip noise words/punctuation, collapse whitespace."""
    s = (name or "").lower().strip()
    # Drop chain branding and locator nouns that add no site identity.
    s = re.sub(r"\bn\s*&\s*f\b", " ", s)
    s = re.sub(r"\b(now\s*&?\s*forever|khawar\s*&?\s*sons|hawar\s*&?\s*sons)\b", " ", s)
    s = re.sub(r"\b(site|store|station|location|#)\b", " ", s)
    # Keep '&' inside aliases (Harwin & Gessener) but normalize spacing.
    s = re.sub(r"[^\w&]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def is_station(name: str | None) -> bool:
    """True unless the name is a company-wide room, DM, or raw space id."""
    raw = (name or "").strip()
    if not raw:
        return False
    low = raw.lower()
    if raw.startswith("spaces/") or low.startswith("direct message"):
        return False
    return _normalize(raw) not in {_normalize(n) for n in _NON_STATION_NAMES}


def resolve(name: str | None) -> dict | None:
    """Resolve a free-form reference to its station record.

    Returns ``{"number": int|None, "name": str, "key": str}`` for a recognized
    or number-bearing station, or ``None`` for blanks and non-stations
    (company-wide rooms, DMs, raw space ids).
    """
    if not is_station(name):
        return None
    norm = _normalize(name)
    if not norm:
        return None

    # 1) A known site number anywhere in the string wins (strongest signal).
    for tok in re.findall(r"\d+", norm):
        n = int(tok)
        if n in _BY_NUMBER:
            s = _BY_NUMBER[n]
            return {"number": n, "name": s["name"], "key": str(n)}

    # 2) A known place/alias word.
    for alias, s in _BY_ALIAS.items():
        if re.search(r"\b" + re.escape(alias) + r"\b", norm):
            num = s.get("number")
            return {"number": num, "name": s["name"],
                    "key": str(num) if num is not None else _slug(s["name"])}

    # 3) An unrecognized but explicit number -> its own site bucket.
    m = re.search(r"\d+", norm)
    if m:
        n = int(m.group())
        return {"number": n, "name": f"Site {n}", "key": str(n)}

    # 4) Unknown named place -> stable slug so variants still group together.
    return {"number": None, "name": (name or "").strip(), "key": _slug(norm)}


def _slug(s: str) -> str:
    return re.sub(r"\s+", "-", _normalize(s)).strip("-")


def site_key(name: str | None) -> str:
    """Stable grouping key for a reference. Empty string for non-stations."""
    r = resolve(name)
    return r["key"] if r else ""


def canonical_name(name: str | None) -> str:
    """Friendly canonical display name (falls back to the cleaned input)."""
    r = resolve(name)
    if not r:
        return (name or "").strip()
    return r["name"]


def same_site(a: str | None, b: str | None) -> bool:
    """True iff both references resolve to the same station."""
    ka, kb = site_key(a), site_key(b)
    return bool(ka) and ka == kb
