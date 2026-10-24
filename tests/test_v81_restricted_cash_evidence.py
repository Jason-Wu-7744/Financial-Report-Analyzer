"""Actual CATL 2025H1 note layout: exclusions start on PDF147, end PDF148."""
from dataclasses import dataclass
import json
from pathlib import Path

from deep_research import TOPICS, topic_score, select_deep_evidence, supplement_deep_evidence


@dataclass
class Page:
    page: int
    text: str
    score: int = 0


def notes():
    raw = json.loads((Path(__file__).parent / "fixtures/catl_2025h1_cash_availability_notes.json").read_text(encoding="utf-8"))
    return {item["page"]: Page(**item) for item in raw}


def statements():
    return [Page(63, "合并资产负债表\n资产总计1,000,000\n负债合计300,000\n所有者权益合计700,000"),
            Page(68, "合并利润表\n营业收入900,000\n利润总额200,000\n所得税费用20,000"),
            Page(72, "合并现金流量表\n经营活动产生300,000\n投资活动200,000\n筹资活动产生100,000")]


def test_actual_detailed_exclusions_outrank_general_pledged_assets():
    original = notes()
    assert topic_score(original[147].text, TOPICS["restricted_cash"]) > topic_score(original[19].text, TOPICS["restricted_cash"])
    assert topic_score(original[147].text, TOPICS["restricted_cash"]) > topic_score(original[131].text, TOPICS["restricted_cash"])


def test_cash_availability_and_continuation_survive_preferred_page_pressure():
    original = notes()
    pages = [Page(i, "主营业务 分部信息 管理层讨论 账龄 到期分析 " * 160) for i in range(1, 174)]
    for page in [*statements(), *original.values()]:
        pages[page.page - 1] = page
    selected = select_deep_evidence(pages, preferred_pages=pages[:32], max_pages=32, max_chars=68000)
    selected_map = {item.page: item for item in selected}
    assert selected_map[147].text == original[147].text
    assert selected_map[148].text == original[148].text
    assert selected_map[146].text == original[146].text
    text = selected_map[147].text + selected_map[148].text
    for amount in ("16,320,022", "536,136", "9,936,355", "26,792,514"):
        assert amount in text
    assert len(selected) <= 32
    assert sum(len(item.text) for item in selected) <= 68000
    assert pages[146].text == original[147].text  # cache pages were not mutated


def test_supplement_detailed_breakdown_even_when_generic_restrictions_covered():
    original = notes()
    pages = sorted([*statements(), *original.values()], key=lambda item: item.page)
    selected = [original[19], *statements()]
    supplemented = supplement_deep_evidence(pages, selected, max_pages=7, max_chars=25000)
    by_page = {item.page: item for item in supplemented}
    assert by_page[146].text == original[146].text
    assert by_page[147].text == original[147].text
    assert by_page[148].text == original[148].text
    assert len(supplemented) <= 7
    assert sum(len(item.text) for item in supplemented) <= 25000


def test_ordinary_bank_deposits_do_not_establish_cash_restrictions():
    assert not topic_score("Customer deposits 1,000,000; bank balances 500,000", TOPICS["restricted_cash"])


def test_actual_consolidated_income_continuation_survives_numeric_policy_examples():
    raw = json.loads((Path(__file__).parent / "fixtures/catl_2025h1_consolidated_income_continuations.json").read_text(encoding="utf-8"))
    original = {item["page"]: Page(**item) for item in raw}
    pages = [Page(i, "主营业务 分部信息 " * 160) for i in range(1, 174)]
    for page in [*statements(), *original.values()]:
        pages[page.page - 1] = page
    selected = select_deep_evidence(pages, preferred_pages=pages[:32], max_pages=32, max_chars=68000)
    by_page = {item.page: item for item in selected}
    assert by_page[68].text == original[68].text
    assert by_page[69].text == original[69].text
    assert "32,365,447" in by_page[69].text
    assert by_page[72].text == original[72].text
    assert by_page[73].text == original[73].text
    assert sum(len(item.text) for item in selected) <= 68000
