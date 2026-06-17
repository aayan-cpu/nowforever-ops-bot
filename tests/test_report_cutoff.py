"""Tests for report cutoff + late flagging (WORK.md: 'Report cutoff + late flagging').

Run: `py -m unittest tests.test_report_cutoff` from the repo root.

`reports.report_lateness` is pure (messages + injected now + cutoffs in,
classification out) so it tests without Firestore or wall-clock. June is US
Central Daylight Time (UTC-5), so a UTC instant of 03:30Z on the 18th is
22:30 local on the 17th.
"""
import unittest
from datetime import datetime, timezone

from app import reports, digests


def _m(room, ts_iso, report=True):
    cats = "daily_shift_report;general" if report else "general"
    return {"room_name": room, "categories": cats, "timestamp_raw": ts_iso}


# 2026-06-18T03:30Z == 2026-06-17 22:30 Central (CDT). Cutoff default 22:00.
NOW = datetime(2026, 6, 18, 3, 30, tzinfo=timezone.utc)


class ReportLatenessTests(unittest.TestCase):
    def _sample(self):
        return [
            _m("4 Channelview", "2026-06-18T02:00:00Z"),   # 21:00 local -> on time
            _m("9 Bissonnet", "2026-06-18T03:45:00Z"),     # 22:45 local -> late
            _m("11 N&F Windchase", "2026-06-18T01:00:00Z", report=False),  # no report
        ]

    def test_on_time_late_and_missing(self):
        r = reports.report_lateness(self._sample(), NOW)
        self.assertEqual(r["as_of"], "2026-06-17")
        self.assertEqual(r["on_time"], ["4 Channelview"])
        self.assertEqual(r["late"], [{"site": "9 Bissonnet", "filed": "22:45", "cutoff": "22:00"}])
        self.assertEqual(r["missing_past_cutoff"], [{"site": "11 N&F Windchase", "cutoff": "22:00"}])

    def test_per_site_cutoff_override(self):
        # Give site 9 a later cutoff; its 22:45 report is now on time.
        r = reports.report_lateness(self._sample(), NOW, cutoffs={"9": "23:00"})
        self.assertIn("9 Bissonnet", r["on_time"])
        self.assertEqual(r["late"], [])

    def test_before_cutoff_missing_not_flagged(self):
        # 2026-06-18T00:30Z == 2026-06-17 19:30 local — before the 22:00 cutoff.
        early = datetime(2026, 6, 18, 0, 30, tzinfo=timezone.utc)
        msgs = [_m("11 N&F Windchase", "2026-06-18T00:00:00Z", report=False)]
        r = reports.report_lateness(msgs, early)
        self.assertEqual(r["missing_past_cutoff"], [])  # window still open
        self.assertEqual(r["late"], [])

    def test_all_on_time(self):
        msgs = [_m("4 Channelview", "2026-06-18T01:00:00Z")]  # 20:00 local
        r = reports.report_lateness(msgs, NOW)
        self.assertEqual(r["late"], [])
        self.assertEqual(r["missing_past_cutoff"], [])
        self.assertEqual(r["on_time"], ["4 Channelview"])

    def test_non_stations_ignored(self):
        msgs = [_m("All Captains Chat", "2026-06-18T03:45:00Z"),
                _m("spaces/AAAA", "2026-06-18T03:45:00Z")]
        r = reports.report_lateness(msgs, NOW)
        self.assertEqual((r["on_time"], r["late"], r["missing_past_cutoff"]), ([], [], []))

    def test_central_offset_dst(self):
        # Sanity-check the DST boundary helper: July = CDT (-5), January = CST (-6).
        self.assertEqual(reports._central_offset_hours(datetime(2026, 7, 1, tzinfo=timezone.utc)), -5)
        self.assertEqual(reports._central_offset_hours(datetime(2026, 1, 1, tzinfo=timezone.utc)), -6)


class _PatchLateness:
    def __init__(self, status):
        self.status = status
        self.posts = []

    def __enter__(self):
        self._orig = (reports.daily_report_lateness, digests.chat_media.post_to_space)
        reports.daily_report_lateness = lambda *a, **k: self.status
        digests.chat_media.post_to_space = lambda space, text: (self.posts.append((space, text)) or True)
        return self

    def __exit__(self, *a):
        reports.daily_report_lateness, digests.chat_media.post_to_space = self._orig


class LateReportsJobTests(unittest.TestCase):
    def test_posts_when_late_or_missing(self):
        status = {"on_time": ["4 Channelview"],
                  "late": [{"site": "9 Bissonnet", "filed": "22:45", "cutoff": "22:00"}],
                  "missing_past_cutoff": [{"site": "11 N&F Windchase", "cutoff": "22:00"}]}
        with _PatchLateness(status) as p:
            res = digests.late_reports()
        self.assertEqual((res["late"], res["missing"]), (1, 1))
        self.assertEqual(p.posts[0][0], digests.ADMIN_DM)
        text = p.posts[0][1]
        self.assertIn("9 Bissonnet", text)
        self.assertIn("22:45", text)
        self.assertIn("11 N&F Windchase", text)

    def test_quiet_when_all_on_time(self):
        with _PatchLateness({"on_time": ["4 Channelview"], "late": [], "missing_past_cutoff": []}) as p:
            res = digests.late_reports()
        self.assertEqual(res.get("skipped"), "all on time")
        self.assertEqual(p.posts, [])


if __name__ == "__main__":
    unittest.main()
