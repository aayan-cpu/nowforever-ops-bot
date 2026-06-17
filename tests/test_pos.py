"""Tests for the POS integration scaffold (WORK.md: 'POS integration scaffold').

Run: `py -m unittest tests.test_pos` from the repo root.
"""
import os
import unittest

from app import pos


class AdapterRegistryTests(unittest.TestCase):
    def test_default_adapter_is_fake(self):
        a = pos.get_adapter()
        self.assertEqual(a.name, "fake")
        self.assertIsInstance(a, pos.FakePOSAdapter)

    def test_fake_satisfies_protocol(self):
        self.assertIsInstance(pos.get_adapter("fake"), pos.POSAdapter)

    def test_unknown_adapter_raises(self):
        with self.assertRaises(ValueError):
            pos.get_adapter("nonesuch-vendor")

    def test_env_var_selects_adapter(self):
        saved = os.environ.get("OPS_POS_ADAPTER")
        os.environ["OPS_POS_ADAPTER"] = "fake"
        try:
            self.assertEqual(pos.get_adapter().name, "fake")
        finally:
            if saved is None:
                os.environ.pop("OPS_POS_ADAPTER", None)
            else:
                os.environ["OPS_POS_ADAPTER"] = saved

    def test_register_and_resolve_custom_adapter(self):
        self.addCleanup(lambda: pos._ADAPTERS.pop("dummy", None))
        pos.register_adapter("dummy", pos.FakePOSAdapter)
        self.assertIn("dummy", pos.available_adapters())
        self.assertEqual(pos.get_adapter("dummy").name, "fake")


class FakeSalesTests(unittest.TestCase):
    def setUp(self):
        self.a = pos.FakePOSAdapter(stores=["4 Channelview"])

    def test_known_store_returns_summary(self):
        s = self.a.get_sales("4 Channelview", "2026-06-17")
        self.assertIsInstance(s, pos.SalesSummary)
        self.assertEqual(s.store, "4 Channelview")

    def test_total_is_fuel_plus_inside(self):
        s = self.a.get_sales("4 Channelview", "2026-06-17")
        self.assertAlmostEqual(s.total_sales, round(s.fuel_sales + s.inside_sales, 2))

    def test_deterministic(self):
        s1 = self.a.get_sales("4 Channelview", "2026-06-17")
        s2 = self.a.get_sales("4 Channelview", "2026-06-17")
        self.assertEqual(s1, s2)

    def test_different_dates_differ(self):
        s1 = self.a.get_sales("4 Channelview", "2026-06-17")
        s2 = self.a.get_sales("4 Channelview", "2026-06-18")
        self.assertNotEqual((s1.total_sales, s1.transactions), (s2.total_sales, s2.transactions))

    def test_unknown_store_returns_none(self):
        self.assertIsNone(self.a.get_sales("99 Nowhere", "2026-06-17"))


class FakeInventoryTests(unittest.TestCase):
    def setUp(self):
        self.a = pos.FakePOSAdapter(stores=["4 Channelview"])

    def test_lists_items_for_known_store(self):
        items = self.a.list_inventory("4 Channelview")
        self.assertTrue(items)
        self.assertTrue(all(isinstance(i, pos.InventoryItem) for i in items))

    def test_unknown_store_empty(self):
        self.assertEqual(self.a.list_inventory("99 Nowhere"), [])

    def test_below_reorder_flag(self):
        low = pos.InventoryItem(store="X", sku="S", name="n", quantity=100, reorder_level=200)
        ok = pos.InventoryItem(store="X", sku="S", name="n", quantity=300, reorder_level=200)
        none = pos.InventoryItem(store="X", sku="S", name="n", quantity=1)
        self.assertTrue(low.below_reorder)
        self.assertFalse(ok.below_reorder)
        self.assertFalse(none.below_reorder)  # no threshold set


if __name__ == "__main__":
    unittest.main()
