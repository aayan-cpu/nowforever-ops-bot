"""Tests for Google Chat webhook token verification (WORK.md: 'Webhook bearer-token verification').

Run: `py -m unittest tests.test_chat_auth` from the repo root.

Everything is stdlib: we generate a throwaway RSA keypair (deterministic
Miller-Rabin), DER-encode a minimal x509 cert from it, sign a JWT, and check
that app.chat_auth verifies the good case and rejects every tampered one — all
without `cryptography` or network.
"""
import base64
import hashlib
import json
import math
import random
import unittest

from app import chat_auth


# --- tiny stdlib RSA keygen + signer + DER encoder (test-side only) -------
def _is_prime(n: int) -> bool:
    if n < 2:
        return False
    for p in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
        if n % p == 0:
            return n == p
    d, r = n - 1, 0
    while d % 2 == 0:
        d //= 2; r += 1
    rnd = random.Random(99)
    for _ in range(16):
        a = rnd.randrange(2, n - 1)
        x = pow(a, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(r - 1):
            x = x * x % n
            if x == n - 1:
                break
        else:
            return False
    return True


def _gen_prime(bits: int, rnd: random.Random) -> int:
    while True:
        c = rnd.getrandbits(bits) | (1 << (bits - 1)) | 1
        if _is_prime(c):
            return c


def _gen_rsa(bits=1024):
    rnd = random.Random(42)
    e = 65537
    while True:
        p, q = _gen_prime(bits // 2, rnd), _gen_prime(bits // 2, rnd)
        if p != q and math.gcd(e, (p - 1) * (q - 1)) == 1:
            n = p * q
            return n, e, pow(e, -1, (p - 1) * (q - 1))


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _sign_rs256(message: bytes, n: int, d: int) -> bytes:
    k = (n.bit_length() + 7) // 8
    t = chat_auth._SHA256_DIGESTINFO + hashlib.sha256(message).digest()
    em = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    return pow(int.from_bytes(em, "big"), d, n).to_bytes(k, "big")


def _der_len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(b)]) + b


def _tlv(tag: int, val: bytes) -> bytes:
    return bytes([tag]) + _der_len(len(val)) + val


