"""Tests for canonical site-name resolution (WORK.md: 'Site-name normalization').

Run: `py -m unittest tests.test_sites` from the repo root.

Pins the core promise from the task: "11", "Windchase", and "11 N&F Windchase"
must all resolve to the same station, regardless of how a chat room, message, or
user happened to spell it.
"""
import unittest

from app import sites


class SiteKeyGroupingTests(unittest.TestCase):
    def test_number_place_and_full_name_are_one_site(self):
        # The headline example from the task description.
        self.assertEqual(sites.site_key("11"), sites.site_key("Windchase"))
        self.assertEqual(sites.site_key("11"), sites.site_key("11 N&F Windchase"))
        self.assertTrue(sites.same_site("11", "windchase"))
        self.assertTrue(sites.same_site("Windchase", "11 N&F Windchase"))

    def test_channelview_variants(self):
        self.assertTrue(sites.same_site("4", "Channelview"))
        self.assertTrue(sites.same_site("4 Channelview", "channelview"))
        self.assertEqual(sites.site_key("4"), "4")

    def test_site_and_store_prefixes_are_ignored(self):
        self.assertTrue(sites.same_site("site 18", "Harwin & Gessener"))
        self.assertTrue(sites.same_site("store 4", "4 Channelview"))
        self.assertTrue(sites.same_site("#11", "11 N&F Windchase"))

    def test_multiword_aliases(self):
        self.assertTrue(sites.same_site("12", "Stafford"))
        self.assertTrue(sites.same_site("12 S Main Stafford", "stafford"))
        self.assertTrue(sites.same_site("18", "gessener"))

    def test_distinct_sites_do_not_collide(self):
        self.assertFalse(sites.same_site("11", "4"))
        self.assertFalse(sites.same_site("Windchase", "Galveston"))
        self.assertNotEqual(sites.site_key("24 Galveston"), sites.site_key("27 Fry"))


class CanonicalNameTests(unittest.TestCase):
    def test_canonical_name_from_number(self):
        self.assertEqual(sites.canonical_name("11"), "11 N&F Windchase")
        self.assertEqual(sites.canonical_name("4 channelview"), "4 Channelview")

    def test_canonical_name_from_alias(self):
        self.assertEqual(sites.canonical_name("galveston"), "24 Galveston")
        self.assertEqual(sites.canonical_name("WESTHEIMER"), "29 Westheimer")


class ResolveTests(unittest.TestCase):
    def test_resolve_known_site_fields(self):
        r = sites.resolve("power outage windchase")
        self.assertIsNotNone(r)
        self.assertEqual(r["number"], 11)
        self.assertEqual(r["name"], "11 N&F Windchase")
        self.assertEqual(r["key"], "11")

    def test_unknown_number_gets_own_bucket(self):
        r = sites.resolve("site 99")
        self.assertEqual(r["number"], 99)
        self.assertEqual(r["key"], "99")
        self.assertEqual(r["name"], "Site 99")
        # Two references to the same unknown number still group together.
        self.assertTrue(sites.same_site("99", "store 99"))

    def test_unknown_place_is_stable_and_distinct(self):
        k1 = sites.site_key("Some New Place")
        k2 = sites.site_key("some new place")
        self.assertEqual(k1, k2)
        self.assertTrue(k1)
        self.assertNotEqual(k1, sites.site_key("Another Spot"))


class NonStationTests(unittest.TestCase):
    def test_company_wide_and_system_rooms_are_not_stations(self):
        for n in ("All Captains Chat", "spaces/AAAAhO6H0_Y",
                  "Direct message", "", None,
                  "SUMMERBELL CAMPUS COMMUNICATIONS GROUP"):
            self.assertFalse(sites.is_station(n), n)
            self.assertIsNone(sites.resolve(n), n)
            self.assertEqual(sites.site_key(n), "")

    def test_same_site_false_for_non_stations(self):
        self.assertFalse(sites.same_site("All Captains Chat", "All Captains Chat"))
        self.assertFalse(sites.same_site(None, None))


if __name__ == "__main__":
    unittest.main()
