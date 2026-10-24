from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import hk_quality
import screening_engine as screening
from hkex import _is_wanted_report


@dataclass
class Page:
    page: int
    text: str


def report(checks=None):
    return screening.normalize_report(
        {"checks": checks or [], "sources": [{"id": "S1", "url": "https://www1.hkexnews.hk/report.pdf", "title": "Annual report"}]},
        company_name="Example", stock_code="00700.HK", industry="Technology", screening_date="2026-10-15",
    )


def check(cid="C8", state="已核验未触发"):
    return {"id": cid, "evidence_state": state, "finding": "公司于2004年6月上市，距本次筛查已22年。",
            "basis": "公司股份自2004年6月16日起在香港联交所上市。[S1]", "source_ids": ["S1"],
            "evidence_quote": "Shares were listed on 16 June 2004"}


def test_missing_checks_and_vague_pass_never_become_clearance():
    data = report()
    assert data["conclusion"] == "待补证"
    assert len(data["unchecked"]) == 19
    assert data["evidence_counts"]["证据不足"] == 19
    assert data["review_schema"] == "evidence-review-v8.1"
    vague = check()
    vague.update(outcome="通过", finding="未取得过去三年数据，暂按通过。")
    assert report([vague])["checks"][9]["outcome"] == "证据不足"
    md = screening.report_to_markdown(data)
    assert "19项硬性排雷全部通过" not in md
    assert "全部项目通过" not in md
    assert "19项证据不足" in md


def test_four_states_keep_trigger_and_gaps_separate():
    rows = [check("H1"), check("H2", "已核验触发"), check("C1", "不适用")]
    data = report(rows)
    assert data["conclusion"] == "淘汰"
    assert data["hits"] == ["H2"]
    assert len(data["unchecked"]) == 16
    assert data["evidence_counts"] == {"已核验未触发": 1, "已核验触发": 1, "不适用": 1, "证据不足": 16}


def test_unknown_source_and_unrecognized_outcome_remain_insufficient():
    row = check()
    row["source_ids"] = ["S99"]
    assert len(report([row])["unchecked"]) == 19
    row = check()
    row["evidence_state"] = "apparently fine"
    assert len(report([row])["unchecked"]) == 19


def test_direct_quote_matching_ignores_whitespace_case_and_grouping_commas():
    row = check()
    text = "SHARES\n WERE listed on 16\tJune 2004"
    assert screening.validate_check_evidence(row, text)["evidence_state"] == "已核验未触发"
    row["id"] = "H1"
    row["evidence_quote"] = "Revenue increased to 1,234 million"
    assert screening.validate_check_evidence(row, "Revenue increased\nto 1234 million")["evidence_state"] == "已核验未触发"
    assert screening.validate_check_evidence(row, "Revenue increased to 1235 million")["evidence_state"] == "证据不足"
    row["evidence_quote"] = "主要由于出售加拿大银行业务及阿根廷业务"
    assert screening.validate_check_evidence(row, "主要由于出售加拿⼤银⾏业务及阿根廷业务")["evidence_state"] == "已核验未触发"


def _tencent_and_disproof(cid, numerator, denominator, threshold, numerator_quote, denominator_quote):
    row = check(cid)
    row.update(
        finding=f"本期比例{numerator/denominator*100:.2f}%未超过{threshold}%；未取得其他趋势/账龄数据。",
        basis="该项为AND组合，首个必要条件已否定；其他未取得资料仅为范围限制。[S1]",
        evidence_quote="", proof_type="and_condition_disproved", disproven_condition=f"本期比率>{threshold}%",
        disproof={"numerator": numerator, "denominator": denominator, "ratio_pct": round(numerator/denominator*100, 2),
                  "threshold_pct": threshold, "period": "2025-06-30 / 2025H1", "unit": "人民币百万元",
                  "numerator_quote": numerator_quote, "denominator_quote": denominator_quote},
    )
    return row


