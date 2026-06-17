"""Tests for the site-awareness added to app.classifier — resolving the canonical
station a message is about from room context (and, for company-wide rooms, from
an explicit in-text site reference)."""
import unittest

from app.classifier import classify_message, resolve_site


class TestResolveSite(unittest.TestCase):
    def test_station_room_number(self):
        r = resolve_site("anything", "4 Channelview")
        self.assertEqual(r["key"], "4")
        self.assertEqual(r["name"], "4 Channelview")

    def test_station_room_bare_number(self):
        self.assertEqual(resolve_site("", "11")["key"], "11")

    def test_station_room_alias(self):
        self.assertEqual(resolve_site("", "Windchase")["name"], "11 N&F Windchase")

    def test_company_wide_room_uses_text_site(self):
        # Posted in the all-hands room but names a store -> attribute that store.
        r = resolve_site("store 11 needs gas now", "All Captains Chat")
        self.assertIsNotNone(r)
        self.assertEqual(r["key"], "11")

    def test_company_wide_room_without_site_is_none(self):
        self.assertIsNone(resolve_site("good morning everyone", "All Captains Chat"))

    def test_bare_quantity_is_not_a_site(self):
        # "2666 gallons" must NOT be read as Site 2666.
        self.assertIsNone(resolve_site("we are short 2,666 gallons", "All Captains Chat"))

    def test_dm_room_with_explicit_site(self):
        r = resolve_site("issue at site 4", "Direct Message")
        self.assertEqual(r["key"], "4")


class TestClassifyCarriesSite(unittest.TestCase):
    def test_site_fields_populated_from_room(self):
        c = classify_message("need gas asap", room_name="4 Channelview")
        self.assertEqual(c.site, "4 Channelview")
        self.assertEqual(c.site_key, "4")

    def test_site_from_text_in_company_room(self):
        c = classify_message("store 24 needs a gas delivery", room_name="All Captains Chat")
        self.assertEqual(c.site_key, "24")
        self.assertEqual(c.site, "24 Galveston")

    def test_no_site_when_unattributable(self):
        c = classify_message("thanks everyone", room_name="All Captains Chat")
        self.assertIsNone(c.site)
        self.assertEqual(c.site_key, "")

    def test_site_resolution_does_not_change_priority(self):
        # Site context is attribution only — it must not alter the urgency call.
        with_site = classify_message("need gas asap", room_name="4 Channelview")
        without = classify_message("need gas asap", room_name="")
        self.assertEqual(with_site.priority, without.priority)
        self.assertEqual(with_site.is_task, without.is_task)

    def test_site_adds_small_confidence(self):
        with_site = classify_message("need gas asap", room_name="4 Channelview")
        without = classify_message("need gas asap", room_name="")
        self.assertGreater(with_site.confidence, without.confidence)

    def test_backward_compatible_defaults(self):
        # Callers that ignore room still get a valid object.
        c = classify_message("please check the printer")
        self.assertIsNone(c.site)
        self.assertEqual(c.site_key, "")


if __name__ == "__main__":
    unittest.main()
