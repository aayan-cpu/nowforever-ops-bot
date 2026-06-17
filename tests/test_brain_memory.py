"""Tests for per-user multi-turn memory (WORK.md: 'Multi-turn conversation memory').

Run: `py -m unittest tests.test_brain_memory` from the repo root.

Conversation memory is now keyed by space + sender, so in a shared room each
person keeps their own short-term thread (their follow-ups resolve against their
own turns, not a roommate's). Backed by the in-memory FakeStore — no Firestore.
"""
import unittest

from app import brain
from tests._fakestore import FakeStore


class ConvIdTests(unittest.TestCase):
    def test_distinct_per_user_same_space(self):
        self.assertNotEqual(brain._conv_id("spaces/X", "alice@x"),
                            brain._conv_id("spaces/X", "bob@x"))

    def test_sender_case_insensitive(self):
        self.assertEqual(brain._conv_id("spaces/X", "Alice@X"),
                         brain._conv_id("spaces/X", "alice@x"))

    def test_no_slashes_in_id(self):
        self.assertNotIn("/", brain._conv_id("spaces/AAA/threads/1", "u@x"))


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.fs = FakeStore().install()

    def tearDown(self):
        self.fs.restore()

    def test_threads_isolated_by_user(self):
        brain._save_turn("spaces/room", "alice@x", "what about site 11?", "site 11 needs gas")
        brain._save_turn("spaces/room", "bob@x", "and deposits?", "all deposited")
        alice = brain._load_turns("spaces/room", "alice@x")
        bob = brain._load_turns("spaces/room", "bob@x")
        self.assertEqual(len(alice), 2)
        self.assertEqual(len(bob), 2)
        self.assertIn("site 11 needs gas", alice[1]["content"])
        self.assertNotIn("site 11", str(bob))  # bob never sees alice's thread

    def test_roundtrip_same_user(self):
        brain._save_turn("spaces/dm1", "owner@x", "hi", "hello")
        turns = brain._load_turns("spaces/dm1", "owner@x")
        self.assertEqual([t["role"] for t in turns], ["user", "assistant"])

    def test_caps_at_three_exchanges(self):
        for i in range(5):
            brain._save_turn("spaces/r", "u@x", f"q{i}", f"a{i}")
        turns = brain._load_turns("spaces/r", "u@x")
        self.assertEqual(len(turns), 6)            # last 3 exchanges only
        self.assertEqual(turns[0]["content"], "q2")  # q0/q1 rolled off

    def test_no_space_returns_empty(self):
        self.assertEqual(brain._load_turns(None, "u@x"), [])
        brain._save_turn(None, "u@x", "q", "a")  # no-op, must not raise


if __name__ == "__main__":
    unittest.main()
