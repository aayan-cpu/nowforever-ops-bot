"""Firestore-backed persistence using the REST API (no client library).

Why REST: the google-cloud-firestore library needs gRPC, which doesn't build
on the dev machine's Python 3.14 (see docs/LIMITATIONS.md #1). The REST API
needs only the standard library plus a bearer token.

Auth:
- In Cloud Run, the token comes from the metadata server (the runtime service
  account, granted roles/datastore.user).
- Locally, it falls back to a service-account key at OPS_SA_KEY (default
  /tmp/sa-key.json), signing a JWT the same way scripts/chat_admin.py does.

Data model mirrors the old SQLite tables as two collections: `messages` and
`tasks`. Tasks keep a numeric id (doc id) via an atomic counter so the
"close task 170" style commands keep working. Aggregations are done in Python
(data volume is small), since Firestore can't GROUP BY server-side.
"""
from __future__ import annotations

import json
import os
import ssl
import time
import urllib.request
import urllib.parse
import urllib.error

PROJECT = os.getenv("OPS_GCP_PROJECT", "nfchatbot-498419")
DB = os.getenv("OPS_FIRESTORE_DB", "(default)")
SA_KEY = os.getenv("OPS_SA_KEY", "/tmp/sa-key.json")
SCOPE = "https://www.googleapis.com/auth/datastore"
BASE = f"https://firestore.googleapis.com/v1/projects/{PROJECT}/databases/{DB}/documents"

_ctx = ssl.create_default_context()
_token_cache: dict = {"token": None, "exp": 0}


# ---------------------------------------------------------------- auth
def _metadata_token() -> tuple[str, int] | None:
    url = ("http://metadata.google.internal/computeMetadata/v1/instance/"
           "service-accounts/default/token")
    req = urllib.request.Request(url, headers={"Metadata-Flavor": "Google"})
    try:
        data = json.loads(urllib.request.urlopen(req, timeout=2).read())
        return data["access_token"], int(time.time()) + int(data.get("expires_in", 3000))
    except Exception:
        return None


def _sa_token() -> tuple[str, int]:
    import base64
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    def b64(d: bytes) -> str:
        return base64.urlsafe_b64encode(d).rstrip(b"=").decode()

    sa = json.load(open(SA_KEY))
    now = int(time.time())
    header = b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    payload = b64(json.dumps({
        "iss": sa["client_email"], "scope": SCOPE,
        "aud": "https://oauth2.googleapis.com/token", "iat": now, "exp": now + 3600,
    }).encode())
    pk = serialization.load_pem_private_key(sa["private_key"].encode(), password=None)
    sig = pk.sign(f"{header}.{payload}".encode(), padding.PKCS1v15(), hashes.SHA256())
    body = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": f"{header}.{payload}.{b64(sig)}",
    }).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=body)
    data = json.loads(urllib.request.urlopen(req, context=_ctx).read())
    return data["access_token"], now + int(data.get("expires_in", 3000))


def _token() -> str:
    if _token_cache["token"] and time.time() < _token_cache["exp"] - 60:
        return _token_cache["token"]
    got = _metadata_token() or _sa_token()
    _token_cache["token"], _token_cache["exp"] = got
    return got[0]


# ------------------------------------------------------- value (de)serialize
def _to_val(v):
    if v is None:
        return {"nullValue": None}
    if isinstance(v, bool):
        return {"booleanValue": v}
    if isinstance(v, int):
        return {"integerValue": str(v)}
    if isinstance(v, float):
        return {"doubleValue": v}
    return {"stringValue": str(v)}


def _from_val(v: dict):
    if "nullValue" in v:
        return None
    if "booleanValue" in v:
        return v["booleanValue"]
    if "integerValue" in v:
        return int(v["integerValue"])
    if "doubleValue" in v:
        return float(v["doubleValue"])
    return v.get("stringValue", "")


def _to_fields(d: dict) -> dict:
    return {k: _to_val(v) for k, v in d.items()}


def _from_doc(doc: dict) -> dict:
    out = {k: _from_val(v) for k, v in (doc.get("fields") or {}).items()}
    out["_name"] = doc.get("name", "")
    out["id"] = out.get("id", doc.get("name", "").split("/")[-1])
    return out


