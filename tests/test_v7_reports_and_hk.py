from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import engine
import market_data
import cninfo
from engine import CompanyRow, KeyFinancialMetrics
from hkex import HkexClient, _is_wanted_report, _year_matches, is_hk_stock_code, normalise_hk_code


class CompleteDeepReportTests(unittest.TestCase):
    def test_fallback_report_remains_retryable_but_evidence_gap_does_not(self):
        row=CompanyRow(2,'300750','宁德时代',{})
        fallback=engine._comment_payload(row,Path('report.md'),'半年度报告',2025,'需复核','报告包含兜底或未生成内容')
        evidence_gap=engine._comment_payload(row,Path('report.md'),'半年度报告',2025,'需复核','未取得上期原版，历史对比存在缺口')
        self.assertTrue(fallback['retryable'])
        self.assertFalse(evidence_gap['retryable'])

    def test_repairs_present_but_interrupted_table_chapter(self):
        sections = {n: f'## {n}、{title}\n\n' + '可追溯的完整正文，相关证据来自PDF第7页，缺少材料时明确无法核验。'
                    for n, title in zip(engine.DEEP_SECTION_NUMERALS, engine.DEEP_SECTION_TITLES)}
        sections['六'] = '## 六、关键数字与口径核验\n\n| 指标 | 公式及期间/权益'
        initial = engine._assemble_deep_report('# 报告', sections)
        repair = '## 六、关键数字与口径核验\n\n| 指标 | 结果 |\n|---|---|\n| ROE | 未取得期初权益，无法核验该指标，需补充上期报告（PDF第7页） |'
        self.assertEqual(engine.incomplete_deep_report_sections(sections), ['六'])
        # First repair is also truncated: the single-chapter retry must recover.
        responses = iter([initial, sections['六'], repair])
        fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw:
            SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=next(responses)))], usage=None))))
        with patch.object(engine, 'OpenAI', return_value=fake):
            report, *_ = engine.generate_deep_report_markdown(CompanyRow(2, '300750', '宁德时代', {}), [],
                KeyFinancialMetrics(), 'key', 'model', 'https://example.invalid', '半年度报告', 2025, '', [], KeyFinancialMetrics(), '')
        _, actual = engine.split_deep_report(report)
        self.assertEqual(engine.incomplete_deep_report_sections(actual), [])
        self.assertIn('需补充上期报告', actual['六'])
        self.assertEqual(actual['三'], sections['三'])

    def test_stub_always_contains_all_current_chapters(self) -> None:
        report = engine.stub_deep_report(
            CompanyRow(2, "00700.HK", "腾讯控股", {}),
            KeyFinancialMetrics(revenue_billion=1.0),
            "年度报告",
            2025,
            "测试降级",
        )
        self.assertEqual(engine.missing_deep_report_sections(report), [])
        _preamble, sections = engine.split_deep_report(report)
        self.assertEqual(tuple(sections), engine.DEEP_SECTION_NUMERALS)

    def test_missing_section_detector_catches_previous_failure_shape(self) -> None:
        broken = "# 报告\n\n## 一、公司画像与数据来源\nA\n\n## 九、财务指标速览\nB\n\n## 十、风险清单与造假嫌疑排查\nC\n\n## 十一、财报预期差与市场反应\nD"
        missing = engine.missing_deep_report_sections(broken)
        self.assertEqual(missing, ["二", "三", "四", "五", "六", "七", "八", "十二"])

    def test_generation_repairs_the_previous_failure_shape(self) -> None:
        responses = iter(
            [
                "# 报告\n\n## 一、研究结论与关键变化\nAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\n\n## 四、风险、矛盾与反证\nBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB\n\n## 五、情景与后续跟踪\nCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC",
                "## 二、经营驱动与盈利质量\nBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB\n\n## 三、资产质量、现金与偿债\nCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC",
                "## 六、关键数字与口径核验\nFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF\n\n## 七、证据账本与研究边界\nGGGGGGGGGGGGGGGGGGGGGGGGGGGGGG",
            ]
        )

        class Completions:
            @staticmethod
            def create(**_kwargs):
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=next(responses)))],
                    usage=SimpleNamespace(prompt_tokens=10, completion_tokens=10),
                )

        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
        with patch.object(engine, "OpenAI", return_value=fake_client):
            report, input_tokens, output_tokens, _cost = engine.generate_deep_report_markdown(
                CompanyRow(2, "00700.HK", "腾讯控股", {}),
                [],
                KeyFinancialMetrics(),
                "key",
                "model",
                "https://example.invalid",
                "年度报告",
                2025,
                "",
                [],
                KeyFinancialMetrics(),
                "2026-04-09",
            )
        self.assertEqual(engine.missing_deep_report_sections(report), [])
        self.assertEqual(input_tokens, 30)
        self.assertEqual(output_tokens, 30)


