"""Tests for proactive DM / broadcast (WORK.md: 'Message-everyone / proactive DM').

Run: `py -m unittest tests.test_message_user` from the repo root.

Covers the pure directory name-resolver and the brain message_user/broadcast tool
dispatch. The live Google Directory/Chat calls are mocked, so no creds are needed.
"""
import unittest
from unittest.mock import patch

from app import directory, brain

USERS = [
    {"email": "moiz@khawarsons.com", "name": "Abdul Moiz", "id": "1"},
    {"email": "moin@khawarsons.com", "name": "Moin Khan", "id": "2"},
    {"email": "aayan@khawarsons.com", "name": "Aayan", "id": "3"},
    {"email": "abdul.rahman@khawarsons.com", "name": "Abdul Rahman", "id": "4"},
]


class MatchPersonTests(unittest.TestCase):
    def test_exact_email(self):
        m, _ = directory._match_person("moiz@khawarsons.com", USERS)
        self.assertEqual(m["id"], "1")

    def test_exact_full_name_case_insensitive(self):
        m, _ = directory._match_person("abdul moiz", USERS)
        self.assertEqual(m["id"], "1")

    def test_unique_substring(self):
        m, _ = directory._match_person("moiz", USERS)
        self.assertEqual(m["id"], "1")

    def test_all_token_match(self):
        m, _ = directory._match_person("abdul rahman", USERS)
        self.assertEqual(m["id"], "4")

    def test_ambiguous_returns_candidates(self):
        m, cands = directory._match_person("abdul", USERS)
        self.assertIsNone(m)
        self.assertEqual({c["id"] for c in cands}, {"1", "4"})

    def test_not_found(self):
        m, cands = directory._match_person("nobody here", USERS)
        self.assertIsNone(m)
        self.assertEqual(cands, [])

    def test_blank_query(self):
        self.assertEqual(directory._match_person("", USERS), (None, []))


class MessageUserDispatchTests(unittest.TestCase):
    def test_success(self):
        with patch("app.directory.message_person",
                   return_value={"ok": True, "matched_name": "Abdul Moiz", "email": "moiz@khawarsons.com"}):
            out = brain._run_tool("message_user", {"person": "Abdul Moiz", "message": "Delivery is here"})
        self.assertEqual(out, "Sent your message to Abdul Moiz.")

    def test_ambiguous(self):
        with patch("app.directory.message_person", return_value={
            "ok": False, "error": "ambiguous",
            "candidates": [{"name": "Abdul Moiz", "email": "moiz@khawarsons.com"},
                           {"name": "Abdul Rahman", "email": "abdul.rahman@khawarsons.com"}],
        }):
            out = brain._run_tool("message_user", {"person": "Abdul", "message": "hi"})
        self.assertIn("More than one person", out)
        self.assertIn("Abdul Moiz", out)
        self.assertIn("Abdul Rahman", out)

    def test_not_found(self):
        with patch("app.directory.message_person", return_value={"ok": False, "error": "not_found"}):
            out = brain._run_tool("message_user", {"person": "Ghost", "message": "hi"})
        self.assertIn("couldn't find anyone", out)

    def test_requires_both_fields(self):
        out = brain._run_tool("message_user", {"person": "Abdul Moiz", "message": ""})
        self.assertIn("I need both", out)

    def test_delivery_failure_surfaced(self):
        with patch("app.directory.message_person",
                   return_value={"ok": False, "error": "no DM space (user may need to allow the app)"}):
            out = brain._run_tool("message_user", {"person": "Moin", "message": "hi"})
        self.assertIn("Couldn't message", out)


class BroadcastDispatchTests(unittest.TestCase):
    def test_captains_scope_posts_with_megaphone_prefix(self):
        with patch("app.chat_media.post_to_space", return_value=True) as m:
            out = brain._run_tool("broadcast", {"message": "Store meeting at 5pm", "scope": "captains"})
        self.assertIn("all-captains", out)
        text = m.call_args[0][1]
        self.assertTrue(text.startswith("📢 "))
        self.assertIn("Store meeting at 5pm", text)

    def test_all_stores_posts_to_every_room(self):
        rooms = [("spaces/A", "4 Channelview"), ("spaces/B", "11 Windchase")]
        with patch("app.brain.store_room_spaces", return_value=rooms), \
             patch("app.chat_media.post_to_space", return_value=True) as m:
            out = brain._run_tool("broadcast", {"message": "freeze prep tonight"})
        self.assertIn("2 store chat", out)
        self.assertEqual(m.call_count, 2)  # one post per room

    def test_all_stores_reports_failures(self):
        rooms = [("spaces/A", "4 Channelview"), ("spaces/B", "11 Windchase")]
        with patch("app.brain.store_room_spaces", return_value=rooms), \
             patch("app.chat_media.post_to_space", side_effect=[True, False]):
            out = brain._run_tool("broadcast", {"message": "x", "scope": "all_stores"})
        self.assertIn("1 store chat", out)
        self.assertIn("Couldn't reach 1", out)
        self.assertIn("11 Windchase", out)

    def test_empty_message(self):
        out = brain._run_tool("broadcast", {"message": "   "})
        self.assertIn("What should I announce", out)

    def test_captains_post_failure(self):
        with patch("app.chat_media.post_to_space", return_value=False):
            out = brain._run_tool("broadcast", {"message": "hello", "scope": "captains"})
        self.assertIn("Couldn't post", out)


class ToolRegistrationTests(unittest.TestCase):
    def test_message_user_and_broadcast_are_admin_only(self):
        action_names = {t["name"] for t in brain._ACTION_TOOLS}
        read_names = {t["name"] for t in brain._READ_TOOLS}
        self.assertIn("message_user", action_names)
        self.assertIn("broadcast", action_names)
        self.assertNotIn("message_user", read_names)
        self.assertNotIn("broadcast", read_names)


if __name__ == "__main__":
    unittest.main()
