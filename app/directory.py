"""Resolve org users and proactively DM anyone — the foundation for the bot
reaching people without them messaging it first.

How it works:
- Directory API (Admin SDK), via domain-wide delegation impersonating a super
  admin, resolves an email -> Google user id (and can list the whole org).
- Chat API (app auth) then finds the bot's DM space with that user id and posts.

Auth required (one-time, admin console → Domain-Wide Delegation, client id
111828330959106535963):
  https://www.googleapis.com/auth/admin.directory.user.readonly

Runs locally with OPS_SA_KEY (signs the DWD JWT). Used to onboard/reach people
and register admins' DM spaces so Cloud Run digests can reach them.
"""
from __future__ import annotations

import base64
import json
import os
import ssl
import time
import urllib.request
import urllib.parse
import urllib.error

from app import chat_media, store

SA_KEY = os.getenv("OPS_SA_KEY", "/tmp/sa-key.json")
SUPER_ADMIN = os.getenv("OPS_SUPER_ADMIN", "aayan@khawarsons.com")
DIR_SCOPE = "https://www.googleapis.com/auth/admin.directory.user.readonly"
_ctx = ssl.create_default_context()


def _b64(d: bytes) -> str:
    return base64.urlsafe_b64encode(d).rstrip(b"=").decode()


def _dwd_token(scope: str, subject: str) -> str:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    sa = json.load(open(SA_KEY))
    now = int(time.time())
    header = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    payload = _b64(json.dumps({"iss": sa["client_email"], "scope": scope, "sub": subject,
                               "aud": "https://oauth2.googleapis.com/token",
                               "iat": now, "exp": now + 3600}).encode())
    pk = serialization.load_pem_private_key(sa["private_key"].encode(), password=None)
    sig = pk.sign(f"{header}.{payload}".encode(), padding.PKCS1v15(), hashes.SHA256())
    body = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": f"{header}.{payload}.{_b64(sig)}"}).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=body)
    return json.loads(urllib.request.urlopen(req, context=_ctx, timeout=15).read())["access_token"]


def get_user_id(email: str) -> str | None:
    """Email -> Google user id via the Directory API."""
    tok = _dwd_token(DIR_SCOPE, SUPER_ADMIN)
    url = f"https://admin.googleapis.com/admin/directory/v1/users/{urllib.parse.quote(email)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
    try:
        return json.loads(urllib.request.urlopen(req, context=_ctx, timeout=15).read()).get("id")
    except urllib.error.HTTPError as e:
        print(f"[directory] {email}: {e.code} {e.read().decode()[:160]}", flush=True)
        return None


def list_users(max_results: int = 500) -> list[dict]:
    """List active org users [{email, id, name}]."""
    tok = _dwd_token(DIR_SCOPE, SUPER_ADMIN)
    out, page = [], ""
    while True:
        q = f"customer=my_customer&maxResults=200&query=isSuspended=false{('&pageToken=' + page) if page else ''}"
        url = f"https://admin.googleapis.com/admin/directory/v1/users?{q}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
        try:
            data = json.loads(urllib.request.urlopen(req, context=_ctx, timeout=20).read())
        except urllib.error.HTTPError as e:
            print(f"[directory] list: {e.code} {e.read().decode()[:160]}", flush=True)
            break
        for u in data.get("users", []):
            out.append({"email": u.get("primaryEmail"), "id": u.get("id"),
                        "name": (u.get("name") or {}).get("fullName")})
        page = data.get("nextPageToken", "")
        if not page or len(out) >= max_results:
            break
    return out


def find_dm_space(user_id: str) -> str | None:
    """Find the bot's DM space with a user id (Chat app auth)."""
    tok = chat_media.get_chat_token()
    if not tok:
        return None
    url = f"https://chat.googleapis.com/v1/spaces:findDirectMessage?name=users/{user_id}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
    try:
        return json.loads(urllib.request.urlopen(req, context=_ctx, timeout=15).read()).get("name")
    except urllib.error.HTTPError as e:
        print(f"[directory] findDM {user_id}: {e.code} {e.read().decode()[:160]}", flush=True)
        return None