def test_tencent_q1_and_q5_disproof_is_not_killed_by_missing_other_conditions():
    q1 = _tencent_and_disproof("Q1", 810461, 2013310, 80, "負債總額 810,461 727,099", "資產總額 2,013,310 1,780,995")
    q5 = _tencent_and_disproof("Q5", 51315, 364526, 40, "應收賬款 23 51,315 48,203", "收入 364,526 320,618 14%")
    text = "\n".join([q1["disproof"]["numerator_quote"], q1["disproof"]["denominator_quote"], q5["disproof"]["numerator_quote"], q5["disproof"]["denominator_quote"]])
    for row in (q1, q5):
        checked = screening.validate_check_evidence(row, text)
        assert checked["evidence_state"] == "已核验未触发"
        normalized = report([checked])
        assert next(item for item in normalized["checks"] if item["id"] == row["id"])["evidence_state"] == "已核验未触发"
        assert row["id"] not in normalized["unchecked"]
    q1["disproof"]["ratio_pct"] = 90
    assert screening.validate_check_evidence(q1, text)["evidence_state"] == "证据不足"


def test_or_check_cannot_be_cleared_by_one_disproved_branch():
    row = _tencent_and_disproof("C1", 810461, 2013310, 80, "負債總額 810,461 727,099", "資產總額 2,013,310 1,780,995")
    text = row["disproof"]["numerator_quote"] + "\n" + row["disproof"]["denominator_quote"]
    assert screening.validate_check_evidence(row, text)["evidence_state"] == "证据不足"


def test_hsbc_report_title_does_not_prove_listing_age():
    row = check("C8")
    row["finding"] = "汇丰是长期上市公司，上市已远超2-3年。"
    row["evidence_quote"] = "滙豐控股有限公司 2025年中期業績報告"
    assert screening.validate_check_evidence(row, row["evidence_quote"])["evidence_state"] == "证据不足"
    row["evidence_quote"] = "Shares were listed on 16 June 2004"
    assert screening.validate_check_evidence(row, row["evidence_quote"])["evidence_state"] == "已核验未触发"


def test_risk_word_export_reports_gaps_as_gaps(tmp_path):
    data = report()
    path, error = screening.try_build_docx(data, tmp_path / "risk.docx")
    assert path and not error
    with ZipFile(path) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    assert "19项硬性排雷全部通过" not in xml
    assert "全部项目通过" not in xml
    assert "证据不足" in xml
    assert "待补证" in xml


def test_hk_pages_keep_three_statements_and_credit_not_just_highlights():
    pages = [Page(1, "目錄\n綜合損益表 80\n綜合現金流量表 90\n綜合財務狀況表 100")]
    pages.extend(Page(n, "財務摘要\n收益 123 456 789 100 200 300") for n in range(2, 20))
    pages.extend([
        Page(80, "Consolidated income statement\nUS$ million\nRevenue 100 80\nProfit attributable to owners 20 18"),
        Page(81, "Attributable to shareholders 20 18\nNon-controlling interests 3 2"),
        Page(90, "綜合現金流量表\n經營活動現金 150 120\n投資活動現金 (80) (50)"),
        Page(100, "綜合財務狀況表\n資產 900 850\n負債 500 450\n權益 400 400"),
        Page(110, "信貸風險\n資本充足率 15.4 15.2\n淨息差 1.7 1.8"),
    ])
    selected = hk_quality.select_hk_financial_pages(pages, max_pages=12)
    numbers = {page.page for page in selected}
    assert {80, 81, 90, 100, 110}.issubset(numbers)
    assert 1 not in numbers
    assert selected[0].text in [page.text for page in pages]
    context = hk_quality.hk_accounting_context(pages, "滙豐控股")
    assert "USD" in context and "银行" in context