def _uint(x: int) -> bytes:
    b = x.to_bytes((x.bit_length() + 7) // 8 or 1, "big")
    if b[0] & 0x80:
        b = b"\x00" + b
    return _tlv(0x02, b)


def _cert_pem(n: int, e: int) -> str:
    spki = _tlv(0x30, _tlv(0x30, _tlv(0x06, bytes.fromhex("2a864886f70d010101")) + _tlv(0x05, b""))
                + _tlv(0x03, b"\x00" + _tlv(0x30, _uint(n) + _uint(e))))
    algid = _tlv(0x30, _tlv(0x06, bytes.fromhex("2a864886f70d01010b")) + _tlv(0x05, b""))
    name, dummy = _tlv(0x30, b""), _uint(1)
    validity = _tlv(0x30, _tlv(0x17, b"000000000000Z") + _tlv(0x17, b"000000000000Z"))
    tbs = _tlv(0x30, dummy + dummy + algid + name + validity + name + spki)
    cert = _tlv(0x30, tbs + algid + _tlv(0x03, b"\x00"))
    return "-----BEGIN CERTIFICATE-----\n" + base64.encodebytes(cert).decode() + "-----END CERTIFICATE-----\n"


N, E, D = _gen_rsa()
NOW = 1_000_000
AUD = "123456789"


def _jwt(kid="kid1", iss=chat_auth.CHAT_ISSUER, aud=AUD, exp=NOW + 3600, alg="RS256"):
    header = _b64u(json.dumps({"alg": alg, "typ": "JWT", "kid": kid}).encode())
    payload = _b64u(json.dumps({"iss": iss, "aud": aud, "exp": exp}).encode())
    sig = _sign_rs256(f"{header}.{payload}".encode(), N, D)
    return f"{header}.{payload}.{_b64u(sig)}"


class _Keys:
    """Patch chat_auth's signing-key lookup to our test key."""
    def __enter__(self):
        self._orig = chat_auth.google_signing_keys
        chat_auth.google_signing_keys = lambda now=None, force=False: {"kid1": (N, E)}
        return self

    def __exit__(self, *a):
        chat_auth.google_signing_keys = self._orig


class RsaPrimitiveTests(unittest.TestCase):
    def test_verify_rs256_roundtrip(self):
        msg = b"hello.world"
        sig = _sign_rs256(msg, N, D)
        self.assertTrue(chat_auth._verify_rs256(msg, sig, N, E))
        self.assertFalse(chat_auth._verify_rs256(b"tampered", sig, N, E))

    def test_pubkey_extracted_from_cert(self):
        self.assertEqual(chat_auth._rsa_pubkey_from_cert(_cert_pem(N, E)), (N, E))


class VerifyTokenTests(unittest.TestCase):
    def test_valid_token(self):
        with _Keys():
            self.assertEqual(chat_auth.verify_token(_jwt(), AUD, now=NOW), (True, "ok"))

    def test_rejects_bad_audience(self):
        with _Keys():
            ok, why = chat_auth.verify_token(_jwt(aud="evil"), AUD, now=NOW)
            self.assertFalse(ok); self.assertEqual(why, "bad aud")

    def test_rejects_bad_issuer(self):
        with _Keys():
            ok, why = chat_auth.verify_token(_jwt(iss="attacker@evil.com"), AUD, now=NOW)
            self.assertFalse(ok); self.assertEqual(why, "bad iss")

    def test_rejects_expired(self):
        with _Keys():
            ok, why = chat_auth.verify_token(_jwt(exp=NOW - 1000), AUD, now=NOW)
            self.assertFalse(ok); self.assertEqual(why, "expired")

    def test_rejects_wrong_alg(self):
        with _Keys():
            ok, why = chat_auth.verify_token(_jwt(alg="none"), AUD, now=NOW)
            self.assertFalse(ok); self.assertEqual(why, "alg not RS256")

    def test_rejects_unknown_kid(self):
        with _Keys():
            ok, why = chat_auth.verify_token(_jwt(kid="other"), AUD, now=NOW)
            self.assertFalse(ok); self.assertEqual(why, "unknown kid")

    def test_rejects_tampered_signature(self):
        with _Keys():
            tok = _jwt()
            h, p, _s = tok.split(".")
            forged = f"{h}.{_b64u(json.dumps({'iss': chat_auth.CHAT_ISSUER, 'aud': AUD, 'exp': NOW + 9}).encode())}.{_s}"
            ok, why = chat_auth.verify_token(forged, AUD, now=NOW)
            self.assertFalse(ok); self.assertEqual(why, "bad signature")

    def test_malformed(self):
        self.assertEqual(chat_auth.verify_token("not-a-jwt", AUD, now=NOW)[0], False)

    def test_audience_skipped_when_unset(self):
        with _Keys():
            self.assertTrue(chat_auth.verify_token(_jwt(aud="anything"), "", now=NOW)[0])


class FullCertPathTests(unittest.TestCase):
    def test_keys_parsed_from_fetched_certs(self):
        orig_fetch = chat_auth._fetch_cert_pems
        chat_auth._cert_cache.update({"exp": 0, "keys": {}})
        chat_auth._fetch_cert_pems = lambda: {"kid1": _cert_pem(N, E)}
        try:
            self.assertEqual(chat_auth.verify_token(_jwt(), AUD, now=NOW), (True, "ok"))
        finally:
            chat_auth._fetch_cert_pems = orig_fetch
            chat_auth._cert_cache.update({"exp": 0, "keys": {}})


class VerifyRequestGatingTests(unittest.TestCase):
    def setUp(self):
        self._orig = chat_auth.enabled

    def tearDown(self):
        chat_auth.enabled = self._orig

    def test_disabled_allows_everything(self):
        chat_auth.enabled = lambda: False
        self.assertEqual(chat_auth.verify_request({}, now=NOW), (True, "verification disabled"))

    def test_enabled_requires_bearer(self):
        chat_auth.enabled = lambda: True
        ok, why = chat_auth.verify_request({}, now=NOW)
        self.assertFalse(ok); self.assertEqual(why, "missing bearer token")


if __name__ == "__main__":
    unittest.main()
