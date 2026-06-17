"""Unit tests for app.reports aggregations, backed by an in-memory fake store
(no Firestore). Covers the dashboard the AI brain grounds on, task/alert
listings, and task_action mutations.
"""
import unittest

from app import reports
from tests._fakestore import FakeStore


MESSAGES = [
    {"id": 1, "room_name": "4 Channelview", "priority": "high", "is_task": True,
     "attachment_count": 1, "categories": "fuel_delivery_issue", "seq": 5,
     "message": "need gas", "is_duplicate": False},
    {"id": 2, "room_name": "4 Channelview", "priority": "normal", "is_task": False,
     "attachment_count": 0, "categories": "general", "seq": 4,
     "message": "day report", "is_duplicate": False},
    {"id": 3, "room_name": "11 Windchase", "priority": "medium", "is_task": True,
     "attachment_count": 2, "categories": "admin_request_task;equipment_maintenance",
     "seq": 3, "message": "please fix printer", "is_duplicate": False},
    # a duplicate: counted in totals but excluded from live category/alert views.
    {"id": 4, "room_name": "11 Windchase", "priority": "high", "is_task": True,
     "attachment_count": 0, "categories": "fuel_delivery_issue", "seq": 2,
     "message": "need gas dup", "is_duplicate": True},
]

TASKS = [
    {"id": 10, "room_name": "4 Channelview", "priority": "high", "status": "open",
     "task_title": "need gas"},
    {"id": 11, "room_name": "11 Windchase", "priority": "medium", "status": "open",
     "task_title": "fix printer"},
    {"id": 12, "room_name": "4 Channelview", "priority": "normal", "status": "closed",
     "task_title": "old thing"},
]


class ReportsTestBase(unittest.TestCase):
    def setUp(self):
        self.fake = FakeStore(messages=MESSAGES, tasks=TASKS).install()
        self.addCleanup(self.fake.restore)


class TestDashboard(ReportsTestBase):
    def test_totals(self):
        d = reports.dashboard()
        self.assertEqual(d["totals"]["messages"], 4)
        self.assertEqual(d["totals"]["attachments"], 3)
        self.assertEqual(d["totals"]["duplicates"], 1)

    def test_priority_counts_sorted_high_first(self):
        d = reports.dashboard()
        self.assertEqual(d["priorities"][0]["priority"], "high")
        high = next(p for p in d["priorities"] if p["priority"] == "high")
        self.assertEqual(high["count"], 2)

    def test_categories_exclude_duplicates(self):
        # The duplicate (id 4) is fuel_delivery_issue; only id 1 should count it.
        d = reports.dashboard()
        self.assertEqual(d["categories"].get("fuel_delivery_issue"), 1)

    def test_top_rooms_aggregate(self):
        d = reports.dashboard()
        rooms = {r["room_name"]: r for r in d["top_rooms"]}
        self.assertEqual(rooms["4 Channelview"]["messages"], 2)
        self.assertEqual(rooms["4 Channelview"]["high"], 1)
        self.assertEqual(rooms["11 Windchase"]["attachments"], 2)


class TestTaskListings(ReportsTestBase):
    def test_open_tasks_excludes_closed(self):
        ids = [t["id"] for t in reports.open_tasks()]
        self.assertIn(10, ids)
        self.assertIn(11, ids)
        self.assertNotIn(12, ids)

    def test_open_tasks_priority_sorted(self):
        tasks = reports.open_tasks()
        self.assertEqual(tasks[0]["id"], 10)  # high before medium

    def test_open_tasks_room_filter(self):
        tasks = reports.open_tasks(room="windchase")
        self.assertEqual([t["id"] for t in tasks], [11])

    def test_closed_status_filter(self):
        tasks = reports.open_tasks(status="closed")
        self.assertEqual([t["id"] for t in tasks], [12])

    def test_high_priority_excludes_duplicates(self):
        rows = reports.high_priority()
        ids = [m["id"] for m in rows]
        self.assertIn(1, ids)
        self.assertNotIn(4, ids)  # high but duplicate


class TestRoomSummary(ReportsTestBase):
    def test_room_summary_stats(self):
        s = reports.room_summary(None, "channelview")
        self.assertEqual(s["stats"]["room_name"], "4 Channelview")
        self.assertEqual(s["stats"]["messages"], 2)
        self.assertEqual([t["id"] for t in s["open_tasks"]], [10])

    def test_unknown_room_has_no_stats(self):
        s = reports.room_summary(None, "nonexistent")
        self.assertIsNone(s["stats"])


class TestTaskAction(ReportsTestBase):
    def test_close(self):
        res = reports.task_action(None, 10, "close")
        self.assertTrue(res["ok"])
        self.assertEqual(self.fake.get("tasks", 10)["status"], "closed")

    def test_assign(self):
        res = reports.task_action(None, 11, "assign", assignee="Ali")
        self.assertTrue(res["ok"])
        t = self.fake.get("tasks", 11)
        self.assertEqual(t["assignee"], "Ali")
        self.assertEqual(t["status"], "assigned")

    def test_reopen(self):
        reports.task_action(None, 12, "open")
        self.assertEqual(self.fake.get("tasks", 12)["status"], "open")

    def test_unknown_action(self):
        res = reports.task_action(None, 10, "frobnicate")
        self.assertFalse(res["ok"])

    def test_missing_task(self):
        res = reports.task_action(None, 9999, "close")
        self.assertFalse(res["ok"])


class TestRenderers(ReportsTestBase):
    def test_text_report_contains_headers(self):
        out = reports.render_text_report()
        self.assertIn("Now & Forever Ops Dashboard", out)
        self.assertIn("Messages parsed: 4", out)

    def test_dashboard_html_renders(self):
        html = reports.render_dashboard_html()
        self.assertIn("<h1>", html)
        self.assertIn("4 Channelview", html)

    def test_tasks_html_renders(self):
        self.assertIn("Open Tasks", reports.render_tasks_html())


if __name__ == "__main__":
    unittest.main()
