"""Tests for missing/overdue daily-report detection + reminders
(WORK.md: 'Missing/overdue report detection + reminders').

Run: `py -m unittest tests.test_missing_reports` from the repo root.

`reports.report_status` is pure (messages + as_of in, standing out) so it tests
without Firestore. The digest jobs are exercised with the report lookup and
chat poster patched, so no network/store is touched.
"""
import unittest

from app import reports, digests


def _m(room, day=None, report=False, cats="general"):
    if report:
        cats = "daily_shift_report;" + cats
    return {"room_name": room, "categories": cats,
            "created_at": (day + "T12:00:00Z") if day else ""}


AS_OF = "2026-06-17"


class ReportStatusTests(unittest.TestCase):
    def test_reported_today_vs_missing(self):
        msgs = [
            _m("4 Channelview", AS_OF, report=True),
            _m("9 Bissonnet", AS_OF, report=False),   # chatter, not a report
        ]
        st = reports.report_status(msgs, AS_OF)
        self.assertIn("4 Channelview", st["reported"])
        self.assertIn("9 Bissonnet", st["missing"])
        self.assertNotIn("4 Channelview", st["missing"])

    def test_canonical_grouping_counts_site_once(self):
        # Same station spelled two ways; one of them filed today's report.
        msgs = [_m("11", AS_OF, report=False),
                _m("11 N&F Windchase", AS_OF, report=True)]
        st = reports.report_status(msgs, AS_OF)
        self.assertEqual(st["sites"], ["11 N&F Windchase"])
        self.assertEqual(st["reported"], ["11 N&F Windchase"])
        self.assertEqual(st["missing"], [])

    def test_non_stations_excluded(self):
        msgs = [_m("All Captains Chat", AS_OF, report=True),
                _m("spaces/AAAA", AS_OF, report=True),
                _m("Direct message", AS_OF, report=True)]
        st = reports.report_status(msgs, AS_OF)
        self.assertEqual(st["sites"], [])

    def test_overdue_detection(self):
        msgs = [
            _m("4 Channelview", AS_OF, report=True),        # today -> not overdue
            _m("9 Bissonnet", "2026-06-14", report=True),   # 3 days ago -> overdue
            _m("24 Galveston", report=False),               # never reported -> overdue
        ]
        st = reports.report_status(msgs, AS_OF, overdue_days=2)
        overdue = {o["site"]: o for o in st["overdue"]}
        self.assertNotIn("4 Channelview", overdue)
        self.assertEqual(overdue["9 Bissonnet"]["days_since"], 3)
        self.assertEqual(overdue["9 Bissonnet"]["last_report"], "2026-06-14")
        self.assertIsNone(overdue["24 Galveston"]["last_report"])
        self.assertIsNone(overdue["24 Galveston"]["days_since"])

    def test_latest_report_date_wins(self):
        # Two reports on file; the newest (06-16) must drive days_since, not 06-10.
        msgs = [_m("27 Fry", "2026-06-10", report=True),
                _m("27 Fry", "2026-06-16", report=True)]
        st = reports.report_status(msgs, AS_OF, overdue_days=1)
        self.assertEqual(st["overdue"][0]["site"], "27 Fry")
        self.assertEqual(st["overdue"][0]["last_report"], "2026-06-16")
        self.assertEqual(st["overdue"][0]["days_since"], 1)  # 06-17 - 06-16

    def test_empty(self):
        st = reports.report_status([], AS_OF)
        self.assertEqual((st["sites"], st["reported"], st["missing"], st["overdue"]),
                         ([], [], [], []))


class _PatchDigests:
    """Patch the report lookup + chat poster digests uses; capture posts."""

    def __init__(self, status):
        self.status = status
        self.posts = []

    def __enter__(self):
        self._orig = (reports.missing_daily_reports, digests.chat_media.post_to_space)
        reports.missing_daily_reports = lambda *a, **k: self.status
        digests.chat_media.post_to_space = lambda space, text: (self.posts.append((space, text)) or True)
        return self

    def __exit__(self, *a):
        reports.missing_daily_reports, digests.chat_media.post_to_space = self._orig


class ReminderJobTests(unittest.TestCase):
    def test_reminder_posts_to_captains_when_missing(self):
        status = {"missing": ["9 Bissonnet", "24 Galveston"], "overdue": []}
        with _PatchDigests(status) as p:
            res = digests.report_reminder()
        self.assertEqual(res["missing"], 2)
        self.assertEqual(len(p.posts), 1)
        space, text = p.posts[0]
        self.assertEqual(space, digests.REPORT_REMINDER_SPACE)
        self.assertIn("9 Bissonnet", text)
        self.assertIn("reminder", text.lower())

    def test_reminder_silent_when_all_reported(self):
        with _PatchDigests({"missing": [], "overdue": []}) as p:
            res = digests.report_reminder()
        self.assertEqual(res.get("skipped"), "all reported")
        self.assertEqual(p.posts, [])

    def test_missing_reports_includes_overdue_block(self):
        status = {"missing": ["9 Bissonnet"],
                  "overdue": [{"site": "9 Bissonnet", "last_report": "2026-06-14", "days_since": 3}]}
        with _PatchDigests(status) as p:
            res = digests.missing_reports()
        self.assertEqual(res["overdue"], 1)
        _, text = p.posts[0]
        self.assertIn("Overdue", text)
        self.assertIn("2026-06-14", text)


if __name__ == "__main__":
    unittest.main()
