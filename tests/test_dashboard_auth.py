"""Tests for dashboard token auth (WORK.md: 'Dashboard auth').

Run: `py -m unittest tests.test_dashboard_auth` from the repo root.

OPS_DASHBOARD_TOKEN gates the operational dashboard views (/, /dashboard, /tasks,
/alerts, /api/dashboard, /rooms/*). When the env var is unset the views stay open;
when set, a request must present the token via ?token= or the X-Ops-Token header.
"""
import os
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from app.server import OpsHandler, dashboard_auth_ok

TOKEN_ENV = "OPS_DASHBOARD_TOKEN"


class DashboardAuthLogicTests(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.get(TOKEN_ENV)

    def tearDown(self):
        if self._saved is None:
            os.environ.pop(TOKEN_ENV, None)
        else:
            os.environ[TOKEN_ENV] = self._saved

    def test_open_when_token_unset(self):
        os.environ.pop(TOKEN_ENV, None)
        self.assertTrue(dashboard_auth_ok(None, None))
        self.assertTrue(dashboard_auth_ok("anything", None))

    def test_open_when_token_empty(self):
        os.environ[TOKEN_ENV] = ""
        self.assertTrue(dashboard_auth_ok(None, None))

    def test_header_token_accepted(self):
        os.environ[TOKEN_ENV] = "s3cret"
        self.assertTrue(dashboard_auth_ok("s3cret", None))

    def test_query_token_accepted(self):
        os.environ[TOKEN_ENV] = "s3cret"
        self.assertTrue(dashboard_auth_ok(None, "s3cret"))

    def test_missing_token_rejected(self):
        os.environ[TOKEN_ENV] = "s3cret"
        self.assertFalse(dashboard_auth_ok(None, None))

    def test_wrong_token_rejected(self):
        os.environ[TOKEN_ENV] = "s3cret"
        self.assertFalse(dashboard_auth_ok("nope", "nope"))


class DashboardAuthGateTests(unittest.TestCase):
    """End-to-end gate check. Only exercises paths that short-circuit before any
    Firestore call: 401 rejections (auth fails first) and the open /healthz probe."""

    @classmethod
    def setUpClass(cls):
        cls._saved = os.environ.get(TOKEN_ENV)
        os.environ[TOKEN_ENV] = "gate-token"
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), OpsHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        if cls._saved is None:
            os.environ.pop(TOKEN_ENV, None)
        else:
            os.environ[TOKEN_ENV] = cls._saved

    def _status(self, path, headers=None):
        url = f"http://127.0.0.1:{self.port}{path}"
        req = urllib.request.Request(url, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code

    def test_healthz_open_without_token(self):
        self.assertEqual(self._status("/healthz"), 200)

    def test_dashboard_requires_token(self):
        self.assertEqual(self._status("/dashboard"), 401)

    def test_tasks_requires_token(self):
        self.assertEqual(self._status("/tasks"), 401)

    def test_alerts_requires_token(self):
        self.assertEqual(self._status("/alerts"), 401)

    def test_rooms_requires_token(self):
        self.assertEqual(self._status("/rooms/4%20Channelview"), 401)

    def test_wrong_query_token_rejected(self):
        self.assertEqual(self._status("/dashboard?token=wrong"), 401)


if __name__ == "__main__":
    unittest.main()
