"""Unit tests for app.classifier — the rule-based message classifier.

These pin the behavior the ops bot relies on: urgent-issue detection, the
"resolved"/status-update downgrade, task vs non-task decisions, assignee
extraction, mention-stripped titles (the truncated-title regression), and
stable fingerprints for dedup.
"""
import unittest

from app.classifier import (
    classify_message,
    title_from_message,
    extract_assignees,
    make_fingerprint,
    clean_text,
    normalize_sender,
    category_string,
)


class TestPriority(unittest.TestCase):
    def test_need_gas_is_high(self):
        c = classify_message("We need gas at store 4 ASAP")
        self.assertEqual(c.priority, "high")
        self.assertTrue(c.is_task)

    def test_electrician_is_high(self):
        self.assertEqual(classify_message("call an electrician, power burned").priority, "high")

    def test_plain_please_is_medium(self):
        c = classify_message("please send the weekly numbers")
        self.assertEqual(c.priority, "medium")

    def test_neutral_message_is_normal(self):
        self.assertEqual(classify_message("here is the day report").priority, "normal")


class TestResolvedDowngrade(unittest.TestCase):
    def test_resolved_status_downgrades_priority(self):
        # "AC is working now" should NOT alert — it's a status update.
        c = classify_message("AC is working now, all good")
        self.assertEqual(c.priority, "normal")
        self.assertIn("status_update", c.categories)
        self.assertFalse(c.is_task)

    def test_still_urgent_overrides_resolved(self):
        # A resolved word plus a "still not" keeps it urgent.
        c = classify_message("fixed the sign but pump still not working")
        self.assertEqual(c.priority, "high")

    def test_power_back_on_not_high(self):
        self.assertEqual(classify_message("power back on, no issues").priority, "normal")


class TestTaskDetection(unittest.TestCase):
    def test_noted_is_not_a_task(self):
        self.assertFalse(classify_message("noted, thanks").is_task)

    def test_received_is_not_a_task(self):
        self.assertFalse(classify_message("gas delivery received").is_task)

    def test_action_verb_makes_task(self):
        self.assertTrue(classify_message("please check the printer").is_task)

    def test_high_priority_forces_task(self):
        self.assertTrue(classify_message("URGENT switch board burned").is_task)


class TestExtraction(unittest.TestCase):
    def test_money_extracted(self):
        c = classify_message("deposit was $1,250.00 today")
        self.assertIn("$1,250.00", c.extracted_amounts)

    def test_gallons_extracted(self):
        c = classify_message("short by 2,500 gallons on the BOL")
        self.assertTrue(any("2,500" in g for g in c.extracted_gallons))

    def test_price_extracted(self):
        c = classify_message("regular at 2.49 today")
        self.assertIn("2.49", c.extracted_prices)


class TestAssignees(unittest.TestCase):
    def test_admin_number_mention(self):
        self.assertEqual(extract_assignees("@Admin 4 please look into this"), "@Admin 4")

    def test_no_mention_returns_none(self):
        self.assertIsNone(extract_assignees("just a normal report"))

    def test_dedup_mentions(self):
        # MOIN twice -> one entry.
        self.assertEqual(extract_assignees("@MOIN and @MOIN again"), "@MOIN")


class TestTitle(unittest.TestCase):
    def test_mention_stripped_keeps_quantity(self):
        # Regression: the old regex turned "@Admin 2,666 gallons" into ",666 gallons".
        title = title_from_message("@Admin 2,666 gallons short")
        self.assertFalse(title.startswith(","))
        self.assertIn("2,666 gallons", title)

    def test_leading_punctuation_stripped(self):
        self.assertEqual(title_from_message("@john, fix the pump"), "fix the pump")

    def test_empty_after_strip_gets_placeholder(self):
        self.assertEqual(title_from_message("@Admin"), "Attachment/report needs review")

    def test_long_title_truncated(self):
        title = title_from_message("x" * 200)
        self.assertTrue(title.endswith("..."))
        self.assertLessEqual(len(title), 123)


class TestFingerprint(unittest.TestCase):
    def test_same_message_same_fingerprint(self):
        a = make_fingerprint("Room 4", "We need gas")
        b = make_fingerprint("Room 4", "we need   gas")  # whitespace/case normalized
        self.assertEqual(a, b)

    def test_different_rooms_differ(self):
        self.assertNotEqual(make_fingerprint("Room 4", "x"), make_fingerprint("Room 5", "x"))

    def test_verses_report_normalized_to_veeder(self):
        # "verses report" is a known OCR/typo for "veeder report".
        self.assertEqual(
            make_fingerprint("r", "verses report"),
            make_fingerprint("r", "veeder report"),
        )


class TestHelpers(unittest.TestCase):
    def test_clean_text_collapses_whitespace(self):
        self.assertEqual(clean_text("a   b\r\n\n\n\nc"), "a b\n\nc")

    def test_normalize_sender_marks_vault_record(self):
        self.assertEqual(normalize_sender("Updated on"), "[vault-update-record]")

    def test_normalize_sender_passthrough(self):
        self.assertEqual(normalize_sender("  Ali  "), "Ali")

    def test_category_string_joins(self):
        self.assertEqual(category_string(["a", "b"]), "a;b")


if __name__ == "__main__":
    unittest.main()
