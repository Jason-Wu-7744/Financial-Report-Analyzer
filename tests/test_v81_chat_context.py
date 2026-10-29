"""Clicked filing identity must survive follow-ups, aliases and report order."""
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from chat_context import report_chat_key, resolve_chat_context


ITEMS = [
    {'stock_code': '000089', 'company_name': '深圳机场', 'report_year': 2025, 'report_type': '年度报告', 'revenue_billion': 111},
    {'stock_code': '000089', 'company_name': '深圳机场', 'report_year': 2026, 'report_type': '三季度报告', 'revenue_billion': 987},
    {'stock_code': '000554', 'company_name': '泰山石油', 'report_year': 2025, 'report_type': '年度报告', 'revenue_billion': 222},
]


def english_name(name, code):
    return {'000089': 'Shenzhen Airport', '000554': 'Taishan Petroleum'}[code]


@pytest.mark.parametrize('question', ['Explain the earnings drivers.', 'What changed in cash flow?', '@000089 Explain the revenue.', '@Shenzhen Airport What changed?', '@深圳机场 请解释收入。'])
def test_plain_followups_and_issuer_aliases_keep_the_clicked_report(question):
    selected, cleaned = resolve_chat_context(ITEMS, report_chat_key(ITEMS[1]), question, english_name)
    assert selected is ITEMS[1]
    assert selected['report_year'] == 2026
    assert selected['revenue_billion'] == 987
    assert not cleaned.startswith('@')


def test_other_ticker_explicitly_switches_and_strips_only_its_mention():
    selected, cleaned = resolve_chat_context(ITEMS, report_chat_key(ITEMS[1]), '@000554 Explain the margin.', english_name)
    assert selected is ITEMS[2]
    assert cleaned == 'Explain the margin.'


@pytest.mark.parametrize('mention', ['@000', '@Unknown Company', '@Shenzhen AirportX'])
def test_unrecognized_or_partial_mentions_cannot_choose_another_filing(mention):
    question = mention + ' explain the result'
    selected, cleaned = resolve_chat_context(ITEMS, report_chat_key(ITEMS[1]), question, english_name)
    assert selected is ITEMS[1]
    assert cleaned == question


def test_no_selection_and_unknown_mention_provides_no_fabricated_context():
    selected, cleaned = resolve_chat_context(ITEMS, '', '@000 explain the result', english_name)
    assert selected == {}
    assert cleaned == '@000 explain the result'


def test_filing_identity_includes_period_and_does_not_mutate_domain_data():
    assert report_chat_key(ITEMS[0]) != report_chat_key(ITEMS[1])
    assert report_chat_key(ITEMS[1]) == '000089|2026|三季度报告'
    assert ITEMS[0]['report_type'] == '年度报告'
