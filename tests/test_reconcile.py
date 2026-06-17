"""Tests for app.reconcile — cross-event BOL vs Veeder-Root reconciliation."""
import unittest

from app import reconcile


class TestCompare(unittest.TestCase):
    def test_within_tolerance(self):
        r = reconcile.compare(5000, 4900, threshold=500)
        self.assertFalse(r["flagged"])
        self.assertEqual(r["discrepancy_gallons"], 100.0)

    def test_over_threshold_flags(self):
        # The Channelview-style ~2,500 gal gap.
        r = reconcile.compare(8000, 5500, threshold=500)
        self.assertTrue(r["flagged"])
        self.assertEqual(r["discrepancy_gallons"], 2500.0)
        self.assertIn("2500", r["reason"].replace(",", ""))

    def test_missing_side_is_incomplete(self):
        r = reconcile.compare(5000, None)
        self.assertFalse(r["flagged"])
        self.assertIn("incomplete", r["reason"])

    def test_string_numbers_coerced(self):
        r = reconcile.compare("8,000", "5500", threshold=500)
        self.assertTrue(r["flagged"])

    def test_exactly_threshold_not_flagged(self):
        # diff must EXCEED threshold (matches vision._reconcile).
        self.assertFalse(reconcile.compare(1500, 1000, threshold=500)["flagged"])


class TestSingleImageEvents(unittest.TestCase):
    def test_event_with_both_numbers(self):
        events = [{"room_name": "4 Channelview", "report_date": "2024-06-01",
                   "bol_gallons": 8000, "veeder_gallons": 5500}]
        res = reconcile.reconcile_events(events, threshold=500)
        self.assertEqual(len(res), 1)
        self.assertTrue(res[0]["flagged"])
        self.assertEqual(res[0]["room_name"], "4 Channelview")


class TestCrossEventPairing(unittest.TestCase):
    def test_separate_bol_and_veeder_paired_by_site_and_date(self):
        events = [
            {"room_name": "4 Channelview", "report_date": "2024-06-01", "bol_gallons": 8000},
            {"room_name": "4 Channelview", "report_date": "2024-06-02", "veeder_gallons": 5500},
        ]
        res = reconcile.reconcile_events(events, threshold=500)
        flagged = [r for r in res if r["flagged"]]
        self.assertEqual(len(flagged), 1)
        self.assertEqual(flagged[0]["bol_gallons"], 8000)
        self.assertEqual(flagged[0]["veeder_gallons"], 5500)

    def test_different_sites_not_paired(self):
        events = [
            {"room_name": "4 Channelview", "report_date": "2024-06-01", "bol_gallons": 8000},
            {"room_name": "11 Windchase", "report_date": "2024-06-01", "veeder_gallons": 5500},
        ]
        res = reconcile.reconcile_events(events, threshold=500)
        # No complete pair -> both incomplete, nothing flagged.
        self.assertEqual([r for r in res if r["flagged"]], [])
        self.assertTrue(all("incomplete" in r["reason"] for r in res))

    def test_out_of_window_not_paired(self):
        events = [
            {"room_name": "4 Channelview", "report_date": "2024-06-01", "bol_gallons": 8000},
            {"room_name": "4 Channelview", "report_date": "2024-07-01", "veeder_gallons": 5500},
        ]
        res = reconcile.reconcile_events(events, threshold=500)
        self.assertEqual([r for r in res if r["flagged"]], [])

    def test_each_reading_used_once(self):
        events = [
            {"room_name": "4 Channelview", "report_date": "2024-06-01", "bol_gallons": 8000},
            {"room_name": "4 Channelview", "report_date": "2024-06-01", "bol_gallons": 7000},
            {"room_name": "4 Channelview", "report_date": "2024-06-01", "veeder_gallons": 5500},
        ]
        res = reconcile.reconcile_events(events, threshold=500)
        # One BOL pairs with the Veeder; the other BOL is left incomplete.
        complete = [r for r in res if r["discrepancy_gallons"] is not None]
        incomplete = [r for r in res if r["discrepancy_gallons"] is None]
        self.assertEqual(len(complete), 1)
        self.assertEqual(len(incomplete), 1)


class TestDiscrepanciesAndSummary(unittest.TestCase):
    EVENTS = [
        {"room_name": "4 Channelview", "report_date": "2024-06-01",
         "bol_gallons": 8000, "veeder_gallons": 5500},   # flagged (2500)
        {"room_name": "11 Windchase", "report_date": "2024-06-02",
         "bol_gallons": 5000, "veeder_gallons": 4950},   # ok (50)
    ]

    def test_discrepancies_filters_to_flagged(self):
        flagged = reconcile.discrepancies(self.EVENTS, threshold=500)
        self.assertEqual(len(flagged), 1)
        self.assertEqual(flagged[0]["room_name"], "4 Channelview")

    def test_summary_lists_flagged(self):
        out = reconcile.summarize(self.EVENTS, threshold=500)
        self.assertIn("Channelview", out)
        self.assertNotIn("Windchase", out)

    def test_summary_clean_when_none(self):
        out = reconcile.summarize([], threshold=500)
        self.assertIn("No BOL vs Veeder", out)

    def test_discrepancies_reads_store_when_events_none(self):
        from app import store
        orig = store.list_all
        store.list_all = lambda c, use_cache=True: (
            list(self.EVENTS) if c == "fuel_events" else [])
        try:
            flagged = reconcile.discrepancies(threshold=500)
            self.assertEqual(len(flagged), 1)
        finally:
            store.list_all = orig


if __name__ == "__main__":
    unittest.main()
