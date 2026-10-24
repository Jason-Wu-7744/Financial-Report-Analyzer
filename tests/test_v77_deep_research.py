import unittest
from dataclasses import dataclass

from deep_research import select_deep_evidence, evidence_coverage, report_quality_issues


@dataclass
class Page:
    page: int
    text: str
    score: int = 0


class DeepEvidenceTests(unittest.TestCase):
    def test_hsbc_formal_interim_title_and_variant_name(self):
        import engine
        row=engine.CompanyRow(2,'00005.HK','匯豐控股',{})
        pages=[engine.ExtractedPage(1,'HSBC Holdings plc\n滙豐控股有限公司\n2025年中期業績報告')]
        self.assertEqual(engine.validate_report_source(pages,row,'半年度报告'),[])
        wrong=engine.CompanyRow(2,'00700.HK','騰訊控股',{})
        self.assertTrue(engine.validate_report_source(pages,wrong,'半年度报告'))
        announcement=[engine.ExtractedPage(1,'滙豐控股有限公司 2025年中期業績公告')]
        self.assertTrue(engine.validate_report_source(announcement,row,'半年度报告'))

    def test_hk_image_logo_cover_uses_labeled_ticker(self):
        import engine
        pages = [engine.ExtractedPage(1, '年度報告 H 股股份代號: 02333（港幣櫃台）')]
        self.assertEqual(engine.validate_report_source(pages, engine.CompanyRow(2,'02333.HK','长城汽车',{}),'年度报告'), [])
        self.assertTrue(engine.validate_report_source(pages, engine.CompanyRow(2,'01211.HK','比亚迪',{}),'年度报告'))

    def test_combined_group_company_statements(self):
        coverage = evidence_coverage([Page(1, '合并及公司资产负债表'), Page(2, '合併及公司现金流量表')])
        self.assertEqual(coverage['balance_sheet'], [1])
        self.assertEqual(coverage['cashflow'], [2])

    def test_traditional_company_name_matches_same_issuer(self):
        import engine
        self.assertEqual(engine.validate_report_source([engine.ExtractedPage(1, '2025 年度報告 中國建設銀行股份有限公司')],
            engine.CompanyRow(2, '00939.HK', '建设银行', {}), '年度报告'), [])

    def test_consolidated_position_variant_is_selected(self):
        pages = [Page(1, '审计范围包括合併財務狀況表'), Page(50, '合併財務狀況表\n現金 1,000.00\n資產 2,000.00\n負債 1,000.00\n權益 1,000.00')]
        self.assertIn(50, evidence_coverage(select_deep_evidence(pages, max_pages=1))['balance_sheet'])

    def test_unverified_hk_metrics_never_anchor_deep_prompt(self):
        import engine
        row = engine.CompanyRow(2, '00386.HK', '中国石化', {})
        text = engine._deep_metric_text(row, engine.KeyFinancialMetrics(revenue_billion=0.12))
        self.assertNotIn('0.1200', text)
        self.assertIn('原版', text)

    def test_annual_title_without_duplicate_year_character(self):
        from cninfo import classify_periodic_report
        self.assertEqual(classify_periodic_report('招商银行2025年度报告（A股）'), ('年度报告', 2025))
        self.assertIsNone(classify_periodic_report('招商银行2025年度报告摘要'))

    def test_statements_survive_many_operating_pages(self):
        pages = [Page(i, '主营业务 业绩变动原因 ' * 100) for i in range(1, 20)]
        pages += [Page(20, '合并资产负债表 现金 总资产'), Page(21, '合并利润表 营业收入'),
                  Page(22, '合并现金流量表 经营活动')]
        selected = select_deep_evidence(pages, max_pages=12)
        coverage = evidence_coverage(selected)
        self.assertTrue(all(coverage[x] for x in ('balance_sheet', 'income', 'cashflow')))

    def test_toc_is_not_cashflow_evidence(self):
        pages = [Page(1, '綜合現金流量表 .... 80\n一 .... 1\n二 .... 2\n三 .... 3'),
                 Page(80, '綜合現金流量表 經營活動 500')]
        self.assertEqual(evidence_coverage(select_deep_evidence(pages))['cashflow'], [80])

    def test_text_budget_and_original_preserved(self):
        page = Page(1, '合并资产负债表' + 'a' * 10000)
        selected = select_deep_evidence([page], max_chars=1000)
        self.assertLessEqual(sum(len(p.text) for p in selected), 1000)
        self.assertIn('截断', selected[0].text)
        self.assertGreater(len(page.text), 10000)

    def test_missing_coverage_stays_missing(self):
        self.assertEqual(evidence_coverage([Page(1, '主营业务')])['debt'], [])

    def test_fallback_is_not_publishable(self):
        self.assertIn('报告包含兜底或未生成内容', report_quality_issues('当前仅保留完整章节骨架 PDF第1页'))

    def test_uncited_report_is_flagged(self):
        self.assertTrue(report_quality_issues('企业经营稳健，现金充足'))


if __name__ == '__main__':
    unittest.main()
