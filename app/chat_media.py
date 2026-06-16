"""Download Google Chat message attachments (e.g. photos of BOLs) so they can
be analyzed by app/vision.py.

Auth is dependency-free and key-free in Cloud Run:
  - Cloud Run: the runtime service account calls IAM `generateAccessToken` to
    mint a chat.bot token for `chat-bot-poster` (needs roles/iam.serviceAccount
    TokenCreator, granted on that SA). No private key in the container, and the
    slim image needs no `cryptography`.
  - Local: falls back to signing a JWT from OPS_SA_KEY (/tmp/sa-key.json).
"""
from __future__ import annotations

import json
import os
import ssl
import time
import urllib.request
import urllib.error

CHAT_SA = os.getenv("OPS_CHAT_SA", "chat-bot-poster@nfchatbot-498419.iam.gserviceaccount.com")
SA_KEY = os.getenv("OPS_SA_KEY", "/tmp/sa-key.json")
SCOPE = "https://www.googleapis.com/auth/chat.bot"
_ctx = ssl.create_default_context()
_cache: dict = {"token": None, "exp": 0}


def _metadata_token() -> str | None:
    url = ("http://metadata.google.internal/computeMetadata/v1/instance/"
           "service-accounts/default/token")
    try:
        req = urllib.request.Request(url, headers={"Metadata-Flavor": "Google"})
        return json.loads(urllib.request.urlopen(req, timeout=3).read())["access_token"]
    except Exception:
        return None


def _impersonated_token() -> str | None:
    """Cloud Run path: mint a chat.bot token for CHAT_SA via IAM generateAccessToken."""
    base = _metadata_token()
    if not base:
        return None
    url = (f"https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/"
           f"{CHAT_SA}:generateAccessToken")
    body = json.dumps({"scope": [SCOPE]}).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Authorization": f"Bearer {base}", "Content-Type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(req, context=_ctx, timeout=10).read())["accessToken"]
    except Exception:
        return None


def _sa_key_token() -> str | None:
    """Local path: sign a JWT from the SA key (needs `cryptography`, dev-only)."""
    if not os.path.exists(SA_KEY):
        return None
    import base64
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    def b64(d: bytes) -> str:
        return base64.urlsafe_b64encode(d).rstrip(b"=").decode()

    sa = json.load(open(SA_KEY))
    now = int(time.time())
    header = b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    payload = b64(json.dumps({"iss": sa["client_email"], "scope": SCOPE,
                              "aud": "https://oauth2.googleapis.com/token",
                              "iat": now, "exp": now + 3600}).encode())
    pk = serialization.load_pem_private_key(sa["private_key"].encode(), password=None)
    sig = pk.sign(f"{header}.{payload}".encode(), padding.PKCS1v15(), hashes.SHA256())
    import urllib.parse
    body = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": f"{header}.{payload}.{b64(sig)}"}).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=body)
    return json.loads(urllib.request.urlopen(req, context=_ctx, timeout=10).read())["access_token"]


def get_chat_token() -> str | None:
    if _cache["token"] and time.time() < _cache["exp"] - 60:
        return _cache["token"]
    tok = _impersonated_token() or _sa_key_token()
    if tok:
        _cache["token"], _cache["exp"] = tok, time.time() + 3000
    return tok


# Downloading user-uploaded attachments needs DELEGATED (user) auth — app auth
# is denied. We impersonate a member via chat.messages.readonly. In Cloud Run we
# sign the JWT with IAM (no private key / no cryptography needed); locally we sign
# with the SA key.
DL_SUBJECT = os.getenv("OPS_DOWNLOAD_SUBJECT", "aayan@khawarsons.com")
DL_SCOPE = "https://www.googleapis.com/auth/chat.messages.readonly"
_dl_cache: dict = {"token": None, "exp": 0}


def _exchange_jwt(signed_jwt: str) -> str | None:
    import urllib.parse
    data = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": signed_jwt}).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data)
    try:
        return json.loads(urllib.request.urlopen(req, context=_ctx, timeout=10).read())["access_token"]
    except Exception as e:
        print(f"[dl] exchange: {e}", flush=True)
        return None