class HkCodeTests(unittest.TestCase):
    def test_hk_code_forms_are_canonicalised(self) -> None:
        for value in ("700", "0700", "00700", "HK0700", "00700.HK"):
            self.assertTrue(is_hk_stock_code(value))
            self.assertEqual(normalise_hk_code(value), "00700.HK")
        self.assertFalse(is_hk_stock_code("600519"))

    def test_report_title_filter_accepts_hk_variants(self) -> None:
        self.assertTrue(_is_wanted_report("2025 ANNUAL REPORT", 2025, "年度报告"))
        self.assertTrue(_is_wanted_report("二零二五年年報 2025", 2025, "年度报告"))
        self.assertTrue(_is_wanted_report("2025 INTERIM REPORT", 2025, "半年度报告"))
        self.assertFalse(_is_wanted_report("2025 ANNUAL RESULTS ANNOUNCEMENT", 2025, "年度报告"))
        self.assertFalse(_is_wanted_report("2024 ANNUAL REPORT", 2025, "年度报告"))

    def test_formal_category_accepts_combined_esg_but_rejects_results(self) -> None:
        self.assertTrue(
            _is_wanted_report(
                "2025年報", 2025, "年度报告", "財務報表 - [年報 / 環境、社會及管治資料/報告]"
            )
        )
        self.assertFalse(
            _is_wanted_report(
                "2025年中期業績公告", 2025, "半年度报告", "公告及通告 - [中期業績]"
            )
        )

    def test_non_calendar_fiscal_year_matches_trailing_year(self) -> None:
        self.assertTrue(_year_matches("2024/25 年報", 2025))
        self.assertFalse(_year_matches("2024/25 年報", 2026))

    def test_hkex_search_parses_double_encoded_result(self) -> None:
        class Response:
            @staticmethod
            def json():
                return {
                    "result": '[{"TITLE":"2025 ANNUAL REPORT","FILE_LINK":"/listedco/2026/report.pdf","DATE_TIME":"2026/03/20"}]'
                }

        with tempfile.TemporaryDirectory() as directory:
            client = HkexClient(Path(directory))
            client.resolve_security = lambda *_args: {
                "canonical_code": "00700.HK",
                "canonical_name": "TENCENT",
                "stock_id": "7609",
            }
            client._get = lambda *_args, **_kwargs: Response()
            reports = client.search_reports("00700.HK", "TENCENT", 2025, "年度报告")
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0].sec_code, "00700.HK")
        self.assertEqual(reports[0].announcement_date, "2026-03-20")
        self.assertTrue(reports[0].download_url.endswith("/listedco/2026/report.pdf"))

    def test_simplified_company_name_prefers_exact_equity_over_warrants(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = HkexClient(Path(directory))
            client.company_catalog = lambda: [
                {"c": "09863", "n": "零跑汽車", "i": 1000167023},
                {"c": "13954", "n": "零跑信證七四購A", "i": 1000307451},
            ]
            security = client.resolve_security("", "零跑汽车")
        self.assertEqual(security["canonical_code"], "09863.HK")
        self.assertEqual(security["canonical_name"], "零跑汽車")


class SingleMarketInputTests(unittest.TestCase):
    def test_a_share_mode_rejects_hk_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "A股模式不接受港股代码"):
                cninfo.parse_company_identifiers("00700.HK", Path(directory), market="A股")

    def test_hk_mode_rejects_six_digit_a_share_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "港股模式不接受 A 股代码"):
                cninfo.parse_company_identifiers("600519", Path(directory), market="港股")

    def test_hk_mode_uses_hkex_and_returns_canonical_code(self) -> None:
        resolved = {"canonical_code": "00700.HK", "canonical_name": "腾讯控股", "stock_id": "7609"}
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(HkexClient, "resolve_security", return_value=resolved):
                companies = cninfo.parse_company_identifiers("腾讯控股", Path(directory), market="港股")
        self.assertEqual([(item.stock_code, item.company_name) for item in companies], [("00700.HK", "腾讯控股")])


class HkMarketDataTests(unittest.TestCase):
    def test_hk_f10_branch_maps_metrics(self) -> None:
        payload = {
            "result": {
                "data": [
                    {
                        "REPORT_DATE": "2025-12-31 00:00:00",
                        "OPERATE_INCOME": 100_000_000_000,
                        "HOLDER_PROFIT": 20_000_000_000,
                        "OPERATE_INCOME_YOY": 10.0,
                        "HOLDER_PROFIT_YOY": 15.0,
                        "TOTAL_ASSETS": 500_000_000_000,
                        "TOTAL_PARENT_EQUITY": 250_000_000_000,
                    }
                ]
            }
        }
        with patch.object(market_data, "_request_json", return_value=payload):
            metrics = market_data.fetch_eastmoney_metrics("00700.HK", 2025, "年度报告")
        self.assertEqual(metrics.revenue_billion, 1000.0)
        self.assertEqual(metrics.parent_profit_billion, 200.0)
        self.assertEqual(metrics.revenue_yoy_pct, 10.0)
        self.assertEqual(metrics.parent_profit_yoy_pct, 15.0)
        self.assertEqual(metrics.asset_turnover, 0.2)
        self.assertEqual(metrics.equity_multiplier, 2.0)
        self.assertEqual(metrics.source_name, "东方财富港股F10主要指标")


if __name__ == "__main__":
    unittest.main()
