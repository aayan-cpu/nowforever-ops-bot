"""Tests for the single-word command router (WORK.md: 'Dead single-word commands').

Run: `py -m unittest tests.test_dead_commands` from the repo root.

Bare keywords like 'reports'/'report' used to match no handler and fall back to a
blank "Got it." ack. They now hit real handlers (or fall through to the brain for
non-admins), and the catch-all ack is actionable rather than blank.
"""
import types
import unittest
from unittest.mock import patch

from app import chat_live

ADMIN = "aayan@khawarsons.com"      # in default OPS_ADMIN_EMAILS (owner)
CAPTAIN = "captain@store.com"        # not an admin


def _msg(text, sender=ADMIN, room="4 Channelview"):
    return {"message": text, "sender": sender, "room_name": room}


def _classified(priority="normal"):
    return types.SimpleNamespace(priority=priority, categories=["general"], assigned_hint=None)


class HelpCommandTests(unittest.TestCase):
    def test_help_available_to_everyone(self):
        self.assertEqual(chat_live.build_reply(_msg("help", CAPTAIN), None, None), chat_live.HELP_TEXT)
        self.assertEqual(chat_live.build_reply(_msg("help", ADMIN), None, None), chat_live.HELP_TEXT)

    def test_help_tolerates_trailing_punctuation(self):
        self.assertEqual(chat_live.build_reply(_msg("help!", CAPTAIN), None, None), chat_live.HELP_TEXT)

    def test_commands_synonym(self):
        self.assertEqual(chat_live.build_reply(_msg("commands", CAPTAIN), None, None), chat_live.HELP_TEXT)


class ReportsCommandTests(unittest.TestCase):
    def test_reports_keyword_recognized_for_admin(self):
        rows = [{"room_name": "4 Channelview", "report_date": "2026-06-16", "total_sales": 5000}]
        with patch("app.chat_live.store.list_all", return_value=rows) as m:
            out = chat_live.build_reply(_msg("reports", ADMIN), None, None)
        m.assert_called_once_with("day_reports")
        self.assertIn("Latest daily reports", out)
        self.assertIn("4 Channelview", out)

    def test_report_singular_recognized(self):
        with patch("app.chat_live.store.list_all", return_value=[]) as m:
            out = chat_live.build_reply(_msg("report", ADMIN), None, None)
        m.assert_called_once_with("day_reports")
        self.assertIn("No daily-report figures", out)

    def test_reports_falls_through_to_brain_for_non_admin(self):
        # Non-admin path returns None (caller routes to the AI brain) without any I/O.
        with patch("app.chat_live.store.list_all") as m:
            self.assertIsNone(chat_live.build_reply(_msg("reports", CAPTAIN), None, None))
        m.assert_not_called()


class TaskKeywordTests(unittest.TestCase):
    def test_singular_task_recognized_for_admin(self):
        rows = [{"id": 7, "room_name": "11 Windchase", "task_title": "Fix pump"}]
        with patch("app.chat_live.open_tasks", return_value=rows):
            out = chat_live.build_reply(_msg("task", ADMIN), None, None)
        self.assertIn("Open Tasks", out)
        self.assertIn("#7", out)


class FallThroughTests(unittest.TestCase):
    def test_conversational_message_returns_none(self):
        self.assertIsNone(chat_live.build_reply(_msg("how are you doing today", ADMIN), None, None))


class DefaultAckTests(unittest.TestCase):
    def test_no_task_ack_is_not_blank(self):
        out = chat_live.default_ack(_msg("noted"), _classified("normal"), None)
        self.assertNotEqual(out, "Got it.")
        self.assertIn("summary", out)
        self.assertIn("reports", out)

    def test_task_ack_reports_task_number(self):
        out = chat_live.default_ack(_msg("pump down"), _classified("high"), 42)
        self.assertIn("#42", out)


if __name__ == "__main__":
    unittest.main()
