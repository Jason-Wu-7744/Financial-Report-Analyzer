import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from statement_scope import (
    statement_segments, statement_scope_context, income_records,
    financial_statement_scope_issues, displayed_cash_bridge_issues,
)


def source_pages():
    # Real CATL 2025H1 statement layout, including mixed-page boundary.
    return [
        SimpleNamespace(page=68, text="3、合并利润表\n单位：千元\n营业总收入\n178,886,253"),
        SimpleNamespace(page=69, text="四、利润总额\n38,812,500\n五、净利润\n32,365,447\n资产减值损失\n-2,498,964"),
        SimpleNamespace(page=70, text="合并利润表续页\n4、母公司利润表\n单位：千元\n营业收入"),
        SimpleNamespace(page=71, text="三、营业利润\n42,642,613\n四、利润总额\n42,662,371\n五、净利润\n38,112,809\n资产减值损失\n-1,378,501\n5、合并现金流量表\n单位：千元\n经营活动现金流"),
        SimpleNamespace(page=72, text="经营活动现金流量净额\n58,687,066"),
    ]


def test_mixed_page_title_is_not_retroactive():
    segments = [item for item in statement_segments(source_pages()) if item['page'] == 71]
    assert [item['scope'] for item in segments] == ['parent_only', 'consolidated']
    assert segments[0]['kind'] == 'income'
    assert segments[1]['kind'] == 'cashflow'
    assert segments[0]['title_page'] == 70
    records = income_records(source_pages())
    assert any(item['current'] == Decimal('32365447') and item['scope'] == 'consolidated' for item in records)
    assert any(item['current'] == Decimal('38112809') and item['scope'] == 'parent_only' for item in records)


def test_full_source_boundaries_are_supplied_for_selected_continuation():
    context = statement_scope_context(source_pages(), [source_pages()[3]])
    assert '母公司单体income' in context and '标题承接PDF第70页' in context
    assert '合并cashflow' in context


def test_cannot_compare_parent_profit_to_consolidated_cashflow():
    report = '同期合并净利润38,112,809千元[本期PDF第71页]；经营现金流58,687,066千元。'
    assert financial_statement_scope_issues(report, source_pages())


def test_generic_profit_and_converted_parent_amount_are_rejected():
    assert financial_statement_scope_issues('净利润381.12809亿元[本期PDF第71页]。', source_pages())
    assert financial_statement_scope_issues('营业利润42,642,613千元[本期PDF第71页]。', source_pages())


def test_correct_consolidated_and_explicit_parent_scope_are_allowed():
    assert not financial_statement_scope_issues('合并净利润32,365,447千元[本期PDF第69页]。', source_pages())
    assert not financial_statement_scope_issues('母公司单体净利润38,112,809千元[本期PDF第71页]。', source_pages())


def test_catl_original_rounding_discrepancy_not_zero():
    bad = '| 现金桥 | 期初270,159,734+经营58,687,066+投资-26,269,519+筹资20,607,571+汇率600,381=期末323,785,232千元 | 差额为0 |'
    issues = displayed_cash_bridge_issues(bad)
    assert len(issues) == 1 and '差额1' in issues[0]


def test_catl_tail_difference_explicitly_disclosed_is_not_silently_fixed():
    report = '| 现金桥 | 270,159,734+58,687,066-26,269,519+20,607,571+600,381=323,785,232千元 | 相差1千元，可能为列示舍入，待核对 |'
    assert not displayed_cash_bridge_issues(report)


def test_correct_bank_bridge_and_parenthesis_negative():
    assert not displayed_cash_bridge_issues('现金桥：4349.40 + (-369.05) + 308.72 = 4289.07亿美元；差额0。')
    assert not displayed_cash_bridge_issues('现金桥：4349.40+经营131.82+投资(-364.30)+筹资(-136.57)+汇兑308.72=4289.07亿美元。')


def test_wrong_bridge_without_zero_claim_still_requires_disclosure():
    assert displayed_cash_bridge_issues('现金桥：434.94-369.05+308.72=428.907亿美元。')


def test_unrelated_formula_and_undisplayed_bridge_not_claimed_checked():
    assert not displayed_cash_bridge_issues('简化现金结余：58,687,066-20,212,919=38,474,147千元。')
    assert not displayed_cash_bridge_issues('现金桥原文显示尾差，需要人工复核。')


def test_tencent_unit_after_opening_cash_is_not_dropped():
    text = '现金桥：期初现金及现金等价物132,519百万元＋经营净流入151,265－投资净流出72,407－融资净流出30,111＋汇兑收益791＝期末182,057百万元，勾稽一致。'
    assert not displayed_cash_bridge_issues(text)
    assert displayed_cash_bridge_issues(text.replace('期末182,057', '期末182,058'))
