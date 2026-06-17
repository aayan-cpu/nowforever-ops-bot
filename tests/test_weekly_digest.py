"""Tests for the weekly per-room digest job (WORK.md: 'Weekly digest job').

Run: `py -m unittest tests.test_weekly_digest` from the repo root.

Covers the pure builder (_build_weekly_digest) and the /cron wiring (JOBS entry).
weekly_digest() itself is not invoked here because it hits Firestore + Google Chat.
"""
import unittest
from datetime import datetime, timezone

from app import digests

NOW = datetime(2026, 6, 17, 12, 0, 0, tzinfo=timezone.utc)


def _iso(days_ago: float) -> str:
    return (datetime.fromtimestamp(NOW.timestamp() - days_ago * 86400, tz=timezone.utc)
            .isoformat().replace("+00:00", "Z"))


class WeeklyDigestBuilderTests(unittest.TestCase):
    def test_empty_is_all_clear(self):
        self.assertIn("all clear", digests._build_weekly_digest([], now=NOW))

    def test_groups_and_counts_per_room(self):
        tasks = [
            {"room_name": "4 Channelview", "priority": "high", "task_title": "Pump down", "created_at": _iso(1)},
            {"room_name": "4 Channelview", "priority": "normal", "task_title": "Restock", "created_at": _iso(2)},
            {"room_name": "11 Windchase", "priority": "normal", "task_title": "Sign", "created_at": _iso(10)},
        ]
        out = digests._build_weekly_digest(tasks, now=NOW)
        self.assertIn("*4 Channelview* — 2 open, 1 high, 2 new this week", out)
        # 11 Windchase task is 10 days old -> open but not "new this week"
        self.assertIn("*11 Windchase* — 1 open", out)
        self.assertNotIn("new this week", out.split("\n")[-1])

    def test_high_priority_room_sorts_first(self):
        tasks = [
            {"room_name": "Quiet", "priority": "normal", "task_title": "x", "created_at": _iso(1)},
            {"room_name": "Busy", "priority": "high", "task_title": "Fire", "created_at": _iso(1)},
        ]
        out = digests._build_weekly_digest(tasks, now=NOW)
        self.assertLess(out.index("*Busy*"), out.index("*Quiet*"))

    def test_lists_up_to_three_high_titles(self):
        tasks = [
            {"room_name": "R", "priority": "high", "task_title": f"issue {i}", "created_at": _iso(1)}
            for i in range(5)
        ]
        out = digests._build_weekly_digest(tasks, now=NOW)
        self.assertEqual(out.count("  • issue"), 3)

    def test_falls_back_to_task_text_when_no_title(self):
        tasks = [{"room_name": "R", "priority": "high", "task_text": "from text", "created_at": _iso(1)}]
        out = digests._build_weekly_digest(tasks, now=NOW)
        self.assertIn("  • from text", out)

    def test_missing_room_name_bucketed_as_unknown(self):
        out = digests._build_weekly_digest([{"priority": "normal", "created_at": _iso(1)}], now=NOW)
        self.assertIn("*(unknown)*", out)


class WeeklyDigestWiringTests(unittest.TestCase):
    def test_registered_in_jobs(self):
        self.assertIn("weekly-digest", digests.JOBS)
        self.assertIs(digests.JOBS["weekly-digest"], digests.weekly_digest)


if __name__ == "__main__":
    unittest.main()
