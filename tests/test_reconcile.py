"""Tests for BOL vs Veeder-Root reconciliation (WORK.md: 'Veeder-Root vs BOL mismatch').

Run: `py -m unittest tests.test_reconcile` from the repo root.

Pins the cross-record pairing that catches discrepancies like the ~2,500-gal
Channelview case, where the BOL receipt and the tank reading arrive as separate
messages. Logic is pure (event lists in, mismatch list out) — no Firestore.
"""
import unittest

from app import reconcile


def _ev(room, date=None, bol=None, veeder=None, data_id="x"):
    return {"room_name": room, "report_date": date, "bol_gallons": bol,
            "veeder_gallons": veeder, "data_id": data_id}


class SameRecordTests(unittest.TestCase):
    def test_flags_single_record_with_both_figures(self):
        out = reconcile.reconcile_events([_ev("4 Channelview", bol=8000, veeder=5500)], threshold=500)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["discrepancy_gallons"], 2500)
        self.assertEqual(out[0]["source"], "same-record")

    def test_within_threshold_not_flagged(self):
        out = reconcile.reconcile_events([_ev("4 Channelview", bol=8000, veeder=7800)], threshold=500)
        self.assertEqual(out, [])


class MatchByDateTests(unittest.TestCase):
    def test_pairs_separate_bol_and_veeder_messages(self):
        events = [
            _ev("4 Channelview", date="2026-06-10", bol=8000, data_id="bol1"),
            _ev("4 Channelview", date="2026-06-10", veeder=5500, data_id="vr1"),
        ]
        out = reconcile.reconcile_events(events, threshold=500)
        self.assertEqual(len(out), 1)
        m = out[0]
        self.assertEqual(m["source"], "matched-by-date")
        self.assertEqual(m["discrepancy_gallons"], 2500)
        self.assertEqual(set(m["data_ids"]), {"bol1", "vr1"})

    def test_sums_multiple_drops_same_day(self):
        events = [
            _ev("9 Bissonnet", date="2026-06-10", bol=4000, data_id="b1"),
            _ev("9 Bissonnet", date="2026-06-10", bol=4000, data_id="b2"),
            _ev("9 Bissonnet", date="2026-06-10", veeder=5500, data_id="v1"),
        ]
        out = reconcile.reconcile_events(events, threshold=500)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["bol_gallons"], 8000)
        self.assertEqual(out[0]["discrepancy_gallons"], 2500)

    def test_different_dates_do_not_pair(self):
        events = [
            _ev("4 Channelview", date="2026-06-10", bol=8000),
            _ev("4 Channelview", date="2026-06-11", veeder=5500),
        ]
        self.assertEqual(reconcile.reconcile_events(events, threshold=500), [])

    def test_different_sites_do_not_pair(self):
        events = [
            _ev("4 Channelview", date="2026-06-10", bol=8000),
            _ev("9 Bissonnet", date="2026-06-10", veeder=5500),
        ]
        self.assertEqual(reconcile.reconcile_events(events, threshold=500), [])

    def test_undated_events_are_skipped_in_crosspass(self):
        events = [
            _ev("4 Channelview", bol=8000),   # no date -> can't pair safely
            _ev("4 Channelview", veeder=5500),
        ]
        self.assertEqual(reconcile.reconcile_events(events, threshold=500), [])


class CoercionAndFormatTests(unittest.TestCase):
    def test_string_gallon_values_coerced(self):
        out = reconcile.reconcile_events(
            [_ev("4 Channelview", date="2026-06-10", bol="8,000", data_id="b"),
             _ev("4 Channelview", date="2026-06-10", veeder="5500", data_id="v")],
            threshold=500)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["bol_gallons"], 8000.0)

    def test_results_sorted_biggest_gap_first(self):
        events = [
            _ev("A", date="d", bol=1000, veeder=2000),   # 1000
            _ev("B", date="d", bol=1000, veeder=5000),   # 4000
        ]
        out = reconcile.reconcile_events(events, threshold=500)
        self.assertEqual([m["discrepancy_gallons"] for m in out], [4000, 1000])

    def test_format_report_empty_and_nonempty(self):
        self.assertIn("No BOL", reconcile.format_report([]))
        out = reconcile.reconcile_events([_ev("4 Channelview", date="2026-06-10", bol=8000, veeder=5500)], threshold=500)
        text = reconcile.format_report(out)
        self.assertIn("4 Channelview", text)
        self.assertIn("2500", text)


if __name__ == "__main__":
    unittest.main()