def _req(method: str, path: str, body: dict | None = None, _tries: int = 4) -> dict:
    url = path if path.startswith("http") else f"{BASE}/{path}"
    data = json.dumps(body).encode() if body is not None else None
    last_err = None
    for attempt in range(_tries):
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {_token()}", "Content-Type": "application/json",
        })
        try:
            return json.loads(urllib.request.urlopen(req, context=_ctx, timeout=20).read() or b"{}")
        except urllib.error.HTTPError as e:
            # Retry transient server/rate-limit errors; fail fast on real 4xx.
            if e.code in (429, 500, 502, 503, 504) and attempt < _tries - 1:
                last_err = e; time.sleep(1.5 * (attempt + 1)); continue
            raise RuntimeError(f"Firestore {method} {path} -> {e.code}: {e.read().decode()}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = e
            if attempt < _tries - 1:
                time.sleep(1.5 * (attempt + 1)); continue
            raise RuntimeError(f"Firestore {method} {path} network error: {last_err}") from None


# Short-lived cache for full-collection reads. A single AI answer makes several
# report/tool calls that each scanned all messages; this fetches once per window.
# Writes bust the affected collection so the writer sees fresh data immediately.
_list_cache: dict = {}
_LIST_TTL = float(os.getenv("OPS_LIST_CACHE_TTL", "45"))


def _bust(collection: str) -> None:
    _list_cache.pop(collection, None)


# ------------------------------------------------------------- public API
def create(collection: str, data: dict, doc_id: str | None = None) -> dict:
    path = collection + (f"?documentId={urllib.parse.quote(doc_id)}" if doc_id else "")
    _bust(collection)
    return _from_doc(_req("POST", path, {"fields": _to_fields(data)}))


def get(collection: str, doc_id: str) -> dict | None:
    try:
        return _from_doc(_req("GET", f"{collection}/{urllib.parse.quote(str(doc_id))}"))
    except RuntimeError:
        return None


def patch(collection: str, doc_id: str, data: dict) -> dict:
    mask = "&".join(f"updateMask.fieldPaths={urllib.parse.quote(k)}" for k in data)
    path = f"{collection}/{urllib.parse.quote(str(doc_id))}?{mask}"
    _bust(collection)
    return _from_doc(_req("PATCH", path, {"fields": _to_fields(data)}))


def list_all(collection: str, use_cache: bool = True) -> list[dict]:
    if use_cache:
        hit = _list_cache.get(collection)
        if hit and (time.time() - hit[0]) < _LIST_TTL:
            return hit[1]
    out, page = [], ""
    while True:
        q = "pageSize=300" + (f"&pageToken={urllib.parse.quote(page)}" if page else "")
        res = _req("GET", f"{collection}?{q}")
        out.extend(_from_doc(d) for d in res.get("documents", []))
        page = res.get("nextPageToken", "")
        if not page:
            break
    _list_cache[collection] = (time.time(), out)
    return out


def find(collection: str, field: str, value, limit: int = 5) -> list[dict]:
    """Single-field equality query (uses Firestore's automatic index)."""
    body = {"structuredQuery": {
        "from": [{"collectionId": collection}],
        "where": {"fieldFilter": {
            "field": {"fieldPath": field}, "op": "EQUAL", "value": _to_val(value),
        }},
        "limit": limit,
    }}
    res = _req("POST", f"{BASE}:runQuery", body)
    rows = res if isinstance(res, list) else [res]
    return [_from_doc(r["document"]) for r in rows if isinstance(r, dict) and "document" in r]


def delete(collection: str, doc_id: str) -> None:
    _bust(collection)
    _req("DELETE", f"{collection}/{urllib.parse.quote(str(doc_id))}")


def next_seq(name: str) -> int:
    """Atomic incrementing counter stored at counters/<name>."""
    doc = f"projects/{PROJECT}/databases/{DB}/documents/counters/{name}"
    body = {"writes": [{
        "transform": {
            "document": doc,
            "fieldTransforms": [{"fieldPath": "value", "increment": {"integerValue": "1"}}],
        }
    }]}
    res = _req("POST", f"https://firestore.googleapis.com/v1/projects/{PROJECT}/databases/{DB}/documents:commit", body)
    return int(res["writeResults"][0]["transformResults"][0]["integerValue"])
