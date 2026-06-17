"""Verify the Google Chat webhook bearer token — pure stdlib, no `cryptography`.

Google Chat signs every `/chat/events` request with a JWT in the
`Authorization: Bearer <jwt>` header, issued by `chat@system.gserviceaccount.com`
(RS256) with `aud` = the GCP project number. Without verification, anyone who
learns the URL can POST events and drive the bot. We verify:

  * the RS256 signature, against Google's published x509 certs (cached ~1h),
  * `iss` == chat@system.gserviceaccount.com,
  * `aud` == OPS_CHAT_AUDIENCE (when set), and
  * `exp` (with a small clock-skew leeway).

`cryptography` doesn't build on Python 3.14 (docs/LIMITATIONS.md #1), so RSA is
done with stdlib modular arithmetic (`pow`) + `hashlib`, and the x509 public key
is pulled out with a tiny ASN.1/DER walker. base64url handling mirrors the JWT
*signing* pattern in `app/chat_media._sa_key_token`.

Gated by `OPS_VERIFY_CHAT_TOKEN=1`: when off, `verify_request` allows everything
so enabling the bot can't dark the live webhook before the audience is set.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import ssl
import time
import urllib.request

CHAT_ISSUER = "chat@system.gserviceaccount.com"
CERT_URL = ("https://www.googleapis.com/service_accounts/v1/metadata/x509/"
            "chat@system.gserviceaccount.com")
LEEWAY_SECONDS = 60
CERT_TTL_SECONDS = 3600

# DER-encoded DigestInfo prefix for SHA-256, per PKCS#1 v1.5 (RFC 8017 §9.2).
_SHA256_DIGESTINFO = bytes.fromhex("3031300d060960864801650304020105000420")

_ctx = ssl.create_default_context()
_cert_cache: dict = {"exp": 0, "keys": {}}  # kid -> (n, e)


def enabled() -> bool:
    return os.getenv("OPS_VERIFY_CHAT_TOKEN", "").lower() in {"1", "true", "yes"}


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


# --- minimal ASN.1 / DER --------------------------------------------------
def _read_len(data: bytes, i: int) -> tuple[int, int]:
    b = data[i]; i += 1
    if b < 0x80:
        return b, i
    n = b & 0x7F
    return int.from_bytes(data[i:i + n], "big"), i + n


def _read_tlv(data: bytes, i: int) -> tuple[int, bytes, int]:
    """Return (tag, value_bytes, next_offset) for the TLV at offset i."""
    tag = data[i]; i += 1
    length, i = _read_len(data, i)
    return tag, data[i:i + length], i + length


def _pem_to_der(pem: str) -> bytes:
    body = "".join(line for line in pem.strip().splitlines()
                   if "-----" not in line)
    return base64.b64decode(body)


def _rsa_pubkey_from_spki_der(spki: bytes) -> tuple[int, int] | None:
    """Extract (modulus, exponent) from a SubjectPublicKeyInfo SEQUENCE value:
    SEQUENCE { AlgorithmIdentifier SEQUENCE, subjectPublicKey BIT STRING }."""
    try:
        t1, _alg, k = _read_tlv(spki, 0)          # AlgorithmIdentifier
        if t1 != 0x30:
            return None
        t2, bitstr, _ = _read_tlv(spki, k)        # BIT STRING
        if t2 != 0x03:
            return None
        rsa_der = bitstr[1:]                       # drop "unused bits" byte
        tr, rsa_val, _ = _read_tlv(rsa_der, 0)     # RSAPublicKey SEQUENCE
        if tr != 0x30:
            return None
        tn, n_b, m = _read_tlv(rsa_val, 0)         # modulus INTEGER
        te, e_b, _ = _read_tlv(rsa_val, m)         # exponent INTEGER
        if tn != 0x02 or te != 0x02:
            return None
        return int.from_bytes(n_b, "big"), int.from_bytes(e_b, "big")
    except (IndexError, ValueError):
        return None


def _rsa_pubkey_from_cert(pem: str) -> tuple[int, int] | None:
    """Pull the RSA public key out of an x509 certificate PEM, stdlib-only."""
    der = _pem_to_der(pem)
    tag, cert_val, _ = _read_tlv(der, 0)           # Certificate SEQUENCE
    if tag != 0x30:
        return None
    tag, tbs_val, _ = _read_tlv(cert_val, 0)       # tbsCertificate SEQUENCE
    if tag != 0x30:
        return None
    # The SubjectPublicKeyInfo is the first child SEQUENCE shaped {SEQ, BITSTRING}
    # whose BIT STRING holds an RSAPublicKey — issuer/subject/validity don't match.
    i = 0
    while i < len(tbs_val):
        t, v, j = _read_tlv(tbs_val, i)
        if t == 0x30:
            ne = _rsa_pubkey_from_spki_der(v)
            if ne:
                return ne
        i = j
    return None


# --- Google cert cache ----------------------------------------------------
def _fetch_cert_pems() -> dict[str, str]:
    """Fetch {kid: pem} from Google's x509 endpoint. Isolated for testability."""
    req = urllib.request.Request(CERT_URL, headers={"User-Agent": "nf-ops-bot"})
    return json.loads(urllib.request.urlopen(req, context=_ctx, timeout=10).read())


