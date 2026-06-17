"""Tests for the bare-keyword command router in app.chat_live.build_reply.

Regression target: bare words like "report"/"reports"/"alerts" used to fall
through to a blank "Got it." ack instead of acting. These pin that every known
command word is recognized, and that a recognized word never decays into a
blank ack even when the AI brain is unavailable.

Self-contained: stubs store reads and brain.enabled() inline so it doesn't
depend on test infra from other branches.
"""
import unittest

from app import chat_live
from app import store
from app import brain


ADMIN = "aayan@khawarsons.com"        # in the default ADMIN_EMAILS seed
NONADMIN = "clerk@example.com"

MESSAGES = [
    {"id": 1, "room_name": "4 Channelview", "priority": "high", "is_task": True,
     "attachment_count": 0, "message": "need gas", "is_duplicate": False, "seq": 1},
]
TASKS = [
    {"id": 7, "room_name": "4 Channelview", "priority": "high", "status": "open",
     "task_title": "need gas"},
]


def reply(text, sender=ADMIN):
    return chat_live.build_reply({"message": text, "sender": sender}, None, None)


class ChatCommandsBase(unittest.TestCase):
    def setUp(self):
        # Stub store reads used by dashboard/high_priority/open_tasks.
        self._orig_list = store.list_all
        store.list_all = lambda c, use_cache=True: (
            [dict(m) for m in MESSAGES] if c == "messages"
            else [dict(t) for t in TASKS] if c == "tasks" else []
        )
        self.addCleanup(lambda: setattr(store, "list_all", self._orig_list))
        # Default: brain available (so non-admins defer to it).
        self._orig_enabled = brain.enabled
        self.set_brain(True)
        self.addCleanup(lambda: setattr(brain, "enabled", self._orig_enabled))

    def set_brain(self, on: bool):
        brain.enabled = lambda: on


class TestKeywordRecognition(ChatCommandsBase):
    def test_reports_keyword_recognized(self):
        # The headline bug: "reports"/"report" used to ack "Got it."
        self.assertIn("Summary", reply("reports"))
        self.assertIn("Summary", reply("report"))

    def test_summary_and_status_aliases(self):
        self.assertIn("Summary", reply("summary"))
        self.assertIn("Summary", reply("status"))
        self.assertIn("Summary", reply("dashboard"))

    def test_alerts_keyword(self):
        out = reply("alerts")
        self.assertTrue("Alerts" in out or "No high-priority" in out)

    def test_tasks_keyword(self):
        out = reply("tasks")
        self.assertTrue("Open Tasks" in out or "No open tasks" in out)

    def test_help_keyword_for_everyone(self):
        self.assertIn("Ops Bot", reply("help", sender=NONADMIN))
        self.assertIn("Ops Bot", reply("commands"))

    def test_mention_prefix_stripped(self):
        self.assertIn("Summary", reply("NowForever Ops Bot reports"))

    def test_trailing_punctuation_ignored(self):
        self.assertIn("Summary", reply("report!"))


class TestNoBlankAck(ChatCommandsBase):
    def test_nonadmin_command_with_brain_down_still_answers(self):
        # Brain unavailable: a recognized word must NOT decay to None
        # (which the caller would turn into a blank "Got it.").
        self.set_brain(False)
        self.assertIsNotNone(reply("reports", sender=NONADMIN))
        self.assertIsNotNone(reply("alerts", sender=NONADMIN))
        self.assertIsNotNone(reply("tasks", sender=NONADMIN))

    def test_nonadmin_defers_to_brain_when_up(self):
        # With the brain up, defer (return None) so the AI answers naturally.
        self.set_brain(True)
        self.assertIsNone(reply("reports", sender=NONADMIN))

    def test_admin_always_answered(self):
        self.set_brain(True)
        self.assertIsNotNone(reply("reports", sender=ADMIN))

    def test_is_command_word_helper(self):
        self.assertTrue(chat_live.is_command_word("reports"))
        self.assertTrue(chat_live.is_command_word("@Ops Bot alerts"))
        self.assertFalse(chat_live.is_command_word("how are sales at store 4?"))


class TestNonCommandsFallThrough(ChatCommandsBase):
    def test_question_returns_none(self):
        self.assertIsNone(reply("what's going on at store 4?"))

    def test_sentence_containing_keyword_is_not_a_command(self):
        # "report" inside a sentence must not trigger the summary command.
        self.assertIsNone(reply("please send me the day report for channelview"))


class TestActionCommandsStillGated(ChatCommandsBase):
    def test_close_requires_admin(self):
        self.assertIn("Only the admin", reply("close task #7", sender=NONADMIN))

    def test_admin_can_close(self):
        # task_action will call store.patch — stub it to avoid Firestore.
        orig = store.patch
        store.patch = lambda *a, **k: {}
        orig_get = store.get
        store.get = lambda c, i: {"id": 7, "status": "open"}
        try:
            self.assertIn("Closed task #7", reply("close task #7", sender=ADMIN))
        finally:
            store.patch = orig
            store.get = orig_get


if __name__ == "__main__":
    unittest.main()
