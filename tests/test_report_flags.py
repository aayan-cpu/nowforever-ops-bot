import unittest
from app.chat_live import disallowed_report_flags


class DisallowedReportFlagsTests(unittest.TestCase):
    def test_clean_report_no_flags(self):
        self.assertEqual(disallowed_report_flags({"cash_vendor": 0, "company_gas": 0}), [])
        self.assertEqual(disallowed_report_flags({"cash_vendor": None, "company_gas": None}), [])
        self.assertEqual(disallowed_report_flags({}), [])

    def test_cash_vendor_flagged(self):
        flags = disallowed_report_flags({"cash_vendor": 1.0, "company_gas": 0})
        self.assertEqual(len(flags), 1)
        self.assertIn("CASH VENDOR", flags[0])
        self.assertIn("1.00", flags[0])

    def test_company_gas_flagged(self):
        flags = disallowed_report_flags({"cash_vendor": 0, "company_gas": 25.5})
        self.assertEqual(len(flags), 1)
        self.assertIn("COMPANY GAS", flags[0])

    def test_both_flagged(self):
        flags = disallowed_report_flags({"cash_vendor": 1, "company_gas": 1})
        self.assertEqual(len(flags), 2)

    def test_coerces_money_strings(self):
        flags = disallowed_report_flags({"cash_vendor": "$1,200.00", "company_gas": "0"})
        self.assertEqual(len(flags), 1)
        self.assertIn("1,200.00", flags[0])


if __name__ == "__main__":
    unittest.main()
