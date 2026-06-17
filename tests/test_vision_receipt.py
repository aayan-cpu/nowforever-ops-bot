"""Tests for the BOL / fuel-delivery receipt OCR helpers in app.vision.

These cover the pure post-processing (product normalization, line-item parsing,
gallon totals, bol_gallons backfill) — no network / API key needed. analyze_image
itself isn't exercised (it requires the Claude API).
"""
import unittest

from app import vision


class TestNormalizeProduct(unittest.TestCase):
    def test_known_aliases(self):
        self.assertEqual(vision.normalize_product("Unleaded"), "Regular")
        self.assertEqual(vision.normalize_product("REG"), "Regular")
        self.assertEqual(vision.normalize_product("premium"), "Super")
        self.assertEqual(vision.normalize_product("DSL"), "Diesel")

    def test_octane_numbers(self):
        self.assertEqual(vision.normalize_product("87"), "Regular")
        self.assertEqual(vision.normalize_product("93"), "Super")

    def test_token_scan(self):
        self.assertEqual(vision.normalize_product("No-Lead Regular 87"), "Regular")

    def test_unknown_titlecased(self):
        self.assertEqual(vision.normalize_product("rocket fuel"), "Rocket Fuel")

    def test_empty_is_none(self):
        self.assertIsNone(vision.normalize_product(""))
        self.assertIsNone(vision.normalize_product(None))


class TestParseProducts(unittest.TestCase):
    def test_parses_and_normalizes(self):
        raw = [
            {"product": "Unleaded", "gallons": "5,000", "unit_price": "2.49"},
            {"product": "Diesel", "gallons": 2000, "unit_price": None},
        ]
        out = vision.parse_products(raw)
        self.assertEqual(out[0], {"product": "Regular", "gallons": 5000.0, "unit_price": 2.49})
        self.assertEqual(out[1], {"product": "Diesel", "gallons": 2000.0, "unit_price": None})

    def test_drops_empty_entries(self):
        self.assertEqual(vision.parse_products([{"product": None, "gallons": None}]), [])

    def test_handles_non_dict_and_none(self):
        self.assertEqual(vision.parse_products(None), [])
        self.assertEqual(vision.parse_products(["junk", 5]), [])


class TestReceiptTotals(unittest.TestCase):
    def test_totals_and_breakdown(self):
        products = [
            {"product": "Regular", "gallons": 5000.0, "unit_price": None},
            {"product": "Super", "gallons": 1200.0, "unit_price": None},
            {"product": "Regular", "gallons": 1000.0, "unit_price": None},  # same grade sums
        ]
        t = vision.receipt_totals(products)
        self.assertEqual(t["total_gallons"], 7200.0)
        self.assertEqual(t["by_product"], {"Regular": 6000.0, "Super": 1200.0})

    def test_no_gallons_total_none(self):
        t = vision.receipt_totals([{"product": "Regular", "gallons": None, "unit_price": None}])
        self.assertIsNone(t["total_gallons"])


class TestExtractReceipt(unittest.TestCase):
    def test_backfills_bol_gallons_from_line_items(self):
        data = {"doc_type": "fuel_receipt", "bol_gallons": None,
                "products": [{"product": "Regular", "gallons": 5000, "unit_price": None},
                             {"product": "Diesel", "gallons": 2000, "unit_price": None}]}
        vision.extract_receipt(data)
        self.assertEqual(data["bol_gallons"], 7000.0)
        self.assertEqual(data["receipt_total_gallons"], 7000.0)
        self.assertEqual(data["products_by_grade"], {"Regular": 5000.0, "Diesel": 2000.0})

    def test_does_not_override_existing_bol(self):
        data = {"doc_type": "bol", "bol_gallons": 9999,
                "products": [{"product": "Regular", "gallons": 5000, "unit_price": None}]}
        vision.extract_receipt(data)
        self.assertEqual(data["bol_gallons"], 9999)  # model's explicit total wins

    def test_non_receipt_doc_not_backfilled(self):
        data = {"doc_type": "price_sign", "bol_gallons": None,
                "products": [{"product": "Regular", "gallons": 5000, "unit_price": None}]}
        vision.extract_receipt(data)
        self.assertIsNone(data["bol_gallons"])


class TestReconcileIntegration(unittest.TestCase):
    def test_reconcile_backfills_then_flags_discrepancy(self):
        # Receipt with per-product lines (total 8000) + a Veeder reading of 5500
        # -> backfilled bol_gallons drives the existing discrepancy check.
        data = {"doc_type": "bol", "bol_gallons": None, "veeder_gallons": 5500,
                "products": [{"product": "Regular", "gallons": 6000, "unit_price": None},
                             {"product": "Diesel", "gallons": 2000, "unit_price": None}]}
        out = vision._reconcile(data)
        self.assertEqual(out["bol_gallons"], 8000.0)
        self.assertEqual(out["discrepancy_gallons"], 2500.0)
        self.assertTrue(out["needs_review"])

    def test_reconcile_safe_without_products(self):
        data = {"doc_type": "other", "bol_gallons": None, "veeder_gallons": None}
        out = vision._reconcile(data)
        self.assertEqual(out["products"], [])
        self.assertIsNone(out["receipt_total_gallons"])


if __name__ == "__main__":
    unittest.main()
