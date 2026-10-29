"""Regressions for the missing-source Chinese card reported on 2026-10-29."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import engine
import i18n
from source_status import source_unavailable, source_failure_message, download_failure_for


@pytest.fixture(autouse=True)
def language():
    i18n.configure('zh')
    yield
    i18n.configure('zh')


def unavailable(**overrides):
    return dict(stock_code='002444', company_name='巨星科技', report_type='三季度报告',
                report_year=2026, headline='未匹配到全文', matched_pdf='', matched_pdf_path='',
                status='需复核', summary='没有找到 PDF 文件', selected=True, **overrides)


@pytest.mark.parametrize('lang', ['zh', 'en'])
def test_missing_pdf_never_calls_analysis_market_or_translation(tmp_path, monkeypatch, lang):
    def forbidden(*a, **k):
        raise AssertionError('No source: external calls must not run')
    monkeypatch.setattr(engine, 'load_market_metrics', forbidden)
    monkeypatch.setattr(engine, 'summarize_with_deepseek_fast', forbidden)
    monkeypatch.setattr(i18n, 'localize_summary', forbidden)
    i18n.configure(lang)
    result = i18n.localized_generation(engine.summarize_one_fast)(
        engine.CompanyRow(2, '002444', '巨星科技', {}), None, report_year=2026,
        report_type='三季度报告', api_key='not-used', model='not-used', base_url='not-used',
        test_mode=False, cache_dir=tmp_path,
        match_message='FileNotFoundError: 巨潮未找到 2026年三季度报告全文。')
    assert result['status'] == '失败' and result['retryable']
    assert source_unavailable(result) and not result['selected']
    if lang == 'en':
        assert not i18n.HAN.search(result['summary'])
        assert '2026' in result['summary'] and '002444' in result['summary']
        assert not result.get('translation_failed')
    else:
        assert '巨潮未找到' in result['message']


def test_chinese_generation_bypasses_broken_translator_and_preserves_source(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, 'load_market_metrics', lambda *a: None)
    monkeypatch.setattr(engine, 'extract_pdf_pages', lambda *a: [])
    monkeypatch.setattr(engine, 'validate_report_source', lambda *a: [])
    monkeypatch.setattr(engine, 'extract_key_financial_metrics', lambda *a: engine.KeyFinancialMetrics())
    monkeypatch.setattr(engine, 'select_evidence_pages', lambda *a, **k: [])
    monkeypatch.setattr(engine, 'extract_business_line', lambda *a: '手工具研发与销售')
    monkeypatch.setattr(engine, 'summarize_with_deepseek_fast', lambda *a: (
        '收入增长', '业务增长', '原始中文业务实质，不应受翻译影响。', '手工具研发与销售', 10, 10, .01, []))
    monkeypatch.setattr(engine, 'screen_fast', lambda **k: {'screening_conclusion': '暂定待补证'})
    monkeypatch.setattr(i18n, 'localize_summary', lambda *a: (_ for _ in ()).throw(AssertionError('translation called')))
    result = i18n.localized_generation(engine.summarize_one_fast)(
        engine.CompanyRow(2, '002444', '巨星科技', {}), tmp_path / '002444.pdf', report_year=2025,
        report_type='三季度报告', api_key='mock', model='mock', base_url='mock', test_mode=False, cache_dir=tmp_path)
    assert result['status'] == '通过'
    assert result['business'] == '手工具研发与销售'
    assert result['summary'] == '原始中文业务实质，不应受翻译影响。'


def test_old_saved_missing_pdf_is_recognized_but_real_summary_is_not():
    assert source_unavailable(unavailable())
    assert not source_unavailable({'stock_code': '002444', 'summary': '完整摘要', 'status': '需复核'})
    assert '尚未运行' in source_failure_message(unavailable(), is_english=False)
    assert '2026' in source_failure_message(unavailable(), is_english=True)


def test_download_error_stays_attached_to_its_own_company():
    records = [SimpleNamespace(stock_code='002444', pdf_path='', message='Official report not found'),
               SimpleNamespace(stock_code='600233', pdf_path='ok.pdf', message='Downloaded')]
    assert download_failure_for(records, '002444') == 'Official report not found'
    assert download_failure_for(records, '600233') == ''


@pytest.mark.parametrize('lang', ['zh', 'en'])
def test_old_missing_source_card_has_actionable_error_no_fake_business(tmp_path, monkeypatch, lang):
    from streamlit.testing.v1 import AppTest
    import research_store
    original = research_store.user_dir
    monkeypatch.setattr(research_store, 'user_dir', lambda root, account: original(tmp_path, account))
    monkeypatch.setenv('DEEPSEEK_API_KEY', '')
    monkeypatch.setenv('OPENAI_API_KEY', '')
    i18n.configure(lang)
    meta = research_store.create_research(ROOT, 'qa', 'Missing source regression')
    item = unavailable()
    research_store.save_summaries(ROOT, 'qa', meta['id'], [item])
    at = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=30)
    for key, value in {'ui_language': lang, 'user_name': 'QA', 'user_account': 'qa', 'view': 'research',
                       'research_id': meta['id'], 'summaries': [item], 'ds_test_mode': True}.items():
        at.session_state[key] = value
    at.run()
    assert not at.exception, [x.message for x in at.exception]
    assert any(('PDF' in x.value) for x in at.error)
    markup = '\n'.join(x.value for x in at.markdown)
    assert '候选页未写明主营业务' not in markup and 'Summary needs review' not in markup
    assert at.button(key='llm_pick_0_002444_巨星科技').disabled
    assert not at.session_state['summaries'][0]['selected']


@pytest.mark.parametrize('lang', ['zh', 'en'])
def test_manual_a_share_preflight_rejects_unavailable_period_before_analysis(tmp_path, monkeypatch, lang):
    from streamlit.testing.v1 import AppTest
    import research_store, cninfo
    original = research_store.user_dir
    monkeypatch.setattr(research_store, 'user_dir', lambda root, account: original(tmp_path, account))
    monkeypatch.setenv('DEEPSEEK_API_KEY', '')
    monkeypatch.setenv('OPENAI_API_KEY', '')
    monkeypatch.setattr(cninfo, 'parse_company_identifiers', lambda *a, **k: [SimpleNamespace(stock_code='002444', company_name='巨星科技')])
    calls = []
    monkeypatch.setattr(cninfo, 'search_reports_for_company', lambda *a, **k: calls.append(a) or [])
    i18n.configure(lang)
    meta = research_store.create_research(ROOT, 'qa', 'Preflight regression')
    at = AppTest.from_file(str(ROOT/'app.py'), default_timeout=30)
    for key, value in {'ui_language':lang, 'user_name':'QA', 'user_account':'qa', 'view':'research',
                       'research_id':meta['id'], 'company_source_A股':'直接输入名称/代码', 'source_mode':'巨潮资讯自动下载',
                       'ds_test_mode':True}.items():
        at.session_state[key] = value
    at.run()
    at.text_area[0].set_value('002444')
    next(x for x in at.selectbox if x.value == '半年度报告').set_value('三季度报告').run()
    next(x for x in at.number_input if x.label in {'报告期年份','Reporting year'}).set_value(2026).run()
    next(x for x in at.button if x.label in {'识别公司并列入右侧名单','Find companies and add to list'}).click().run()
    assert not at.exception, [x.message for x in at.exception]
    assert calls and calls[0][0:4] == ('002444','巨星科技',2026,'三季度报告')
    assert at.session_state['worklist'] == []
    assert at.session_state['summaries'] == []
    assert any('2026' in x.value for x in at.error)