def google_signing_keys(now: int | None = None, force: bool = False) -> dict[str, tuple[int, int]]:
    """{kid: (n, e)} for Google's Chat signer, cached for CERT_TTL_SECONDS."""
    now = now if now is not None else int(time.time())
    if not force and _cert_cache["keys"] and now < _cert_cache["exp"]:
        return _cert_cache["keys"]
    keys: dict[str, tuple[int, int]] = {}
    try:
        for kid, pem in _fetch_cert_pems().items():
            ne = _rsa_pubkey_from_cert(pem)
            if ne:
                keys[kid] = ne
    except Exception as e:
        print(f"[chat_auth] cert fetch failed: {e}", flush=True)
        return _cert_cache["keys"]  # keep any stale keys rather than failing closed blindly
    _cert_cache["keys"] = keys
    _cert_cache["exp"] = now + CERT_TTL_SECONDS
    return keys


# --- RS256 verification ---------------------------------------------------
def _verify_rs256(message: bytes, sig: bytes, n: int, e: int) -> bool:
    """RSASSA-PKCS1-v1_5 verify with SHA-256, using only big-int math."""
    k = (n.bit_length() + 7) // 8
    if len(sig) > k:
        return False
    s = int.from_bytes(sig, "big")
    if s >= n:
        return False
    em = pow(s, e, n).to_bytes(k, "big")
    digest = hashlib.sha256(message).digest()
    t = _SHA256_DIGESTINFO + digest
    ps_len = k - len(t) - 3
    if ps_len < 8:
        return False
    expected = b"\x00\x01" + b"\xff" * ps_len + b"\x00" + t
    return hmac.compare_digest(em, expected)


def verify_token(token: str, audience: str = "", now: int | None = None) -> tuple[bool, str]:
    """Verify a Chat JWT. Returns (ok, reason)."""
    now = now if now is not None else int(time.time())
    parts = (token or "").split(".")
    if len(parts) != 3:
        return False, "malformed jwt"
    h_b64, p_b64, s_b64 = parts
    try:
        header = json.loads(_b64url_decode(h_b64))
        payload = json.loads(_b64url_decode(p_b64))
        sig = _b64url_decode(s_b64)
    except (ValueError, json.JSONDecodeError):
        return False, "bad encoding"
    if header.get("alg") != "RS256":
        return False, "alg not RS256"
    if payload.get("iss") != CHAT_ISSUER:
        return False, "bad iss"
    if audience and str(payload.get("aud")) != str(audience):
        return False, "bad aud"
    exp = payload.get("exp")
    if not isinstance(exp, (int, float)) or now > exp + LEEWAY_SECONDS:
        return False, "expired"
    kid = header.get("kid")
    keys = google_signing_keys(now=now)
    ne = keys.get(kid) or google_signing_keys(now=now, force=True).get(kid)
    if not ne:
        return False, "unknown kid"
    if not _verify_rs256(f"{h_b64}.{p_b64}".encode(), sig, ne[0], ne[1]):
        return False, "bad signature"
    return True, "ok"


def verify_request(headers, now: int | None = None) -> tuple[bool, str]:
    """Verify the Authorization header of a /chat/events request.

    Returns (ok, reason). When verification is disabled, always allows so the
    live bot can't be darked before OPS_CHAT_AUDIENCE is configured.
    """
    if not enabled():
        return True, "verification disabled"
    auth = headers.get("Authorization", "") or headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        return False, "missing bearer token"
    audience = os.getenv("OPS_CHAT_AUDIENCE", "")
    return verify_token(auth[len("Bearer "):].strip(), audience, now)
