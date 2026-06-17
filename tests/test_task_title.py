"""Regression tests for task-title extraction (WORK.md: 'Truncated task titles').

Run: `py -m unittest tests.test_task_title` from the repo root.

The old mention-stripping regex in classifier.title_from_message included a space
in its character class, so it ate past an @mention into the following words and
chopped off leading characters of the real title (e.g. "@Admin 2,666 gallons" ->
",666 gallons"). These tests pin the fixed behaviour.
"""
import unittest

from app.classifier import title_from_message, classify_message


class TitleFromMessageTests(unittest.TestCase):
    def test_does_not_eat_quantity_after_admin_mention(self):
        # Reproduces logged failure "#170 ,666 gallons".
        self.assertEqual(
            title_from_message("@Admin 2,666 gallons short on the BOL"),
            "2,666 gallons short on the BOL",
        )

    def test_does_not_eat_word_after_admin_mention(self):
        # Reproduces logged failure "#156 't the customers".
        self.assertEqual(
            title_from_message("@Admin didn't the customers complain about pump 3"),
            "didn't the customers complain about pump 3",
        )

    def test_strips_known_numbered_admin_alias(self):
        self.assertEqual(
            title_from_message("@Admin 4 Ice storage not working"),
            "Ice storage not working",
        )

    def test_strips_generic_single_token_mention(self):
        self.assertEqual(
            title_from_message("@john please check pump 5"),
            "please check pump 5",
        )

    def test_strips_dangling_punctuation_left_by_mention(self):
        self.assertEqual(title_from_message("@john, fix pump"), "fix pump")

    def test_keeps_message_without_mention_intact(self):
        self.assertEqual(
            title_from_message("No mention here just text"),
            "No mention here just text",
        )

    def test_preserves_leading_money(self):
        self.assertEqual(
            title_from_message("$2,666 deposit pending"),
            "$2,666 deposit pending",
        )

    def test_empty_falls_back_to_placeholder(self):
        self.assertEqual(title_from_message("@Admin"), "Attachment/report needs review")
        self.assertEqual(title_from_message(""), "Attachment/report needs review")

    def test_long_title_is_truncated_with_ellipsis(self):
        out = title_from_message("x" * 200)
        self.assertTrue(out.endswith("..."))
        self.assertEqual(len(out), 123)  # 120 chars + "..."

    def test_classify_message_carries_clean_title(self):
        c = classify_message("@Admin 2,666 gallons short on the BOL", room_name="Windchase")
        self.assertEqual(c.task_title, "2,666 gallons short on the BOL")


if __name__ == "__main__":
    unittest.main()
