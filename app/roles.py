"""Scoped role + permission model (below admin).

Today the bot has three tiers (owner / admin / everyone) enforced ad hoc in
`app/chat_live.py`. This module formalizes that and adds the "Discord-style"
scoped roles sketched in docs/ROLES.md — position-based roles that grant a
specific permission set and, optionally, a data scope (which stores).

It is the single authority for "may <email> do <permission> [on <site>]?". It
reads the SAME env as chat_live (`OPS_OWNER_EMAIL`, `OPS_ADMIN_EMAILS`) so
owner/admin behavior is unchanged, and adds scoped roles via `OPS_ROLES`:

    OPS_ROLES=[
      {"email": "reg@k.com",  "role": "regional_manager", "sites": ["4", "11"]},
      {"email": "fuel@k.com", "role": "fuel_manager"},
      {"email": "rep@k.com",  "role": "reports_admin"}
    ]

Pure stdlib + app.sites for site-key normalization (so a scope of "11" also
matches "Windchase" / "11 N&F Windchase"). The owner is always above every role.
"""
from __future__ import annotations

import json
import os

from app import sites

# --- Permissions ----------------------------------------------------------
VIEW = "view"
SET_PREFERENCE = "set_preference"
CLOSE_TASK = "close_task"
ASSIGN_TASK = "assign_task"
AI_ACTION = "ai_action"
VIEW_FUEL = "view_fuel"
TRACK_REPORTS = "track_reports"
MANAGE_ROLES = "manage_roles"

ALL_PERMISSIONS = frozenset({
    VIEW, SET_PREFERENCE, CLOSE_TASK, ASSIGN_TASK, AI_ACTION,
    VIEW_FUEL, TRACK_REPORTS, MANAGE_ROLES,
})

# --- Roles ----------------------------------------------------------------
# Each role grants a permission set. Scope (which stores) is per-user, set on
# the OPS_ROLES entry; roles without a scope see all stores.
ROLE_PERMISSIONS: dict[str, frozenset] = {
    "owner": ALL_PERMISSIONS,
    "admin": ALL_PERMISSIONS - {MANAGE_ROLES},
    "regional_manager": frozenset({VIEW, SET_PREFERENCE, CLOSE_TASK, ASSIGN_TASK, AI_ACTION, VIEW_FUEL, TRACK_REPORTS}),
    "fuel_manager": frozenset({VIEW, SET_PREFERENCE, AI_ACTION, VIEW_FUEL}),
    "reports_admin": frozenset({VIEW, SET_PREFERENCE, AI_ACTION, TRACK_REPORTS}),
    "viewer": frozenset({VIEW, SET_PREFERENCE}),
}

DEFAULT_ROLE = "viewer"
# Roles that are inherently scoped to specific stores when `sites` is provided.
_SCOPED_ROLES = {"regional_manager"}


def _norm_email(email: str | None) -> str:
    return (email or "").strip().lower()


def _owner_email() -> str:
    return _norm_email(os.getenv("OPS_OWNER_EMAIL", "aayan@khawarsons.com"))


def _admin_emails() -> set[str]:
    raw = os.getenv(
        "OPS_ADMIN_EMAILS",
        "aayan@khawarsons.com,admin1@nowandforever.com,admin2@nowandforever.com",
    )
    admins = {_norm_email(e) for e in raw.split(",") if e.strip()}
    admins.add(_owner_email())  # owner is always an admin
    return admins


def _scoped_roles() -> dict[str, dict]:
    """email -> {"role": str, "sites": [site_key, ...]} from OPS_ROLES."""
    out: dict[str, dict] = {}
    raw = os.getenv("OPS_ROLES")
    if not raw:
        return out
    try:
        entries = json.loads(raw)
    except Exception:
        return out  # never let a bad env var break authorization
    for e in entries if isinstance(entries, list) else []:
        if not isinstance(e, dict):
            continue
        email = _norm_email(e.get("email"))
        role = str(e.get("role") or "").strip()
        if not email or role not in ROLE_PERMISSIONS:
            continue
        scope = [sites.site_key(s) for s in (e.get("sites") or []) if sites.site_key(s)]
        out[email] = {"role": role, "sites": scope}
    return out


def role_of(email: str | None) -> str:
    """Highest applicable role. Owner and admin always win over OPS_ROLES so no
    scoped entry can demote them."""
    em = _norm_email(email)
    if not em:
        return DEFAULT_ROLE
    if em == _owner_email():
        return "owner"
    if em in _admin_emails():
        return "admin"
    entry = _scoped_roles().get(em)
    if entry:
        return entry["role"]
    return DEFAULT_ROLE


def permissions_of(email: str | None) -> frozenset:
    return ROLE_PERMISSIONS.get(role_of(email), ROLE_PERMISSIONS[DEFAULT_ROLE])


def can(email: str | None, permission: str) -> bool:
    return permission in permissions_of(email)


def site_scope(email: str | None) -> set[str] | None:
    """Set of site keys this user is limited to, or None for all stores.

    Owner/admin and unscoped roles get None (all stores). A scoped role with an
    explicit `sites` list is limited to those; a scoped role with an empty list
    is also treated as all stores (scope not yet configured)."""
    em = _norm_email(email)
    if em == _owner_email() or em in _admin_emails():
        return None
    entry = _scoped_roles().get(em)
    if entry and entry["role"] in _SCOPED_ROLES and entry["sites"]:
        return set(entry["sites"])
    return None


def can_view_site(email: str | None, site: str | None) -> bool:
    """Whether the user may see data for a given site/room name."""
    scope = site_scope(email)
    if scope is None:
        return True
    key = sites.site_key(site)
    return bool(key) and key in scope


def can_act_on_site(email: str | None, site: str | None, permission: str) -> bool:
    """Both the permission AND the site scope must allow it."""
    return can(email, permission) and can_view_site(email, site)


# --- Back-compat helpers (mirror app.chat_live) ---------------------------
def is_owner(email: str | None) -> bool:
    return _norm_email(email) == _owner_email()


def is_admin(email: str | None) -> bool:
    return _norm_email(email) in _admin_emails()
