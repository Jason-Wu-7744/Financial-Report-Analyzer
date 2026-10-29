"""Regression: summary readiness is independent from risk clearance."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from card_presentation import preliminary_risk_html, summary_status_badge_html, summary_status_label


@pytest.mark.parametrize("is_english", [False, True])
def test_successful_summary_with_c7_remains_explicitly_excluded(is_english):
    badge = summary_status_badge_html("通过", is_english=is_english)
    risk = preliminary_risk_html("暂定淘汰", ["C7"], "Evidence confirms C7.", is_english=is_english)
    if is_english:
        assert ">Summary ready</span>" in badge
        assert ">Pass</span>" not in badge
        assert "Preliminary Risk Screening" in risk and "Preliminary Exclude" in risk
        assert "Triggers C7" in risk
    else:
        assert ">摘要已生成</span>" in badge
        assert ">通过</span>" not in badge
        assert "初步风险筛查" in risk and "暂定淘汰" in risk and "命中 C7" in risk
    assert "risk-kill" in risk and "Evidence confirms C7." in risk


@pytest.mark.parametrize("status, expected", [("需复核", "Summary needs review"), ("失败", "Summary failed"), ("", "Summary pending")])
def test_nonready_summary_has_scoped_status(status, expected):
    assert summary_status_label(status, is_english=True) == expected


def test_evidence_gap_is_not_recast_as_a_pass_and_notes_are_escaped():
    risk = preliminary_risk_html("暂定待补证", [], "<source> missing", is_english=True)
    assert "Preliminary Evidence Gap" in risk and "risk-gap" in risk
    assert "risk-pass" not in risk and "&lt;source&gt; missing" in risk


def test_card_ui_keeps_company_ticker_and_separate_summary_and_risk_scopes(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    import i18n
    import research_store

    original_user_dir = research_store.user_dir
    monkeypatch.setattr(research_store, "user_dir", lambda root, account: original_user_dir(tmp_path, account))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    i18n.configure("en")
    meta = research_store.create_research(ROOT, "qa", "Card status regression")
    item = {
        "stock_code": "000056", "company_name": "皇庭国际", "report_year": 2025,
        "report_type": "年度报告", "selected": True, "status": "通过",
        "business": "Commercial property operations.", "substance": "Operating cash flow remains a risk.",
        "driver": "Property revenue", "screening_conclusion": "暂定淘汰", "screening_hits": ["C7"],
        "screening_note": "Evidence confirms C7.",
    }
    research_store.save_summaries(ROOT, "qa", meta["id"], [item])
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    for key, value in {
        "ui_language": "en", "user_name": "QA", "user_account": "qa", "view": "research",
        "research_id": meta["id"], "summaries": [item], "llm_drawer_open": True,
        "llm_active_company_key": "000056", "ds_test_mode": True,
    }.items():
        at.session_state[key] = value
    at.run()
    assert not at.exception, [x.message for x in at.exception]
    markup = "\n".join(element.value for element in at.markdown)
    assert "000056" in markup and "Summary ready" in markup
    assert "Preliminary Risk Screening" in markup and "Preliminary Exclude" in markup
    assert "Triggers C7" in markup and ">Pass</span>" not in markup
    assert "translation unavailable" not in markup.lower()
    assert "1 selected company is ready for report generation." in [element.value for element in at.info]
    assert at.button(key="resume_deep_pass").label == "Generate selected reports"
    assert not any("incomplete or failed" in element.value.lower() for element in at.warning)
    assert at.session_state["summaries"][0]["status"] == "通过"
    assert at.session_state["summaries"][0]["screening_conclusion"] == "暂定淘汰"

    # The card uses a ticker mention, not a multiword translated company name;
    # submitting that same mention must select this issuer's filing context.
    at.button(key="llm_pick_0_000056_皇庭国际").click().run()
    assert "@000056" in at.chat_input[0].placeholder
    at.chat_input[0].set_value("@000056 Explain the earnings drivers.").run()
    assert not at.exception
    assert at.session_state["llm_active_company_key"].startswith("000056|")
    assert "000056" in at.session_state["llm_chat_messages"][-1]["company"]

    # Resume wording only applies after an actual report attempt was saved.
    at.session_state["comments"] = [{**item, "status": "失败", "message": "Generation failed.", "path": ""}]
    at.run()
    assert not at.exception
    assert at.button(key="resume_deep_pass").label == "Resume Incomplete Companies"
    assert any("incomplete or failed" in element.value.lower() for element in at.warning)
    i18n.configure("zh")
