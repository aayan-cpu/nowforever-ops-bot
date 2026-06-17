"""Tests for fuel reconciliation (WORK.md: 'Veeder-Root vs BOL mismatch detection').

Run: `py -m unittest tests.test_reconcile` from the repo root.
"""
import unittest

from app import reconcile


class DiscrepancyTests(unittest.TestCase):
    def test_signed_difference(self):
        self.assertEqual(reconcile.discrepancy(8000, 5500), 2500.0)
        self.assertEqual(reconcile.discrepancy(5000, 5200), -200.0)

    def test_missing_reading_is_none(self):
        self.assertIsNone(reconcile.discrepancy(None, 5000))
        self.assertIsNone(reconcile.discrepancy(5000, None))
        self.assertIsNone(reconcile.discrepancy("", 5000))

    def test_non_numeric_is_none(self):
        self.assertIsNone(reconcile.discrepancy("n/a", 5000))

    def test_string_numbers_coerced(self):
        self.assertEqual(reconcile.discrepancy("8000", "5500"), 2500.0)


class MismatchPredicateTests(unittest.TestCase):
    def test_within_tolerance_not_flagged(self):
        self.assertFalse(reconcile.is_mismatch(5000, 5150, tolerance=200))

    def test_beyond_tolerance_flagged(self):
        self.assertTrue(reconcile.is_mismatch(8000, 5500, tolerance=200))

    def test_exactly_tolerance_not_flagged(self):
        # strictly greater-than tolerance is required
        self.assertFalse(reconcile.is_mismatch(5200, 5000, tolerance=200))

    def test_missing_reading_not_flagged(self):
        self.assertFalse(reconcile.is_mismatch(None, 5000, tolerance=200))


class ReconcileEventsTests(unittest.TestCase):
    def test_channelview_case_detected_and_sorted_first(self):
        events = [
            {"room_name": "4 Channelview", "report_date": "2026-06-15", "bol_gallons": 8000, "veeder_gallons": 5500},
            {"room_name": "11 Windchase", "report_date": "2026-06-15", "bol_gallons": 5000, "veeder_gallons": 4900},  # within tol
            {"room_name": "7 Katy", "report_date": "2026-06-15", "bol_gallons": 6000, "veeder_gallons": 5500},        # 500 gap
            {"room_name": "9 Pearland", "bol_gallons": None, "veeder_gallons": 4000},                                  # missing
        ]
        out = reconcile.reconcile_events(events, tolerance=200)
        self.assertEqual(len(out), 2)  # Channelview + Katy; Windchase within tol, Pearland missing
        self.assertEqual(out[0]["room_name"], "4 Channelview")  # biggest gap first
        self.assertEqual(out[0]["discrepancy_gallons"], 2500.0)

    def test_empty_when_all_within_tolerance(self):
        events = [{"room_name": "R", "bol_gallons": 5000, "veeder_gallons": 5050}]
        self.assertEqual(reconcile.reconcile_events(events, tolerance=200), [])


class FormatTests(unittest.TestCase):
    def test_empty_is_all_clear(self):
        self.assertIn("no BOL/Veeder discrepancies", reconcile.format_mismatches([]))

    def test_short_vs_over_wording(self):
        rows = reconcile.reconcile_events([
            {"room_name": "A", "bol_gallons": 8000, "veeder_gallons": 5500},  # short in tank
            {"room_name": "B", "bol_gallons": 5000, "veeder_gallons": 5400},  # over in tank
        ], tolerance=200)
        out = reconcile.format_mismatches(rows)
        self.assertIn("2500 gal short in tank", out)
        self.assertIn("400 gal over in tank", out)


if __name__ == "__main__":
    unittest.main()
