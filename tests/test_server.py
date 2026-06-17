"""Smoke tests for the HTTP routes in app.server.

Boots the real OpsHandler on an ephemeral port with the store faked out, then
makes live HTTP requests. Verifies the liveness probe never touches the store,
JSON/HTML routes return the right content types, and unknown paths 404.
"""
import json
import threading
import unittest
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer

from app import server
from app import store
from tests._fakestore import FakeStore
from tests.test_reports import MESSAGES, TASKS


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.headers.get("Content-Type", ""), r.read().decode("utf-8")


class TestServerRoutes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = FakeStore(messages=MESSAGES, tasks=TASKS).install()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.OpsHandler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.fake.restore()

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def test_healthz_ok_without_store(self):
        # Liveness must not touch the store — break it and confirm /healthz still works.
        orig = store.list_all
        store.list_all = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("store down"))
        try:
            status, ctype, body = _get(self.url("/healthz"))
        finally:
            store.list_all = orig
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"ok": True})

    def test_dashboard_json(self):
        status, ctype, body = _get(self.url("/dashboard?format=json"))
        self.assertEqual(status, 200)
        self.assertIn("application/json", ctype)
        data = json.loads(body)
        self.assertEqual(data["totals"]["messages"], 4)

    def test_dashboard_html(self):
        status, ctype, body = _get(self.url("/dashboard"))
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)
        self.assertIn("Ops Dashboard", body)

    def test_tasks_json(self):
        status, _, body = _get(self.url("/tasks?format=json"))
        self.assertEqual(status, 200)
        ids = [t["id"] for t in json.loads(body)]
        self.assertIn(10, ids)
        self.assertNotIn(12, ids)  # closed

    def test_alerts_json(self):
        status, _, body = _get(self.url("/alerts?format=json"))
        self.assertEqual(status, 200)
        rows = json.loads(body)
        self.assertTrue(all(m["priority"] == "high" for m in rows))

    def test_api_dashboard(self):
        status, ctype, body = _get(self.url("/api/dashboard"))
        self.assertEqual(status, 200)
        self.assertIn("application/json", ctype)

    def test_room_route(self):
        status, _, body = _get(self.url("/rooms/4%20Channelview?format=json"))
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["stats"]["messages"], 2)

    def test_unknown_path_404(self):
        try:
            _get(self.url("/no-such-route"))
            self.fail("expected 404")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 404)
            e.close()


if __name__ == "__main__":
    unittest.main()