def test_risk_digest_keeps_late_cashflow_and_does_not_invent_full_coverage():
    blocks = [f"===== PDF第{n}页 =====\n" + "公司概况文字" * 600 for n in range(1, 15)]
    blocks.append("===== PDF第120页 =====\nConsolidated statement of cash flows\nNet cash from operating activities 150 120\n")
    blocks.append("===== PDF第130页 =====\n綜合財務狀況表\nBorrowings 200 180\n")
    digest = hk_quality.compact_risk_evidence("\n\n".join(blocks), max_chars=8000)
    assert "PDF第120页" in digest and "150 120" in digest
    assert "PDF第130页" in digest
    assert "非全文覆盖" in digest
    assert len(digest) <= 8000


def test_hk_operating_selector_prioritizes_financial_explanations_over_risk_notes():
    pages = [
        Page(1, "Contents\nFinancial review ........ 3\nRisk management ....... 44"),
        Page(3, "2025年上半年財務表現\n除稅前溢利減少57億美元，主要由於出售加拿⼤銀⾏業務及阿根廷業務的一次性收益不再重現。\n" * 8),
        Page(22, "Financial review\nNet interest income decreased by US$100m, mainly due to lower rates and currency translation, partly offset by structural hedge income.\n" * 8),
        Page(44, "Risk management\nCredit risk exposure and risk weighted assets increased by 20%. The risk management framework controls trading portfolios.\n" * 8),
        Page(74, "Market risk\nTrading portfolio value-at-risk decreased by 10%. Lower exposure reflects market risk management changes.\n" * 8),
    ]
    original = {page.page: page.text for page in pages}
    selected = hk_quality.select_hk_operating_pages(pages, max_pages=5, max_chars=12000)
    assert {3, 22} == {page.page for page in selected}
    assert all(page.text == original[page.page] for page in selected)
    assert all(any(page is source for source in pages) for page in selected)
    assert hk_quality.hk_operating_page_score(pages[1].text) > hk_quality.hk_operating_page_score(pages[3].text)


def test_hk_operating_selector_preserves_whole_pages_within_budget():
    pages = [Page(n, "Financial review\nRevenue increased by 12%, driven by stronger sales and higher margins.\n" * 8) for n in range(1, 8)]
    selected = hk_quality.select_hk_operating_pages(pages, max_pages=5, max_chars=1600)
    assert selected and len(selected) <= 5
    assert sum(len(page.text) for page in selected) <= 1600
    assert all(page.text == pages[page.page - 1].text for page in selected)


def test_formal_combined_annual_esg_is_not_confused_with_standalone_esg():
    category = "財務報表 - [年報 / 環境、社會及管治資料/報告]"
    assert _is_wanted_report("2025 Annual Report and ESG Report", 2025, "年度报告", category)
    assert not _is_wanted_report("2025 ESG Report", 2025, "年度报告", category)
    assert not _is_wanted_report("2025 Annual Results Announcement and ESG Report", 2025, "年度报告", category)


def test_hk_metric_rejects_currency_swap_and_unknown_pages():
    pages = [Page(10, "Amounts in US$ million\nRevenue 100 80")]
    payload = {"revenue_billion": 1, "revenue_yoy_pct": 25, "page_refs": [10], "unit_note": "HKD million"}
    clean, issues = hk_quality.validate_hk_metric_payload(payload, pages)
    assert clean["revenue_billion"] is None and issues
    assert clean["revenue_yoy_pct"] == 25
    payload.update(unit_note="US$ million", page_refs=[100])
    clean, issues = hk_quality.validate_hk_metric_payload(payload, pages)
    assert clean["revenue_billion"] is None and clean["revenue_yoy_pct"] is None


