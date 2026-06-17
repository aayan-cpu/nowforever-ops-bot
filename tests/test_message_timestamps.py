"""Tests for message send-time handling (WORK.md: 'Message timestamps in ingestion').

Run: `py -m unittest tests.test_message_timestamps` from the repo root.

Covers store.normalize_ts / store.age_minutes (pure) and that
chat_live.extract_chat_event carries a normalized `sent_at` through.
"""
import unittest
from datetime import datetime, timezone

from app import store, chat_live

FIXED = datetime(2026, 6, 17, 12, 0, 0, tzinfo=timezone.utc)


class NormalizeTsTests(unittest.TestCase):
    def test_rfc3339_zulu(self):
        self.assertEqual(store.normalize_ts("2026-06-17T15:30:00Z"), "2026-06-17T15:30:00+00:00")

    def test_offset_converted_to_utc(self):
        self.assertEqual(store.normalize_ts("2026-06-17T10:30:00-05:00"), "2026-06-17T15:30:00+00:00")

    def test_space_separated_naive_treated_as_utc(self):
        self.assertEqual(store.normalize_ts("2026-06-17 15:30:00"), "2026-06-17T15:30:00+00:00")

    def test_date_only(self):
        self.assertEqual(store.normalize_ts("2026-06-17"), "2026-06-17T00:00:00+00:00")

    def test_us_slash_format(self):
        self.assertEqual(store.normalize_ts("06/17/2026 15:30"), "2026-06-17T15:30:00+00:00")

    def test_epoch_seconds(self):
        expected = datetime.fromtimestamp(1750000000, timezone.utc).isoformat()
        self.assertEqual(store.normalize_ts("1750000000"), expected)

    def test_epoch_millis(self):
        expected = datetime.fromtimestamp(1750000000000 / 1000, timezone.utc).isoformat()
        self.assertEqual(store.normalize_ts("1750000000000"), expected)

    def test_blank_falls_back_to_now(self):
        self.assertEqual(store.normalize_ts("", now=FIXED), FIXED.isoformat())
        self.assertEqual(store.normalize_ts(None, now=FIXED), FIXED.isoformat())

    def test_garbage_falls_back_to_now(self):
        self.assertEqual(store.normalize_ts("last tuesday-ish", now=FIXED), FIXED.isoformat())

    def test_output_is_always_parseable(self):
        for raw in ["2026-06-17T15:30:00Z", "1750000000", "", "garbage", "2026-06-17"]:
            datetime.fromisoformat(store.normalize_ts(raw, now=FIXED))  # must not raise


class AgeMinutesTests(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(store.age_minutes("2026-06-17T11:30:00+00:00", now=FIXED), 30.0)

    def test_naive_treated_as_utc(self):
        self.assertEqual(store.age_minutes("2026-06-17T11:00:00", now=FIXED), 60.0)

    def test_unparseable_is_none(self):
        self.assertIsNone(store.age_minutes("nope", now=FIXED))
        self.assertIsNone(store.age_minutes(None, now=FIXED))


class ExtractChatEventTests(unittest.TestCase):
    def _event(self, create_time):
        return {
            "type": "MESSAGE",
            "message": {"name": "spaces/x/messages/1", "text": "Day report attached", "createTime": create_time},
            "space": {"displayName": "4 Channelview"},
            "user": {"email": "captain@store.com"},
        }

    def test_sent_at_normalized_from_create_time(self):
        msg = chat_live.extract_chat_event(self._event("2026-06-17T15:30:00Z"))
        self.assertEqual(msg["sent_at"], "2026-06-17T15:30:00+00:00")
        self.assertEqual(msg["timestamp_raw"], "2026-06-17T15:30:00Z")  # raw preserved

    def test_sent_at_present_even_without_create_time(self):
        ev = {"type": "MESSAGE", "message": {"name": "spaces/x/messages/2", "text": "hi"},
              "space": {"displayName": "4 Channelview"}, "user": {"email": "c@s.com"}}
        msg = chat_live.extract_chat_event(ev)
        # falls back to a generated ISO timestamp; must be parseable.
        datetime.fromisoformat(msg["sent_at"])


if __name__ == "__main__":
    unittest.main()
