"""Tests for Claude REST retry/backoff (WORK.md: 'Brain API resilience').

Run: `py -m unittest tests.test_brain_resilience` from the repo root.

A transient API error (rate limit, overloaded, gateway, network blip, timeout)
must be retried with backoff so a user's reply isn't silently dropped; a real
client error (400/401) must fail fast. We patch `brain._post_once` (so no network
or API key is needed) and `brain._sleep` (so the backoff doesn't actually wait).
"""
import email.message
import socket
import unittest
import urllib.error

from app import brain


def _http_error(code, retry_after=None):
    hdrs = email.message.Message()
    if retry_after is not None:
        hdrs["Retry-After"] = str(retry_after)
    # fp=None is fine: the retry path never reads the body.
    return urllib.error.HTTPError("https://api.anthropic.com/v1/messages",
                                  code, "err", hdrs, None)


class _Patch:
    """Patch _post_once with a scripted sequence and capture backoff sleeps."""

    def __init__(self, sequence, max_attempts=3):
        self.sequence = list(sequence)
        self.calls = 0
        self.sleeps = []
        self.max_attempts = max_attempts

    def __enter__(self):
        self._orig = (brain._post_once, brain._sleep, brain.BRAIN_MAX_ATTEMPTS,
                      brain.BRAIN_BACKOFF_BASE)
        brain.BRAIN_MAX_ATTEMPTS = self.max_attempts
        brain.BRAIN_BACKOFF_BASE = 1.0

        def fake_post(_payload):
            item = self.sequence[self.calls]
            self.calls += 1
            if isinstance(item, Exception):
                raise item
            return item

        brain._post_once = fake_post
        brain._sleep = lambda d: self.sleeps.append(d)
        return self

    def __exit__(self, *a):
        (brain._post_once, brain._sleep, brain.BRAIN_MAX_ATTEMPTS,
         brain.BRAIN_BACKOFF_BASE) = self._orig


OK = {"stop_reason": "end_turn", "content": [{"type": "text", "text": "hi"}]}


class RetryTests(unittest.TestCase):
    def test_success_first_try_no_sleep(self):
        with _Patch([OK]) as p:
            self.assertEqual(brain._call_claude([], None), OK)
            self.assertEqual(p.calls, 1)
            self.assertEqual(p.sleeps, [])

    def test_retries_transient_then_succeeds(self):
        with _Patch([_http_error(503), _http_error(529), OK]) as p:
            self.assertEqual(brain._call_claude([], None), OK)
            self.assertEqual(p.calls, 3)
            self.assertEqual(p.sleeps, [1.0, 2.0])   # exponential backoff

    def test_exhausts_and_raises_on_persistent_transient(self):
        with _Patch([_http_error(503), _http_error(503), _http_error(503)]) as p:
            with self.assertRaises(urllib.error.HTTPError):
                brain._call_claude([], None)
            self.assertEqual(p.calls, 3)
            self.assertEqual(len(p.sleeps), 2)       # slept between, not after last

    def test_client_error_fails_fast(self):
        for code in (400, 401, 403, 404):
            with _Patch([_http_error(code), OK]) as p:
                with self.assertRaises(urllib.error.HTTPError):
                    brain._call_claude([], None)
                self.assertEqual(p.calls, 1, code)   # no retry
                self.assertEqual(p.sleeps, [], code)

    def test_retries_network_errors(self):
        with _Patch([urllib.error.URLError("conn reset"), OK]) as p:
            self.assertEqual(brain._call_claude([], None), OK)
            self.assertEqual(p.calls, 2)

    def test_retries_timeout(self):
        with _Patch([socket.timeout("timed out"), OK]) as p:
            self.assertEqual(brain._call_claude([], None), OK)
            self.assertEqual(p.calls, 2)

    def test_honors_retry_after_header(self):
        with _Patch([_http_error(429, retry_after=7), OK]) as p:
            self.assertEqual(brain._call_claude([], None), OK)
            self.assertEqual(p.sleeps, [7.0])        # header overrides backoff

    def test_backoff_capped(self):
        orig_max = brain.BRAIN_BACKOFF_MAX
        brain.BRAIN_BACKOFF_MAX = 5
        try:
            with _Patch([_http_error(429, retry_after=999), OK]) as p:
                brain._call_claude([], None)
                self.assertEqual(p.sleeps, [5])      # capped at BRAIN_BACKOFF_MAX
        finally:
            brain.BRAIN_BACKOFF_MAX = orig_max


if __name__ == "__main__":
    unittest.main()
