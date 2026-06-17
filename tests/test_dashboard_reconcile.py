"""Tests for the dashboard's fuel-reconciliation + store-scorecard surfacing
in app.reports (store_scorecards, fuel_discrepancies, and their HTML render)."""
import unittest

from app import reports
from tests._fakestore import FakeStore


MESSAGES = [
    {"id": 1, "room_name": "4 Channelview", "priority": "high", "is_task": True,
     "attachment_count": 0, "is_duplicate": False, "seq": 1},
    {"id": 2, "room_name": "4 Channelview", "priority": "normal", "is_task": False,
     "attachment_count": 0, "is_duplicate": False, "seq": 2},
    {"id": 3, "room_name": "11 N&F Windchase", "priority": "normal", "is_task": False,
     "attachment_count": 0, "is_duplicate": False, "seq": 3},
    # bare "11" collapses into the same scorecard as "11 N&F Windchase"
    {"id": 4, "room_name": "11", "priority": "high", "is_task": True,
     "attachment_count": 0, "is_duplicate": False, "seq": 4},
]
TASKS = [
    {"id": 10, "room_name": "4 Channelview", "priority": "high", "status": "open",
     "category": "fuel_delivery_issue", "task_title": "need gas"},
    {"id": 11, "room_name": "4 Channelview", "priority": "normal", "status": "open",
     "category": "equipment_maintenance", "task_title": "printer"},
    {"id": 12, "room_name": "11", "priority": "normal", "status": "open",
     "category": "deposit_cash_bank", "task_title": "deposit"},
    {"id": 13, "room_name": "4 Channelview", "priority": "high", "status": "closed",
     "category": "fuel_delivery_issue", "task_title": "old"},
]
FUEL_EVENTS = [
    {"room_name": "4 Channelview", "report_date": "2024-06-01",
     "bol_gallons": 8000, "veeder_gallons": 5500},   # flagged (2500)
    {"room_name": "11 N&F Windchase", "report_date": "2024-06-02",
     "bol_gallons": 5000, "veeder_gallons": 4950},   # within tolerance
]


class Base(unittest.TestCase):
    def setUp(self):
        self.fake = FakeStore(messages=MESSAGES, tasks=TASKS,
                              fuel_events=FUEL_EVENTS).install()
        self.addCleanup(self.fake.restore)


class TestStoreScorecards(Base):
    def test_open_tasks_counted_closed_excluded(self):
        cards = {c["room_name"]: c for c in reports.store_scorecards()}
        chan = cards["4 Channelview"]
        self.assertEqual(chan["open_tasks"], 2)     # 10 + 11, not the closed 13
        self.assertEqual(chan["high_tasks"], 1)     # only task 10

    def test_canonical_site_collapses_rooms(self):
        cards = {c["room_name"]: c for c in reports.store_scorecards()}
        # "11" and "11 N&F Windchase" -> one canonical card.
        self.assertIn("11 N&F Windchase", cards)
        self.assertNotIn("11", cards)
        self.assertEqual(cards["11 N&F Windchase"]["messages"], 2)
        self.assertEqual(cards["11 N&F Windchase"]["open_tasks"], 1)

    def test_top_issue(self):
        cards = {c["room_name"]: c for c in reports.store_scorecards()}
        # Channelview has fuel_delivery_issue + equipment_maintenance (tie 1-1);
        # most_common returns the first inserted -> fuel_delivery_issue.
        self.assertEqual(cards["4 Channelview"]["top_issue"], "fuel_delivery_issue")

    def test_sorted_by_open_tasks(self):
        cards = reports.store_scorecards()
        self.assertEqual(cards[0]["room_name"], "4 Channelview")  # most open tasks


class TestFuelDiscrepancies(Base):
    def test_only_flagged_returned(self):
        flagged = reports.fuel_discrepancies()
        self.assertEqual(len(flagged), 1)
        self.assertEqual(flagged[0]["room_name"], "4 Channelview")
        self.assertEqual(flagged[0]["discrepancy_gallons"], 2500.0)


class TestDashboardHtml(Base):
    def test_html_has_both_sections(self):
        html = reports.render_dashboard_html()
        self.assertIn("Fuel Reconciliation", html)
        self.assertIn("Store Scorecard", html)
        # flagged mismatch surfaced with its diff
        self.assertIn("2,500", html)
        # scorecard lists a store
        self.assertIn("4 Channelview", html)

    def test_html_clean_when_no_discrepancies(self):
        self.fake.data["fuel_events"] = []
        html = reports.render_dashboard_html()
        self.assertIn("No BOL vs Veeder-Root discrepancies", html)


if __name__ == "__main__":
    unittest.main()
