from __future__ import annotations

import tempfile
import unittest
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import engine
from deep_research import (
    select_deep_evidence, supplement_deep_evidence, evidence_coverage,
    source_reference_issues, report_quality_issues,
    cash_bridge_excerpt, cash_bridge_missing_claim_sections,
    clarify_deep_review_labels,
)


def memo_sections():
    return {
        numeral: f"## {numeral}、{title}\n\n"
        "公司本期收入与现金兑现仍需结合原文及可比期间判断，相关事实见[本期PDF第7页]；"
        "当前只核验已提供材料，不将证据缺口视作经营安全或异常的证明。"
        for numeral, title in zip(engine.DEEP_SECTION_NUMERALS, engine.DEEP_SECTION_TITLES)
    }


def fake_client(responses):
    iterator = iter(responses)
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=next(iterator)))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=20),
        )
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))), calls


class V81EvidenceTests(unittest.TestCase):
    def test_actual_hsbc_long_cashflow_preserves_tail_units_and_comparatives(self):
        raw = (Path(__file__).parent / "fixtures" / "hsbc_2025h1_cashflow_pdf85.txt").read_text(encoding="utf-8")
        pages = [engine.ExtractedPage(i, "主营业务 业绩回顾 分部信息 " * 900) for i in range(1, 85)]
        pages += [engine.ExtractedPage(85, raw), engine.ExtractedPage(86, "现金流附注与限制说明 " * 500)]
        initial = select_deep_evidence(pages, max_pages=32, max_chars=68000)
        selected = supplement_deep_evidence(pages, initial, max_pages=36, max_chars=76000)
        cash = next(page for page in selected if page.page == 85)
        self.assertEqual(cash.text, raw)
        self.assertIn(85, evidence_coverage(selected)["cashflow"])
        excerpt = cash_bridge_excerpt(selected)
        for token in ("百萬美元", "2025年6", "2024年6", "13,182", "(36,430)", "(13,657)", "434,940", "30,872", "428,907", "448,984"):
            self.assertIn(token, excerpt)
        self.assertLessEqual(sum(len(page.text) for page in selected), 76000)
        body = {"三": "## 三、资产质量、现金与偿债\n\n经营、投资、融资现金净额及期末现金未取得，无法完成现金桥核验。"}
        self.assertEqual(cash_bridge_missing_claim_sections(body, selected), ["三"])
        legitimate_limit = {"三": "银行客户及受限资金的自由偿债可用性缺少更细附注，不能把报表现金全额视为自由现金。"}
        self.assertEqual(cash_bridge_missing_claim_sections(legitimate_limit, selected), [])

    def test_late_statement_and_notes_coverage_survive_front_matter(self):
        pages = [engine.ExtractedPage(i, "主营业务 公司介绍 " * 100) for i in range(1, 91)]
        pages += [
            engine.ExtractedPage(91, "Consolidated statement of financial position Total assets 12,000 Total liabilities 7,000 Total equity 5,000"),
            engine.ExtractedPage(92, "Consolidated income statement Revenue 9,000 Profit before tax 2,000 Income tax expense 500"),
            engine.ExtractedPage(93, "Consolidated statement of cash flows Net cash from operating 1,500"),
            engine.ExtractedPage(94, "Net cash used in investing 700 Financing activities 200 Cash and cash equivalents 4,000"),
            engine.ExtractedPage(95, "Related parties Contingent liabilities Capital commitments"),
            engine.ExtractedPage(96, "Debt maturity Liquidity risk Restricted cash 100"),
        ]
        selected = select_deep_evidence(pages, max_pages=14, max_chars=18000)
        coverage = evidence_coverage(selected)
        self.assertTrue(all(coverage[topic] for topic in ("balance_sheet", "income", "cashflow", "debt", "related_contingent")))
        self.assertIn(94, [page.page for page in selected])
        self.assertLessEqual(len(selected), 14)
        self.assertLessEqual(sum(len(page.text) for page in selected), 18000)

    def test_heading_free_cashflow_continuation_is_discovered(self):
        page = engine.ExtractedPage(80, "Net cash from operating 1,200\nNet cash used in investing 300\nFinancing activities 200\nCash and cash equivalents 900")
        self.assertEqual(evidence_coverage([page])["cashflow"], [80])

    def test_followup_restores_original_and_adds_missing_local_note(self):
        pages = [
            engine.ExtractedPage(1, "合并资产负债表 " + "资产 1,000 " * 1000),
            engine.ExtractedPage(2, "主营业务 原始证据保持不变"),
            engine.ExtractedPage(3, "到期分析 受限资金 流动性风险 未来12月"),
            engine.ExtractedPage(4, "借款期限与抵押品续页资料"),
        ]
        initial = [engine.ExtractedPage(1, pages[0].text[:120] + "\n[本页文本截断，必要时回原PDF补取]")]
        recovered = supplement_deep_evidence(pages, initial, max_pages=4, max_chars=20000)
        self.assertIn(3, [page.page for page in recovered])
        self.assertIn(4, [page.page for page in recovered])
        self.assertEqual(recovered[0].text, pages[0].text)
        self.assertNotIn("[本页文本截断", pages[0].text)

    def test_references_distinguish_same_page_numbers_in_two_files(self):
        current = [engine.ExtractedPage(7, "本期")]
        prior = [engine.ExtractedPage(8, "上期")]
        self.assertEqual(source_reference_issues("[本期PDF第7页] [上期PDF第8页]", current, prior), [])
        issues = source_reference_issues("[上期PDF第7页] [本期PDF第9页]", current, prior)
        self.assertEqual(len(issues), 2)


