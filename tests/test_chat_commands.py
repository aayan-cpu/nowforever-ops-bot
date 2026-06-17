"""Tests for the bare-keyword command router (WORK.md: 'Dead single-word commands').

Run: `py -m unittest tests.test_chat_commands` from the repo root.

Early logs showed "report"/"reports"/"alerts" replying just "Got it." instead of
acting: "report"/"reports" matched no handler at all, and any recognized keyword
fell back to a blank ack when gated to a non-admin or while the brain was offline.
These tests pin the fix: bare keywords either hit a real handler or produce a
helpful hint — never a silent "Got it.".

The report handlers hit Firestore, so we patch them with in-memory fakes.
"""
import types
import unittest

from app import chat_live


def _msg(text, sender="aayan@khawarsons.com"):
    return {"message": text, "sender": sender, "room_name": "11 N&F Windchase"}


def _classif(priority="normal", categories=("general",), assigned_hint=""):
    return types.SimpleNamespace(priority=priority, categories=list(categories),
                                 assigned_hint=assigned_hint)


class _FakeReports:
    """Patches the report functions chat_live imported, restoring them after."""

    def __enter__(self):
        self._orig = (chat_live.dashboard, chat_live.high_priority, chat_live.open_tasks)
        chat_live.dashboard = lambda db=None: {
            "totals": {"messages": 5},
            "tasks": [{"status": "open", "count": 3}],
            "priorities": [{"priority": "high", "count": 1}],
            "top_rooms": [{"room_name": "11 N&F Windchase", "tasks": 2, "high": 1}],
        }
        chat_live.high_priority = lambda db=None, limit=8: [
            {"room_name": "24 Galveston", "message": "needs gas now"}]
        chat_live.open_tasks = lambda db=None, limit=10: [
            {"id": 7, "room_name": "9 Bissonnet", "task_title": "ice machine down"}]
        return self

    def __exit__(self, *a):
        chat_live.dashboard, chat_live.high_priority, chat_live.open_tasks = self._orig


class KeywordRecognitionTests(unittest.TestCase):
    def test_recognizes_bare_keywords(self):
        for kw in ("report", "reports", "alerts", "tasks", "summary",
                   "Report.", "  TASKS  ", "NowForever Ops Bot report"):
            self.assertTrue(chat_live.is_readonly_command(kw), kw)

    def test_does_not_treat_sentences_as_commands(self):
        for s in ("what's going on at 4?", "please report the leak", "tasks are piling up"):
            self.assertFalse(chat_live.is_readonly_command(s), s)


class ReportCommandTests(unittest.TestCase):
    def test_report_and_reports_hit_the_summary_handler_for_admin(self):
        with _FakeReports():
            for kw in ("report", "reports", "Reports", "NowForever Ops Bot report"):
                reply = chat_live.build_reply(_msg(kw), None, None)
                self.assertIsNotNone(reply, kw)              # not a blank ack
                self.assertIn("Ops Summary", reply, kw)
                self.assertNotEqual(reply, "Got it.", kw)

    def test_alerts_and_tasks_still_work_for_admin(self):
        with _FakeReports():
            self.assertIn("High Priority", chat_live.build_reply(_msg("alerts"), None, None))
            self.assertIn("Open Tasks", chat_live.build_reply(_msg("tasks"), None, None))

    def test_readonly_commands_route_to_brain_for_non_admin(self):
        with _FakeReports():
            for kw in ("report", "alerts", "tasks", "summary"):
                self.assertIsNone(
                    chat_live.build_reply(_msg(kw, sender="captain@store.com"), None, None), kw)


class DefaultAckTests(unittest.TestCase):
    def test_recognized_keyword_gets_guidance_not_blank_ack(self):
        # Non-admin / brain-offline path: must not be a silent "Got it.".
        for kw in ("report", "reports", "alerts", "tasks"):
            ack = chat_live.default_ack(_msg(kw), _classif(), None)
            self.assertNotEqual(ack, "Got it.", kw)
            self.assertIn("summary", ack.lower(), kw)

    def test_plain_chitchat_still_acks(self):
        self.assertEqual(chat_live.default_ack(_msg("hello there"), _classif(), None), "Got it.")

    def test_task_and_high_priority_acks_unchanged(self):
        self.assertIn("Logged", chat_live.default_ack(_msg("report"), _classif(priority="high"), 12))
        self.assertIn("High-priority",
                      chat_live.default_ack(_msg("the pump exploded"), _classif(priority="high"), None))


if __name__ == "__main__":
    unittest.main()
