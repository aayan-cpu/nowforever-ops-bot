import unittest
from app import cash_reconcile as cr


class ParseDepositTests(unittest.TestCase):
    def test_parses_amount_and_date(self):
        d = cr.parse_deposit("$4,940 bank deposit for 10/22")
        self.assertEqual(d["amount"], 4940.0)
        self.assertEqual(d["deposit_date"], "10/22")

    def test_picks_largest_amount(self):
        d = cr.parse_deposit("deposited 4,940.50 cash plus 60 in coin")
        self.assertEqual(d["amount"], 4940.50)

    def test_none_when_no_amount(self):
        self.assertIsNone(cr.parse_deposit("made the bank run, all good"))
        self.assertIsNone(cr.parse_deposit(""))


class CompareCashTests(unittest.TestCase):
    def test_match_within_threshold_not_flagged(self):
        v = cr.compare_cash(4940, 4935, threshold=20)
        self.assertFalse(v["flagged"])
        self.assertEqual(v["shortfall"], 5.0)

    def test_deposit_short_is_flagged(self):
        v = cr.compare_cash(5000, 4500, threshold=20)
        self.assertTrue(v["flagged"])
        self.assertEqual(v["shortfall"], 500.0)
        self.assertIn("SHORT", v["reason"])

    def test_deposit_over_is_flagged(self):
        v = cr.compare_cash(4500, 5000, threshold=20)
        self.assertTrue(v["flagged"])
        self.assertEqual(v["shortfall"], -500.0)
        self.assertIn("OVER", v["reason"])

    def test_incomplete_when_missing(self):
        v = cr.compare_cash(5000, None)
        self.assertFalse(v["flagged"])
        self.assertIsNone(v["shortfall"])
        self.assertIn("incomplete", v["reason"])

    def test_coerces_money_strings(self):
        v = cr.compare_cash("$5,000.00", "4,500", threshold=20)
        self.assertTrue(v["flagged"])
        self.assertEqual(v["shortfall"], 500.0)


class ReconcileTests(unittest.TestCase):
    def test_pairs_by_site_and_date_flags_gap(self):
        reports = [{"room_name": "4 Channelview", "report_date": "2026-06-15", "cash_amount": 5000}]
        deposits = [{"room_name": "4 Channelview", "deposit_date": "2026-06-16", "amount": 4200}]
        out = cr.reconcile(reports, deposits, threshold=20)
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0]["flagged"])
        self.assertEqual(out[0]["shortfall"], 800.0)
        self.assertEqual(out[0]["deposit_date"], "2026-06-16")

    def test_does_not_pair_across_sites(self):
        reports = [{"room_name": "4 Channelview", "report_date": "2026-06-15", "cash_amount": 5000}]
        deposits = [{"room_name": "8 Parker", "deposit_date": "2026-06-15", "amount": 5000}]
        out = cr.reconcile(reports, deposits, threshold=20)
        self.assertEqual(len(out), 1)
        self.assertFalse(out[0]["flagged"])  # no same-site deposit -> incomplete
        self.assertIn("incomplete", out[0]["reason"])

    def test_outside_window_does_not_pair(self):
        reports = [{"room_name": "A", "report_date": "2026-06-01", "cash_amount": 5000}]
        deposits = [{"room_name": "A", "deposit_date": "2026-06-30", "amount": 4000}]
        out = cr.reconcile(reports, deposits, threshold=20)
        self.assertFalse(out[0]["flagged"])  # 29 days apart > window -> unpaired

    def test_each_deposit_used_once(self):
        reports = [
            {"room_name": "A", "report_date": "2026-06-15", "cash_amount": 5000},
            {"room_name": "A", "report_date": "2026-06-15", "cash_amount": 3000},
        ]
        deposits = [{"room_name": "A", "deposit_date": "2026-06-15", "amount": 5000}]
        out = cr.reconcile(reports, deposits, threshold=20)
        paired = [o for o in out if o["deposit_amount"] is not None]
        self.assertEqual(len(paired), 1)  # only one report gets the single deposit

    def test_ignores_reports_without_cash(self):
        reports = [{"room_name": "A", "report_date": "2026-06-15"}]  # no cash_amount
        deposits = [{"room_name": "A", "deposit_date": "2026-06-15", "amount": 5000}]
        out = cr.reconcile(reports, deposits, threshold=20)
        self.assertEqual(out, [])


if __name__ == "__main__":
    unittest.main()
