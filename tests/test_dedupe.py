"""Tests for near-duplicate task dedupe (WORK.md: 'Near-duplicate task dedupe').

Run: `py -m unittest tests.test_dedupe` from the repo root.

Repeated "need gas"-style reports for the same store should collapse into one
task. The collapse key is computed in the classifier (pure) and used by
chat_live to skip creating a second task. We test the pure key logic directly
and the open-task lookup with `store.find` patched (no Firestore).
"""
import unittest

from app import classifier, chat_live


class RecurringTopicTests(unittest.TestCase):
    def test_gas_variants_map_to_one_topic(self):
        for t in ("need gas", "we need gas asap", "gas needed at the pump",
                  "low on diesel", "out of fuel", "running low on gas"):
            self.assertEqual(classifier.recurring_issue_topic(t), "gas_needed", t)

    def test_other_topics(self):
        self.assertEqual(classifier.recurring_issue_topic("the power is out again"), "power_outage")
        self.assertEqual(classifier.recurring_issue_topic("ice machine is down"), "ice_machine_down")
        self.assertEqual(classifier.recurring_issue_topic("printer not printing tickets"), "printer_down")
        self.assertEqual(classifier.recurring_issue_topic("pump 3 out of order"), "pump_down")

    def test_non_recurring_message_has_no_topic(self):
        for t in ("thanks team", "good morning", "deposit done for the day", ""):
            self.assertEqual(classifier.recurring_issue_topic(t), "", t)


class DedupeKeyTests(unittest.TestCase):
    def test_key_needs_both_site_and_topic(self):
        self.assertEqual(classifier.dedupe_key_for("11", "need gas"), "11:gas_needed")
        self.assertEqual(classifier.dedupe_key_for("", "need gas"), "")       # no site
        self.assertEqual(classifier.dedupe_key_for("11", "thanks team"), "")  # no topic

    def test_classify_message_sets_dedupe_key_from_room(self):
        a = classifier.classify_message("we need gas", room_name="11 N&F Windchase")
        b = classifier.classify_message("station is low on diesel", room_name="11 N&F Windchase")
        self.assertEqual(a.dedupe_key, "11:gas_needed")
        self.assertEqual(a.dedupe_key, b.dedupe_key)
        self.assertTrue(classifier.are_near_duplicates(a, b))

    def test_site_from_in_text_reference(self):
        # Company-wide room, but the text names the store.
        c = classifier.classify_message("site 4 needs gas", room_name="All Captains Chat")
        self.assertEqual(c.dedupe_key, "4:gas_needed")

    def test_different_site_or_topic_not_duplicate(self):
        gas11 = classifier.classify_message("need gas", room_name="11 N&F Windchase")
        gas4 = classifier.classify_message("need gas", room_name="4 Channelview")
        power11 = classifier.classify_message("power is out", room_name="11 N&F Windchase")
        self.assertFalse(classifier.are_near_duplicates(gas11, gas4))     # different site
        self.assertFalse(classifier.are_near_duplicates(gas11, power11))  # different topic

    def test_no_site_messages_never_collapse(self):
        a = classifier.classify_message("need gas", room_name="All Captains Chat")
        b = classifier.classify_message("need gas", room_name="All Captains Chat")
        self.assertEqual(a.dedupe_key, "")
        self.assertFalse(classifier.are_near_duplicates(a, b))  # empty key never matches


class OpenTaskLookupTests(unittest.TestCase):
    def setUp(self):
        self._orig = chat_live.store.find

    def tearDown(self):
        chat_live.store.find = self._orig

    def _patch_find(self, rows):
        chat_live.store.find = lambda coll, field, value, limit=5: [
            r for r in rows if r.get(field) == value][:limit]

    def test_finds_open_task_with_same_key(self):
        self._patch_find([{"id": 7, "dedupe_key": "11:gas_needed", "status": "open"}])
        t = chat_live._open_task_by_dedupe("11:gas_needed")
        self.assertEqual(t["id"], 7)

    def test_ignores_closed_task(self):
        self._patch_find([{"id": 7, "dedupe_key": "11:gas_needed", "status": "closed"}])
        self.assertIsNone(chat_live._open_task_by_dedupe("11:gas_needed"))

    def test_empty_key_returns_none_without_lookup(self):
        called = []
        chat_live.store.find = lambda *a, **k: called.append(1) or []
        self.assertIsNone(chat_live._open_task_by_dedupe(""))
        self.assertEqual(called, [])  # short-circuits, no store call


if __name__ == "__main__":
    unittest.main()
