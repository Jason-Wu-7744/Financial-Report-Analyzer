import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import background_jobs
import i18n
import research_store


def test_job_launch_deduplicates_and_keeps_credentials_off_disk(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(background_jobs.subprocess, 'Popen', lambda *a, **kw: calls.append((a, kw)) or SimpleNamespace(pid=7))
    request = {'account': 'qa', 'research_id': 'job', 'chosen': [{'stock_code': '600519'}], 'api_key': 'must-not-persist'}
    first = background_jobs.launch_job(ROOT, tmp_path, 'en', request, 'process-only-secret')
    second = background_jobs.launch_job(ROOT, tmp_path, 'en', request, 'process-only-secret')
    assert first['token'] == second['token']
    assert len(calls) == 1
    assert calls[0][1]['env']['FILING_JOB_API_KEY'] == 'process-only-secret'
    for path in tmp_path.glob('*.json'):
        assert 'secret' not in path.read_text() and 'must-not-persist' not in path.read_text()


def test_worker_resumes_only_failed_phase(tmp_path, monkeypatch):
    import cninfo
    import engine
    import screening_engine
    import job_worker
    i18n.configure('zh')
    monkeypatch.setattr(job_worker, 'ROOT', tmp_path)
    monkeypatch.setattr(cninfo, 'load_cninfo_metadata', lambda *args: {'source_url': 'https://example.org/filing.pdf'})
    monkeypatch.setattr(engine, 'extract_pdf_pages', lambda *args: [engine.ExtractedPage(1, '合并现金流量表\n经营现金流 100', 1)])
    pdf = tmp_path / 'source.pdf'
    pdf.write_bytes(b'%PDF-test')
    item = {'stock_code': '600519', 'company_name': 'Example Corp', 'report_year': 2025,
            'report_type': '半年度报告', 'matched_pdf_path': str(pdf)}
    folder = research_store.research_dir(tmp_path, 'qa', 'resume')
    count = {'deep': 0, 'risk': 0}

    def deep(row, pdf, output, **kwargs):
        count['deep'] += 1
        base = {**item, 'path': str(output)}
        if count['deep'] == 1:
            return {**base, 'status': '失败', 'retryable': True}
        output.write_text('# Verified research', encoding='utf-8')
        return {**base, 'status': '完成', 'report_schema': 'research-memo-v8.1'}

    def risk(**kwargs):
        count['risk'] += 1
        out = kwargs['output_dir'] / 'risk.md'
        out.write_text('# Risk review', encoding='utf-8')
        return {**item, 'status': '完成', 'path': str(out), 'review_schema': 'evidence-review-v8.1'}

    monkeypatch.setattr(engine, 'comment_one_company', deep)
    monkeypatch.setattr(screening_engine, 'screen_full', risk)
    for token in ['first', 'second']:
        request = folder / f'deep-request-{token}.json'
        background_jobs.atomic_json(request, {'account': 'qa', 'research_id': 'resume', 'language': 'zh',
            'job_token': token, 'model': 'test', 'base_url': 'https://invalid.example', 'test_mode': True, 'chosen': [item]})
        background_jobs.atomic_json(background_jobs.job_path(folder, 'zh'), {'token': token, 'started_at': time.time()})
        job_worker.execute(request)
        state = background_jobs.read_job(background_jobs.job_path(folder, 'zh'))
        assert state['status'] == ('partial' if token == 'first' else 'completed')
    assert count == {'deep': 2, 'risk': 1}
    assert research_store.load_comments(tmp_path, 'qa', 'resume')[0]['status'] == '完成'


def test_worker_retries_english_export_without_regenerating_research(tmp_path, monkeypatch):
    import cninfo
    import engine
    import job_worker
    import screening_engine
    i18n.configure('en')
    monkeypatch.setattr(job_worker, 'ROOT', tmp_path)
    monkeypatch.setattr(i18n, 'localized_generation', lambda function: function)
    monkeypatch.setattr(engine, 'comment_one_company', lambda *a, **k: (_ for _ in ()).throw(AssertionError('model rerun')))
    monkeypatch.setattr(screening_engine, 'screen_full', lambda **k: (_ for _ in ()).throw(AssertionError('risk rerun')))
    monkeypatch.setattr(cninfo, 'load_cninfo_metadata', lambda *a: {})
    pdf = tmp_path / 'source.pdf'
    pdf.write_bytes(b'%PDF-test')
    markdown = tmp_path / 'canonical.md'
    markdown.write_text('# Valid source report', encoding='utf-8')
    item = {'stock_code': '600519', 'company_name': 'Example Corp', 'report_year': 2025,
            'report_type': '半年度报告', 'matched_pdf_path': str(pdf)}
    folder = research_store.research_dir(tmp_path, 'qa', 'translation')
    canonical = {**item, 'path': str(markdown), 'status': '完成', 'report_schema': 'research-memo-v8.1'}
    research_store.save_comments(tmp_path, 'qa', 'translation', [{**item, 'status': '失败',
        'translation_failed': True, 'retryable': True, 'canonical_result': canonical}])
    research_store.save_screenings(tmp_path, 'qa', 'translation', [{**item, 'path': str(markdown),
        'status': '完成', 'review_schema': 'evidence-review-v8.1'}])
    request = folder / 'deep-request-export-retry.json'
    background_jobs.atomic_json(request, {'account': 'qa', 'research_id': 'translation', 'language': 'en',
        'job_token': 'export-retry', 'model': 'test', 'base_url': 'https://invalid.example',
        'test_mode': False, 'chosen': [item]})
    background_jobs.atomic_json(background_jobs.job_path(folder, 'en'), {'token': 'export-retry', 'started_at': time.time()})
    job_worker.execute(request)
    result = research_store.load_comments(tmp_path, 'qa', 'translation')[0]
    assert result['status'] == '完成' and result['path'] == str(markdown)
    assert background_jobs.read_job(background_jobs.job_path(folder, 'en'))['status'] == 'completed'


def test_workspace_keeps_cards_next_to_saved_reports(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    original = research_store.user_dir
    monkeypatch.setattr(research_store, 'user_dir', lambda root, account: original(tmp_path, account))
    monkeypatch.setenv('DEEPSEEK_API_KEY', '')
    monkeypatch.setenv('OPENAI_API_KEY', '')
    for language in ['zh', 'en']:
        i18n.configure(language)
        meta = research_store.create_research(ROOT, 'workspace', 'Workspace example')
        item = {'stock_code': '600519', 'company_name': 'Example Corp', 'report_year': 2025,
                'report_type': '半年度报告', 'selected': True, 'status': '通过',
                'business': 'Consumer products', 'substance': 'Operating mix supported earnings.',
                'driver': 'Product mix', 'screening_conclusion': '暂定待补证'}
        report = tmp_path / f'brief-{language}.md'
        report.write_text('# Research brief\n\nEvidence-backed findings.', encoding='utf-8')
        research_store.save_summaries(ROOT, 'workspace', meta['id'], [item])
        research_store.save_comments(ROOT, 'workspace', meta['id'], [{**item, 'path': str(report), 'status': '完成'}])
        at = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=30)
        for key, value in {'ui_language': language, 'user_name': 'QA', 'user_account': 'workspace',
                           'view': 'research', 'research_id': meta['id'], 'summaries': [item],
                           'comments': [{**item, 'path': str(report), 'status': '完成'}]}.items():
            at.session_state[key] = value
        at.run()
        assert not at.exception, [x.message for x in at.exception]
        text = '\n'.join(x.value for x in at.markdown)
        assert 'research-cards-anchor' in text and 'research-reports-anchor' in text
        assert 'Operating mix supported earnings.' in text
        assert '杜邦三项' not in text and 'DuPont' not in text
        assert 'Evidence-backed findings.' in text
        assert at.checkbox(key='pick_600519_半年度报告_2025_0').value
