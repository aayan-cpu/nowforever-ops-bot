"""Tests for the Veeder-Root / tank-gauge OCR helpers in app.vision.

Pure post-processing only (parse_tanks, veeder_totals, extract_veeder, and the
_reconcile integration) — no network / API key needed.
"""
import unittest

from app import vision


class TestParseTanks(unittest.TestCase):
    def test_parses_and_normalizes(self):
        raw = [
            {"tank": "T1", "product": "Unleaded", "volume_gallons": "6,000",
             "ullage_gallons": 2000, "water_inches": "0.5"},
            {"tank": "Tank 2", "product": "diesel", "volume_gallons": 3000,
             "ullage_gallons": None, "water_inches": None},
        ]
        out = vision.parse_tanks(raw)
        self.assertEqual(out[0]["product"], "Regular")
        self.assertEqual(out[0]["volume_gallons"], 6000.0)
        self.assertEqual(out[0]["water_inches"], 0.5)
        self.assertEqual(out[1]["product"], "Diesel")

    def test_drops_empty_rows(self):
        self.assertEqual(vision.parse_tanks([{"tank": None, "volume_gallons": None}]), [])

    def test_handles_none_and_non_dict(self):
        self.assertEqual(vision.parse_tanks(None), [])
        self.assertEqual(vision.parse_tanks(["junk"]), [])


class TestVeederTotals(unittest.TestCase):
    def test_totals_and_breakdown(self):
        tanks = [
            {"tank": "T1", "product": "Regular", "volume_gallons": 6000.0,
             "ullage_gallons": None, "water_inches": 0.5},
            {"tank": "T2", "product": "Regular", "volume_gallons": 1000.0,
             "ullage_gallons": None, "water_inches": 1.0},
            {"tank": "T3", "product": "Diesel", "volume_gallons": 3000.0,
             "ullage_gallons": None, "water_inches": None},
        ]
        t = vision.veeder_totals(tanks)
        self.assertEqual(t["total_gallons"], 10000.0)
        self.assertEqual(t["by_product"], {"Regular": 7000.0, "Diesel": 3000.0})
        self.assertEqual(t["max_water_inches"], 1.0)
        self.assertFalse(t["high_water"])

    def test_high_water_flag(self):
        tanks = [{"tank": "T1", "product": "Regular", "volume_gallons": 5000.0,
                  "ullage_gallons": None, "water_inches": 2.5}]
        t = vision.veeder_totals(tanks, water_alert_inches=2.0)
        self.assertTrue(t["high_water"])
        self.assertEqual(t["max_water_inches"], 2.5)

    def test_no_volume_total_none(self):
        t = vision.veeder_totals([{"tank": "T1", "product": None,
                                   "volume_gallons": None, "ullage_gallons": None,
                                   "water_inches": None}])
        self.assertIsNone(t["total_gallons"])


class TestExtractVeeder(unittest.TestCase):
    def test_backfills_veeder_gallons(self):
        data = {"doc_type": "veeder_root", "veeder_gallons": None,
                "tanks": [{"tank": "T1", "product": "Regular", "volume_gallons": 6000,
                           "ullage_gallons": None, "water_inches": None},
                          {"tank": "T2", "product": "Diesel", "volume_gallons": 3000,
                           "ullage_gallons": None, "water_inches": None}]}
        vision.extract_veeder(data)
        self.assertEqual(data["veeder_gallons"], 9000.0)
        self.assertEqual(data["veeder_total_gallons"], 9000.0)
        self.assertEqual(data["tanks_by_grade"], {"Regular": 6000.0, "Diesel": 3000.0})

    def test_does_not_override_existing_total(self):
        data = {"doc_type": "veeder_root", "veeder_gallons": 8888,
                "tanks": [{"tank": "T1", "product": "Regular", "volume_gallons": 6000,
                           "ullage_gallons": None, "water_inches": None}]}
        vision.extract_veeder(data)
        self.assertEqual(data["veeder_gallons"], 8888)

    def test_high_water_sets_flag(self):
        data = {"doc_type": "veeder_root", "veeder_gallons": None,
                "tanks": [{"tank": "T1", "product": "Regular", "volume_gallons": 5000,
                           "ullage_gallons": None, "water_inches": 3.0}]}
        vision.extract_veeder(data)
        self.assertTrue(data["high_water"])
        self.assertTrue(data["model_flagged_issue"])

    def test_non_veeder_doc_not_backfilled(self):
        data = {"doc_type": "day_report", "veeder_gallons": None,
                "tanks": [{"tank": "T1", "product": "Regular", "volume_gallons": 5000,
                           "ullage_gallons": None, "water_inches": None}]}
        vision.extract_veeder(data)
        self.assertIsNone(data["veeder_gallons"])


class TestReconcileIntegration(unittest.TestCase):
    def test_backfilled_veeder_drives_discrepancy(self):
        # Tank volumes total 5500; a BOL of 8000 -> 2500 gal discrepancy.
        data = {"doc_type": "veeder_root", "bol_gallons": 8000, "veeder_gallons": None,
                "tanks": [{"tank": "T1", "product": "Regular", "volume_gallons": 5500,
                           "ullage_gallons": None, "water_inches": None}]}
        out = vision._reconcile(data)
        self.assertEqual(out["veeder_gallons"], 5500.0)
        self.assertEqual(out["discrepancy_gallons"], 2500.0)
        self.assertTrue(out["needs_review"])

    def test_high_water_reason(self):
        data = {"doc_type": "veeder_root", "bol_gallons": None, "veeder_gallons": None,
                "tanks": [{"tank": "T1", "product": "Regular", "volume_gallons": 5000,
                           "ullage_gallons": None, "water_inches": 3.0}]}
        out = vision._reconcile(data)
        self.assertTrue(out["needs_review"])
        self.assertIn("water in tank", out["review_reason"])

    def test_safe_without_tanks(self):
        data = {"doc_type": "other", "bol_gallons": None, "veeder_gallons": None}
        out = vision._reconcile(data)
        self.assertEqual(out["tanks"], [])
        self.assertFalse(out["high_water"])


if __name__ == "__main__":
    unittest.main()