def create_dm_space(user_id: str) -> str | None:
    """Create (or return) a DM space between the bot and an org user via
    spaces.setup — lets the bot START a conversation without the user messaging
    first (the 'cold DM' case). Only works for users in the org's Workspace;
    returns None on failure (logged). Idempotent: if a DM already exists, Chat
    returns it instead of erroring."""
    tok = chat_media.get_chat_token()
    if not tok:
        return None
    body = json.dumps({
        "space": {"spaceType": "DIRECT_MESSAGE", "singleUserBotDm": True},
        "memberships": [{"member": {"name": f"users/{user_id}", "type": "HUMAN"}}],
    }).encode()
    req = urllib.request.Request(
        "https://chat.googleapis.com/v1/spaces:setup", data=body, method="POST",
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(req, context=_ctx, timeout=15).read()).get("name")
    except urllib.error.HTTPError as e:
        print(f"[directory] setupDM {user_id}: {e.code} {e.read().decode()[:200]}", flush=True)
        return None
    except Exception as e:
        print(f"[directory] setupDM {user_id}: {e}", flush=True)
        return None


def ensure_dm_space(user_id: str) -> str | None:
    """The bot's DM space with a user — existing if there is one, otherwise create
    one (cold DM). This is what lets the bot reach anyone in the org proactively."""
    return find_dm_space(user_id) or create_dm_space(user_id)


def _match_person(query: str, users: list[dict]) -> tuple[dict | None, list[dict]]:
    """Resolve a free-text name/email against a user list. Pure (no I/O) so it is
    unit-testable. Returns (match, candidates): match is the single resolved user or
    None; candidates is the shortlist (used to disambiguate when 0 or >1 match).

    Order: exact email > exact full name > all-token substring match on name+email.
    """
    q = (query or "").strip().lower()
    if not q:
        return None, []
    for u in users:
        if (u.get("email") or "").lower() == q:
            return u, [u]
    exact = [u for u in users if (u.get("name") or "").lower() == q]
    if len(exact) == 1:
        return exact[0], exact
    if exact:
        return None, exact
    toks = q.split()
    subs = [u for u in users
            if all(t in f"{(u.get('name') or '')} {(u.get('email') or '')}".lower() for t in toks)]
    if len(subs) == 1:
        return subs[0], subs
    return None, subs  # 0 -> not found, >1 -> ambiguous


def resolve_person(query: str) -> tuple[dict | None, list[dict]]:
    """Look up a person by name/email across the org directory."""
    return _match_person(query, list_users())


def message_person(query: str, text: str, register_admin: bool = False) -> dict:
    """Resolve a name/email to a directory user and proactively DM them. Returns a
    result dict: ok+matched_name on success, or error in {ambiguous, not_found}."""
    match, candidates = resolve_person(query)
    if match:
        res = dm_email(match["email"], text, register_admin=register_admin)
        res["matched_name"] = match.get("name")
        return res
    if candidates:
        return {"ok": False, "error": "ambiguous", "query": query,
                "candidates": [{"name": c.get("name"), "email": c.get("email")} for c in candidates[:6]]}
    return {"ok": False, "error": "not_found", "query": query}


def dm_email(email: str, text: str, register_admin: bool = False) -> dict:
    """Proactively DM a user by email. Optionally register their DM space so
    Cloud Run digests can reach them later."""
    uid = get_user_id(email)
    if not uid:
        return {"ok": False, "email": email, "error": "user not found in directory"}
    space = ensure_dm_space(uid)  # find existing, else create one (cold DM)
    if not space:
        return {"ok": False, "email": email,
                "error": "couldn't open a DM (user not in org Workspace, or app not available to them)"}
    ok = chat_media.post_to_space(space, text)
    if ok and register_admin:
        try:
            cid = email.lower().replace("/", "_")
            payload = {"email": email.lower(), "space": space}
            store.create("admin_dms", payload, doc_id=cid) if not store.get("admin_dms", cid) \
                else store.patch("admin_dms", cid, payload)
        except Exception as e:
            print(f"[directory] register {email}: {e}", flush=True)
    return {"ok": ok, "email": email, "space": space}