def test_hk_raw_amount_unit_conversion_and_negative_sign_are_verified():
    pages = [Page(10, "Amounts in US$ million\nRevenue 100 80\nLoss attributable to owners (12) (8)")]
    payload = {
        "revenue_billion": 1, "parent_profit_billion": -0.12, "page_refs": [10], "currency": "USD", "amount_unit": "million", "unit_note": "US$ million",
        "metric_evidence": {
            "revenue_billion": {"raw_value": "100", "unit": "million", "currency": "USD", "page": 10, "period": "six months ended 30 June 2025", "label": "Revenue"},
            "parent_profit_billion": {"raw_value": "(12)", "unit": "million", "currency": "USD", "page": 10, "period": "six months ended 30 June 2025", "label": "Loss attributable to owners"},
        },
    }
    clean, issues = hk_quality.validate_hk_metric_payload(payload, pages)
    assert not issues and clean["parent_profit_billion"] == -0.12 and clean["revenue_billion"] == 1
    payload["parent_profit_billion"] = 0.12
    clean, issues = hk_quality.validate_hk_metric_payload(payload, pages)
    assert clean["parent_profit_billion"] is None and issues


def test_hk_core_amount_without_raw_evidence_cannot_be_adopted():
    pages = [Page(10, "Amounts in US$ million\nRevenue 100 80")]
    payload = {"revenue_billion": 1, "page_refs": [10], "currency": "USD", "unit_note": "US$ million"}
    clean, issues = hk_quality.validate_hk_metric_payload(payload, pages)
    assert clean["revenue_billion"] is None
    assert any("缺少逐项原始取证" in issue for issue in issues)


def test_hk_currency_and_unit_abbreviations_are_accepted_with_raw_evidence():
    for currency, unit, page_unit in (("USD", "USDm", "USDm"), ("USD", "US$m", "US$m"), ("HKD", "港币百万", "港币百万")):
        pages = [Page(10, f"Amounts in {page_unit}\nRevenue 100 80")]
        payload = {"revenue_billion": 1, "page_refs": [10], "currency": currency, "amount_unit": unit, "unit_note": page_unit,
            "metric_evidence": {"revenue_billion": {"raw_value": "100", "unit": unit, "currency": currency, "page": 10,
                "period": "six months ended 30 June 2025", "label": "Revenue"}}}
        clean, issues = hk_quality.validate_hk_metric_payload(payload, pages)
        assert clean["revenue_billion"] == 1 and not issues


def test_screen_full_cannot_accept_19_duplicate_checks(monkeypatch, tmp_path):
    calls = []
    class Client:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({"checks": [check()] * 19})), finish_reason="stop")])
    monkeypatch.setattr(screening, "OpenAI", Client)
    result = screening.screen_full(company_name="Example", stock_code="00700.HK", report_type="半年度报告", report_year=2025,
        metrics={}, evidence_text="Shares were listed on 16 June 2004", source_url="https://www1.hkexnews.hk/report.pdf", output_dir=tmp_path,
        api_key="fake", model="fake", base_url="https://api.example.test", test_mode=False)
    assert len(calls) == 2
    assert result["status"] == "失败" and result["retryable"]
    assert result["conclusion"] == "待补证" and len(result["unchecked"]) == 19
    assert result["review_schema"] == "evidence-review-v8.1"


def _response(content, finish_reason="stop"):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason=finish_reason)])


def _client_with_responses(responses, calls):
    class Client:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
        def create(self, **kwargs):
            calls.append(kwargs)
            return responses[len(calls)-1]
    return Client


def test_truncated_check_is_not_repaired_into_a_completed_check():
    first = screening._blank_check("H1")
    content = '{"checks":[' + json.dumps(first) + ',{"id":"H2","evidence_state":"已核验未触发","finding":"cut off'
    adopted, info = screening._complete_check_objects(content)
    assert list(adopted) == ["H1"]
    assert info["closed_object_count"] == 1
    assert "H2" not in adopted


def test_complete_19_checks_survive_cut_optional_metadata_without_inventing_fields():
    rows = [screening._blank_check(cid) for cid in screening.CHECK_ORDER]
    content = json.dumps({"checks": rows})[:-1] + ',"recommendations":["cut off'
    calls = []
    client = _client_with_responses([_response(content, "length")], calls)()
    diagnostics = []
    data = screening._generate_complete_review(client, model="fake", system_prompt="rules", user_prompt="source", diagnostics=diagnostics)
    assert len(calls) == 1
    assert [item["id"] for item in data["checks"]] == screening.CHECK_ORDER
    assert "recommendations" not in data
    assert diagnostics[0]["finish_reason"] == "length"


