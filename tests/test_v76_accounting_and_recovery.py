from __future__ import annotations

import unittest

import engine
import screening_engine


class HongKongAccountingTests(unittest.TestCase):
    def test_traditional_and_english_income_labels(self):
        self.assertEqual(engine._metric_kind("本公司擁有人應佔溢利"), "parent_profit")
        self.assertEqual(
            engine._metric_kind("Profit for the year attributable to owners of the Company"),
            "parent_profit",
        )
        self.assertEqual(engine._metric_kind("Revenue from contracts with customers"), "revenue")
        self.assertEqual(engine._metric_kind("經調整溢利"), "adjusted_profit")

    def test_hk_units_are_converted_to_hundred_million(self):
        self.assertEqual(engine._unit_multiplier("", "Amounts expressed in HK$ million")[0], 0.01)
        self.assertEqual(engine._unit_multiplier("", "(Expressed in RMB'000)")[0], 0.00001)

    def test_hk_balance_sheet_labels(self):
        self.assertEqual(engine._bs_kind("資產總值"), "total_assets")
        self.assertEqual(engine._bs_kind("Total equity"), "total_equity")

    def test_hk_financial_pages_are_candidates(self):
        pages = [
            engine.ExtractedPage(1, "Chairman's Statement"),
            engine.ExtractedPage(9, "財務摘要\n收益\n本公司擁有人應佔溢利"),
        ]
        self.assertEqual(engine._financial_candidate_pages(pages)[0].page, 9)


class ScreeningRecoveryTests(unittest.TestCase):
    def test_truncated_json_string_is_closed(self):
        payload = screening_engine._parse_json('{"checks":[{"id":"H1","finding":"未见硬阈值')
        self.assertEqual(payload["checks"][0]["id"], "H1")
        self.assertTrue(payload["checks"][0]["finding"].startswith("未见"))


if __name__ == "__main__":
    unittest.main()