class V81MemoGenerationTests(unittest.TestCase):
    def test_fixed_review_labels_change_without_changing_figures_or_citations(self):
        from i18n import numeric_tokens
        text = (
            "## 四、风险、矛盾与反证\n\n信用损失费用2,077百万美元。[本期PDF第85页]\n"
            "证据状态：已核验触发\n\n"
            "## 六、关键数字与口径核验\n\n"
            "| 指标 | 本期 | 来源 | 核验状态与限制 |\n|---|---|---|---|\n"
            "| 营业现金流 | 13,182百万美元 | [本期PDF第85页] | 已核对原文 |\n"
        )
        clarified, issues = clarify_deep_review_labels(text)
        self.assertEqual(issues, [])
        self.assertEqual(numeric_tokens(clarified), numeric_tokens(text))
        self.assertEqual(clarified.count("[本期PDF第85页]"), 2)
        self.assertIn("信用损失费用2,077百万美元。", clarified)
        self.assertIn("研究风险分类：已观察到的风险事实", clarified)
        self.assertIn("模型读取及页码定位，待人工复核", clarified)

    def test_uncertain_label_context_is_retained_and_blocks_completion(self):
        text = (
            "## 六、关键数字与口径核验\n\n"
            "| 指标 | 经营判断 |\n|---|---|\n"
            "| 13,182 | 已核对原文 |\n\n"
            "补充说明：已核验触发，具体结论尚需解释。"
        )
        clarified, issues = clarify_deep_review_labels(text)
        self.assertEqual(clarified, text)
        self.assertTrue(issues)
        result = engine._comment_payload(engine.CompanyRow(2, "00005.HK", "汇丰控股", {}),
            Path("memo.md"), "半年度报告", 2025, "需复核", "；".join(issues))
        self.assertTrue(result["retryable"])
        self.assertFalse(result["generation_complete"])

    def test_status_prefix_preserves_following_basis_and_figures(self):
        from i18n import numeric_tokens
        text = (
            "## 六、关键数字与口径核验\n\n"
            "| 指标 | 金额 | 核验状态与限制 |\n|---|---|---|\n"
            "| 税前利润 | 15,810百万美元 | 已核对原文；列賬基準；可比21,556 |\n"
        )
        clarified, issues = clarify_deep_review_labels(text)
        self.assertEqual(issues, [])
        self.assertIn("模型读取及页码定位，待人工复核；列賬基準；可比21,556", clarified)
        self.assertEqual(numeric_tokens(clarified), numeric_tokens(text))

    def test_model_cash_arithmetic_never_becomes_a_program_check(self):
        from i18n import numeric_tokens
        text = (
            "## 六、关键数字与口径核验\n\n"
            "| 指标 | 算式 | 核验状态与限制 |\n|---|---|---|\n"
            "| 现金桥 | 434,940+13,182-36,430-13,657+30,872=428,907 | 程序检查：加总核对，差额为0 |\n\n"
            "## 七、证据账本与研究边界\n\n"
            "本次程序检查仅执行了现金桥的加总核对。[本期PDF第85页]\n"
            "程序已检查引用页是否存在及章节完整性。"
        )
        clarified, issues = clarify_deep_review_labels(text)
        self.assertEqual(issues, [])
        self.assertEqual(numeric_tokens(clarified), numeric_tokens(text))
        self.assertIn("模型计算，待人工复核，差额为0", clarified)
        self.assertIn("程序已检查引用页是否存在及章节完整性。", clarified)
        self.assertIn("[本期PDF第85页]", clarified)
        self.assertNotIn("程序检查仅执行了现金桥", clarified)

    def test_arithmetic_negation_is_preserved_and_ambiguous_claim_is_flagged(self):
        legitimate = "本次未执行程序算术校验；程序已检查引用页是否存在及章节完整性。"
        clarified, issues = clarify_deep_review_labels(legitimate)
        self.assertEqual(clarified, legitimate)
        self.assertEqual(issues, [])
        ambiguous = "现金桥已由自动程序验证，差额为0。[本期PDF第85页]"
        clarified, issues = clarify_deep_review_labels(ambiguous)
        self.assertEqual(clarified, ambiguous)
        self.assertTrue(issues)
        payload = engine._comment_payload(engine.CompanyRow(2, "00005.HK", "汇丰控股", {}),
            Path("memo.md"), "半年度报告", 2025, "需复核", "；".join(issues))
        self.assertTrue(payload["retryable"])

    def test_actual_traditional_hsbc_claims_are_clarified_with_newlines_preserved(self):
        from i18n import numeric_tokens
        excerpt = (Path(__file__).parent / "fixtures" / "hsbc_program_claims_2025h1_excerpt.txt").read_text(encoding="utf-8").splitlines()
        for newline in ("\n", "\r\n"):
            text = newline.join([
                "## 四、風險、矛盾與反證", "證據狀態：已核驗觸發",
                "## 六、關鍵數字與口徑核驗", "| 指標 | 金額 | 核驗狀態與限制 |",
                "|---|---|---|", "| 營業現金 | 13,182 | 已核對原文；列賬基準 |",
                "| 現金橋 | 428,907 | " + excerpt[0] + " |",
                "## 七、證據賬本與研究邊界", excerpt[1] + "。[本期PDF第85页]",
                "程序已檢查引用頁及章節完整性。", "", "",
            ])
            clarified, issues = clarify_deep_review_labels(text)
            self.assertEqual(issues, [])
            self.assertEqual(numeric_tokens(clarified), numeric_tokens(text))
            self.assertIn("模型計算，待人工複核，差額為0", clarified)
            self.assertIn("模型讀取及頁碼定位，待人工複核；列賬基準", clarified)
            self.assertIn("研究風險分類：已觀察到的風險事實", clarified)
            self.assertIn("程序已檢查引用頁及章節完整性。", clarified)
            self.assertTrue(clarified.endswith(newline * 2))
            second, second_issues = clarify_deep_review_labels(clarified)
            self.assertEqual(second, clarified)
            self.assertEqual(second_issues, [])

    def test_ambiguous_traditional_claim_is_not_silently_accepted(self):
        text = "## 六、關鍵數字與口徑核驗\n\n審閱備註：已核對原文；本次現金橋已由自動程序驗證，差額為0。\n"
        clarified, issues = clarify_deep_review_labels(text)
        self.assertEqual(clarified, text)
        self.assertTrue(issues)

    def test_all_eight_real_qa_excerpts_keep_figures_and_accept_honest_negations(self):
        from i18n import numeric_tokens, protected_tokens
        fixture = json.loads((Path(__file__).parent / "fixtures" / "actual_v81_review_claims_matrix.json").read_text(encoding="utf-8"))
        self.assertEqual(len(fixture["cases"]), 8)
        for case, data in fixture["cases"].items():
            with self.subTest(case=case):
                # This tests label integrity only. Financial-fact acceptance is
                # a separate audit and must not be inferred from this fixture.
                text = "\n".join(data["lines"]) + "\n\n"
                clarified, issues = clarify_deep_review_labels(text)
                self.assertEqual(issues, [])
                self.assertEqual(numeric_tokens(clarified), numeric_tokens(text))
                self.assertEqual(protected_tokens(clarified), protected_tokens(text))
                self.assertEqual([line.count("|") for line in clarified.splitlines()],
                                 [line.count("|") for line in text.splitlines()])
                self.assertTrue(clarified.endswith("\n\n"))
                second, again = clarify_deep_review_labels(clarified)
                self.assertEqual((second, again), (clarified, []))
                if case in ("a_zh/300750", "a_en/600519", "hk_en/00005.HK"):
                    self.assertEqual(clarified, text)

    def test_supplied_cash_bridge_missing_claim_gets_one_targeted_repair(self):
        raw = (Path(__file__).parent / "fixtures" / "hsbc_2025h1_cashflow_pdf85.txt").read_text(encoding="utf-8")
        sections = memo_sections()
        sections["三"] = "## 三、资产质量、现金与偿债\n\n经营、投资、融资现金净额及期末现金未取得，无法完成现金桥核验，因此不能确认现金变动。"
        corrected = "## 三、资产质量、现金与偿债\n\n本期按百万美元列示：434,940+13,182-36,430-13,657+30,872=428,907，差额为零；银行客户资金与自由偿债现金另须区分。[本期PDF第85页]"
        fake, calls = fake_client([engine._assemble_deep_report("# 研究备忘录", sections), corrected])
        with patch.object(engine, "OpenAI", return_value=fake):
            text, *_ = engine.generate_deep_report_markdown(
                engine.CompanyRow(2, "00005.HK", "汇丰控股", {}), [engine.ExtractedPage(85, raw)],
                engine.KeyFinancialMetrics(), "key", "model", "https://example.invalid", "半年度报告", 2025,
                "", [], engine.KeyFinancialMetrics(), "")
        _, actual = engine.split_deep_report(text)
        self.assertEqual(len(calls), 2)
        self.assertEqual(actual["二"], sections["二"])
        self.assertIn("434,940+13,182-36,430-13,657+30,872=428,907", actual["三"])
        self.assertEqual(cash_bridge_missing_claim_sections(actual, [engine.ExtractedPage(85, raw)]), [])

    def test_current_stub_is_explicitly_not_publishable(self):
        text = engine.stub_deep_report(engine.CompanyRow(2, "00700.HK", "腾讯控股", {}),
                                      engine.KeyFinancialMetrics(revenue_billion=999), "半年度报告", 2025, "模型章节补写未完成")
        _, sections = engine.split_deep_report(text)
        self.assertEqual(tuple(sections), engine.DEEP_SECTION_NUMERALS)
        self.assertIn("报告尚未生成", text)
        self.assertNotIn("999", text)
        self.assertTrue(report_quality_issues(text))
        self.assertTrue(engine._comment_payload(engine.CompanyRow(2, "00700.HK", "腾讯控股", {}),
                                                Path("x.md"), "半年度报告", 2025, "需复核",
                                                "模型章节补写未完成")["retryable"])

    def test_historical_twelve_section_reports_remain_readable(self):
        legacy = {n: f"## {n}、历史章节\n\n已有财报研究内容及PDF第7页依据，不因模板升级被删除。"
                  for n in engine.LEGACY_DEEP_SECTION_NUMERALS}
        text = engine._assemble_deep_report("# 历史报告", legacy)
        self.assertEqual(engine.missing_deep_report_sections(text), [])
        _, actual = engine.split_deep_report(text)
        self.assertEqual(tuple(actual), engine.LEGACY_DEEP_SECTION_NUMERALS)

    def test_only_interrupted_chapter_is_repaired_and_evidence_preserved(self):
        sections = memo_sections()
        sections["六"] = "## 六、关键数字与口径核验\n\n| 指标 | 本期"
        initial = engine._assemble_deep_report("# 研究备忘录", sections)
        repair = "## 六、关键数字与口径核验\n\n| 指标 | 原文证据 |\n|---|---|\n| 收入 | 本期与可比期口径须对照原文单位与合并范围核验，[本期PDF第7页] |"
        fake, calls = fake_client([initial, sections["六"], repair])
        with patch.object(engine, "OpenAI", return_value=fake):
            text, tin, tout, _ = engine.generate_deep_report_markdown(
                engine.CompanyRow(2, "300750", "宁德时代", {}), [engine.ExtractedPage(7, "收入证据")],
                engine.KeyFinancialMetrics(), "key", "model", "https://example.invalid",
                "半年度报告", 2025, "", [], engine.KeyFinancialMetrics(), "")
        _, actual = engine.split_deep_report(text)
        self.assertEqual(engine.incomplete_deep_report_sections(actual), [])
        self.assertEqual(actual["二"], sections["二"])
        self.assertIn("须对照原文单位", actual["六"])
        self.assertEqual((tin, tout), (30, 60))
        self.assertEqual(len(calls), 3)

    def test_prompt_uses_current_comparatives_without_claiming_prior_download(self):
        system, user = engine.build_deep_report_prompt(
            engine.CompanyRow(2, "00700.HK", "腾讯控股", {}), [engine.ExtractedPage(7, "收益及同期可比列")],
            engine.KeyFinancialMetrics(revenue_billion=999), "半年度报告", 2025, "", [],
            engine.KeyFinancialMetrics(), "")
        self.assertIn("七章", user)
        self.assertIn("同期可比列仍可使用", user)
        self.assertNotIn("第一至第十二章全部必填", user)
        self.assertNotIn("999", user)
        self.assertIn("非GAAP", system)
        self.assertIn("不得", system)

    def test_wrong_company_file_stops_before_model_generation(self):
        row = engine.CompanyRow(2, "00700.HK", "腾讯控股", {})
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(engine, "load_market_metrics", return_value=None), \
                 patch.object(engine, "load_cninfo_metadata", return_value={}), \
                 patch.object(engine, "extract_pdf_pages", return_value=[engine.ExtractedPage(1, "2025年中期報告 匯豐控股")]), \
                 patch.object(engine, "resolve_financial_metrics") as extract, \
                 patch.object(engine, "generate_deep_report_markdown") as generate:
                payload = engine.comment_one_company(row, root / "wrong.pdf", root / "memo.md",
                    report_type="半年度报告", report_year=2025, cache_dir=root, api_key="key",
                    model="model", base_url="https://example.invalid", test_mode=False)
            self.assertEqual(payload["status"], "失败")
            self.assertTrue(payload["retryable"])
            self.assertIn("来源未通过核验", payload["message"])
            extract.assert_not_called()
            generate.assert_not_called()

    def test_no_model_and_custom_missing_pdf_cannot_be_cached_as_complete(self):
        row = engine.CompanyRow(2, "600519", "贵州茅台", {})
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(engine, "load_market_metrics", return_value=None), \
                 patch.object(engine, "load_cninfo_metadata", return_value={}), \
                 patch.object(engine, "extract_pdf_pages", return_value=[engine.ExtractedPage(1, "贵州茅台2025年半年度报告")]), \
                 patch.object(engine, "resolve_financial_metrics", return_value=engine.KeyFinancialMetrics()), \
                 patch.object(engine, "load_prior_period_evidence", return_value=("", [], engine.KeyFinancialMetrics())), \
                 patch.object(engine, "generate_deep_report_markdown") as generate:
                for test_mode, api_key, pdf in ((True, "key", root / "source.pdf"),
                                               (False, "", root / "source.pdf"),
                                               (False, "key", None)):
                    payload = engine.comment_one_company(row, pdf, root / "memo.md",
                        report_type="半年度报告", report_year=2025, cache_dir=root,
                        api_key=api_key, model="model", base_url="https://example.invalid",
                        test_mode=test_mode, match_message="指定的附件无法取得")
                    self.assertTrue(payload["retryable"])
                    self.assertFalse(payload["generation_complete"])
                generate.assert_not_called()

    def test_publication_defects_retry_but_disclosed_history_gap_does_not(self):
        row = engine.CompanyRow(2, "600519", "贵州茅台", {})
        for message in ("未识别到可追溯页码/来源引用", "章节正文不足或表格截断：第六章",
                        "引用未包含在实际输入证据中：本期PDF第99页"):
            result = engine._comment_payload(row, Path("memo.md"), "半年度报告", 2025, "需复核", message)
            self.assertTrue(result["retryable"])
            self.assertFalse(result["generation_complete"])
        reviewed = engine._comment_payload(row, Path("memo.md"), "半年度报告", 2025,
                                          "需复核", "未取得上期原版，历史对比存在缺口")
        self.assertFalse(reviewed["retryable"])
        self.assertTrue(reviewed["generation_complete"])


if __name__ == "__main__":
    unittest.main()