def test_only_missing_closed_check_is_retried_after_two_incomplete_full_calls():
    rows = [screening._blank_check(cid) for cid in screening.CHECK_ORDER]
    content = '{"checks":' + json.dumps(rows[:-1])[:-1] + ',{"id":"Q6","evidence_state":"证据不足","finding":"cut off'
    calls = []
    client = _client_with_responses([_response(content, "length"), _response(content, "length"), _response(json.dumps({"checks": [rows[-1]]}))], calls)()
    diagnostics = []
    data = screening._generate_complete_review(client, model="fake", system_prompt="rules", user_prompt="source", diagnostics=diagnostics)
    assert len(calls) == 3
    assert len(data["checks"]) == 19
    assert diagnostics[-1]["requested_ids"] == ["Q6"]
    assert "仅补全以下缺失ID：Q6" in calls[-1]["messages"][0]["content"]
    assert calls[-1]["max_tokens"] == 3200


def test_repair_with_wrong_or_duplicate_ids_still_fails_closed():
    rows = [screening._blank_check(cid) for cid in screening.CHECK_ORDER]
    partial = json.dumps({"checks": rows[:-1]})
    calls = []
    client = _client_with_responses([_response(partial), _response(partial), _response(json.dumps({"checks": [rows[-1], rows[-1]]}))], calls)()
    try:
        screening._generate_complete_review(client, model="fake", system_prompt="rules", user_prompt="source", diagnostics=[])
    except ValueError as error:
        assert "补写仍不完整" in str(error)
    else:
        raise AssertionError("duplicate repair IDs must not complete a review")
    assert len(calls) == 3


def test_missing_check_recovery_is_bounded_to_six_calls_and_five_check_batches():
    rows = [screening._blank_check(cid) for cid in screening.CHECK_ORDER]
    missing = rows[1:]
    responses = [_response(json.dumps({"checks": rows[:1]})), _response(json.dumps({"checks": rows[:1]}))]
    responses.extend(_response(json.dumps({"checks": missing[start:start+5]})) for start in range(0,len(missing),5))
    calls = []
    client = _client_with_responses(responses, calls)()
    diagnostics = []
    data = screening._generate_complete_review(client, model="fake", system_prompt="rules", user_prompt="source", diagnostics=diagnostics)
    assert len(calls) == 6 and len(data["checks"]) == 19
    assert all(len(item["requested_ids"]) <= 5 for item in diagnostics if item["phase"] == "missing_check_repair")


def test_screen_full_persists_recovery_diagnostics_and_preserves_all_evidence_gaps(monkeypatch, tmp_path):
    rows = [screening._blank_check(cid) for cid in screening.CHECK_ORDER]
    partial = json.dumps({"checks": rows[:-1]})
    calls = []
    responses = [_response(partial, "length"), _response(partial, "length"), _response(json.dumps({"checks": rows[-1:]}))]
    monkeypatch.setattr(screening, "OpenAI", _client_with_responses(responses, calls))
    result = screening.screen_full(company_name="CATL", stock_code="300750", report_type="半年度报告", report_year=2025,
        metrics={}, evidence_text="Provided company financial statements.", source_url="https://www.cninfo.com.cn/report.pdf", output_dir=tmp_path,
        api_key="fake", model="fake", base_url="https://api.example.test", test_mode=False)
    assert result["status"] == "完成" and not result["retryable"]
    assert len(result["unchecked"]) == 19 and result["conclusion"] == "待补证"
    assert result["generation_diagnostics"][-1]["requested_ids"] == ["Q6"]
    saved = json.loads(Path(result["json_path"]).read_text(encoding="utf-8"))
    assert saved["generation_diagnostics"][0]["finish_reason"] == "length"