def _signjwt_dwd(scope: str, subject: str) -> str | None:
    """Cloud Run: IAM signs a delegated JWT as CHAT_SA (needs tokenCreator)."""
    base = _metadata_token()
    if not base:
        return None
    now = int(time.time())
    claims = {"iss": CHAT_SA, "sub": subject, "scope": scope,
              "aud": "https://oauth2.googleapis.com/token", "iat": now, "exp": now + 3600}
    url = f"https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/{CHAT_SA}:signJwt"
    body = json.dumps({"payload": json.dumps(claims)}).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Authorization": f"Bearer {base}", "Content-Type": "application/json"})
    try:
        signed = json.loads(urllib.request.urlopen(req, context=_ctx, timeout=10).read())["signedJwt"]
    except Exception as e:
        print(f"[dl] signJwt: {e}", flush=True)
        return None
    return _exchange_jwt(signed)


def _sa_key_dwd(scope: str, subject: str) -> str | None:
    """Local: sign the delegated JWT with the SA key."""
    if not os.path.exists(SA_KEY):
        return None
    import base64
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    def b64(d): return base64.urlsafe_b64encode(d).rstrip(b"=").decode()
    sa = json.load(open(SA_KEY))
    now = int(time.time())
    header = b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    payload = b64(json.dumps({"iss": sa["client_email"], "sub": subject, "scope": scope,
                              "aud": "https://oauth2.googleapis.com/token",
                              "iat": now, "exp": now + 3600}).encode())
    pk = serialization.load_pem_private_key(sa["private_key"].encode(), password=None)
    sig = pk.sign(f"{header}.{payload}".encode(), padding.PKCS1v15(), hashes.SHA256())
    return _exchange_jwt(f"{header}.{payload}.{b64(sig)}")


def get_download_token() -> str | None:
    if _dl_cache["token"] and time.time() < _dl_cache["exp"] - 60:
        return _dl_cache["token"]
    print(f"[dl] start: SA_KEY={SA_KEY} exists={os.path.exists(SA_KEY)}", flush=True)
    tok = _signjwt_dwd(DL_SCOPE, DL_SUBJECT)
    print(f"[dl] signjwt -> {'TOKEN' if tok else 'None'}", flush=True)
    if not tok:
        try:
            tok = _sa_key_dwd(DL_SCOPE, DL_SUBJECT)
        except Exception as e:
            print(f"[dl] sakey EXC: {e}", flush=True)
            tok = None
        print(f"[dl] sakey -> {'TOKEN' if tok else 'None'}", flush=True)
    if tok:
        _dl_cache.update(token=tok, exp=time.time() + 3000)
    return tok


def download_attachment(resource_name: str) -> bytes | None:
    """Fetch raw bytes for a Chat attachment by its attachmentDataRef.resourceName."""
    tok = get_download_token()
    if not tok or not resource_name:
        return None
    rn = resource_name.lstrip("/")
    url = f"https://chat.googleapis.com/v1/media/{rn}?alt=media"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
    try:
        return urllib.request.urlopen(req, context=_ctx, timeout=30).read()
    except urllib.error.HTTPError as e:
        print(f"[attachment] download {e.code}: {e.read().decode()[:200]}", flush=True)
        return None
    except Exception as e:
        print(f"[attachment] download error: {e}", flush=True)
        return None


def post_to_space(space: str, text: str) -> bool:
    """Proactively post a message to a Chat space (for digests/alerts)."""
    tok = get_chat_token()
    if not tok or not space or not text:
        return False
    url = f"https://chat.googleapis.com/v1/{space}/messages"
    body = json.dumps({"text": text[:3900]}).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, context=_ctx, timeout=20).read()
        return True
    except Exception as e:
        print(f"[post] {space} error: {e}", flush=True)
        return False


def image_attachments(message_obj: dict) -> list[dict]:
    """Return [{resource_name, content_type, name}] for image attachments on a Chat message."""
    out = []
    for a in (message_obj.get("attachment") or message_obj.get("attachments") or []):
        if not isinstance(a, dict):
            continue
        ctype = a.get("contentType") or a.get("content_type") or ""
        ref = (a.get("attachmentDataRef") or {}).get("resourceName") or a.get("resourceName")
        if ctype.startswith("image/") and ref:
            out.append({"resource_name": ref, "content_type": ctype,
                        "name": a.get("contentName") or a.get("name") or "image"})
    return out
