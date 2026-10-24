"""Independent report worker. Checkpoint each company and phase for resume."""
from __future__ import annotations

import json
import copy
import os
import sys
import threading
import time
from dataclasses import fields
from pathlib import Path

from dotenv import load_dotenv
from background_jobs import atomic_json, job_path, read_job

ROOT = Path(__file__).resolve().parent


def execute(request_path: Path) -> None:
    import research_store
    from cninfo import CninfoAnnouncement, download_announcements, download_reports_for_rows, load_cninfo_metadata
    from engine import CompanyRow, comment_one_company, extract_pdf_pages, match_pdf
    from deep_research import select_deep_evidence
    from screening_engine import screen_full, cninfo_search_url
    from i18n import configure, EnglishTranslator, localized_generation

    request = json.loads(request_path.read_text(encoding='utf-8'))
    account, research_id = request['account'], request['research_id']
    language = request.get('language', 'zh')
    folder = research_store.research_dir(ROOT, account, research_id)
    if request_path.resolve().parent != folder.resolve():
        raise ValueError('Job request must belong to this research')
    path = job_path(folder, language)
    state = read_job(path)
    if state.get('token') != request['job_token']:
        return
    load_dotenv(ROOT / '.env')
    api_key = os.getenv('FILING_JOB_API_KEY', '') or os.getenv('DEEPSEEK_API_KEY', '') or os.getenv('OPENAI_API_KEY', '')
    model = request['model']
    base_url = request['base_url']
    configure(language, EnglishTranslator(api_key, model, base_url))
    comment_fn = localized_generation(comment_one_company)
    risk_fn = localized_generation(screen_full)
    mutex = threading.Lock()
    stop = threading.Event()

    def update(**changes):
        with mutex:
            state.update(changes, heartbeat=time.time())
            atomic_json(path, state)

    def heartbeat():
        while not stop.wait(10):
            update()

    update(status='running', pid=os.getpid(), phase='source')
    monitor = threading.Thread(target=heartbeat, daemon=True)
    monitor.start()
    comments = research_store.load_comments(ROOT, account, research_id)
    screenings = research_store.load_screenings(ROOT, account, research_id)

    def key(item):
        return '|'.join(str(item.get(k) or '') for k in ('stock_code', 'report_year', 'report_type'))

    comment_map = {key(x): x for x in comments}
    risk_map = {key(x): x for x in screenings}

    def checkpoint():
        research_store.save_comments(ROOT, account, research_id, list(comment_map.values()))
        research_store.save_screenings(ROOT, account, research_id, list(risk_map.values()))

    def valid(item, phase):
        return bool(item and not item.get('retryable') and item.get('status') not in {'失败', 'failed'}
                    and item.get('path') and Path(item['path']).is_file()
                    and (item.get('report_schema') == 'research-memo-v8.1' if phase == 'deep'
                         else item.get('review_schema') == 'evidence-review-v8.1'))

    def generate_or_translate(previous, phase, generate):
        """Retry an English export from its validated source without another model report."""
        if language == 'en' and isinstance(previous, dict) and previous.get('translation_failed'):
            canonical = previous.get('canonical_result')
            if isinstance(canonical, dict) and valid(canonical, phase):
                return localized_generation(lambda: copy.deepcopy(canonical))()
        return generate()

    def timed(phase, ticker, function):
        update(phase=phase, ticker=ticker)
        started = time.perf_counter()
        try:
            result = function()
            return result
        finally:
            event = {'ticker': ticker, 'phase': phase, 'seconds': round(time.perf_counter() - started, 3)}
            state.setdefault('events', []).append(event)
            update()

    failures = []
    try:
        chosen = request.get('chosen') or []
        for index, item in enumerate(chosen):
            ticker = item['stock_code']
            year, report_type = int(item['report_year']), item['report_type']
            item_key = key(item)
            try:
                row = CompanyRow(index + 2, ticker, item['company_name'], {})
                update(phase='source', ticker=ticker, completed=index)
                raw_pdf = str(item.get('matched_pdf_path') or '')
                pdf = Path(raw_pdf) if raw_pdf else None
                if not pdf or not pdf.is_file():
                    ann_key = f'{ticker}|{report_type}|{year}|'
                    payload = request.get('announcements', {}).get(ann_key)
                    if payload:
                        allowed = {f.name for f in fields(CninfoAnnouncement)}
                        announcement = CninfoAnnouncement(**{k: v for k, v in payload.items() if k in allowed})
                        pdfs, _ = download_announcements([announcement], ROOT / '.cache' / 'cninfo')
                    else:
                        pdfs, _ = download_reports_for_rows([row], year, report_type, ROOT / '.cache' / 'cninfo')
                    pdf, _ = match_pdf(row, pdfs)
                if not pdf:
                    raise ValueError('Official report PDF could not be verified')
                if not valid(comment_map.get(item_key), 'deep'):
                    out = research_store.comments_dir(ROOT, account, research_id) / research_store.safe_comment_filename(ticker, row.company_name, year, report_type)
                    result = timed('deep', ticker, lambda: generate_or_translate(comment_map.get(item_key), 'deep', lambda: comment_fn(
                        row, pdf, out, report_type=report_type, report_year=year, cache_dir=ROOT / '.cache',
                        api_key=api_key, model=model, base_url=base_url, test_mode=request.get('test_mode', False),
                        max_pages=request.get('max_pages', 28), max_chars=request.get('max_chars', 70000),
                        disclosure_date=str(item.get('disclosure_date') or ''))))
                    comment_map[item_key] = result
                    checkpoint()
                    if not valid(result, 'deep'):
                        failures.append(ticker + ': deep')
                if not valid(risk_map.get(item_key), 'risk'):
                    update(phase='evidence', ticker=ticker)
                    pages = extract_pdf_pages(pdf, ROOT / '.cache' / 'pdf_text')
                    selected = select_deep_evidence(pages, max_pages=36, max_chars=90000)
                    evidence = '\n\n'.join(f'===== PDF第{p.page}页 =====\n{p.text}' for p in selected)
                    metadata = load_cninfo_metadata(pdf)
                    result = timed('risk', ticker, lambda: generate_or_translate(risk_map.get(item_key), 'risk', lambda: risk_fn(
                        company_name=row.company_name, stock_code=ticker, report_type=report_type, report_year=year,
                        metrics=row.metrics or {}, evidence_text=evidence,
                        source_url=metadata.get('source_url') or cninfo_search_url(ticker),
                        output_dir=research_store.screenings_dir(ROOT, account, research_id),
                        api_key=api_key, model=model, base_url=base_url, test_mode=request.get('test_mode', False),
                        industry=str(item.get('business') or ''), disclosure_date=str(item.get('disclosure_date') or ''))))
                    risk_map[item_key] = result
                    checkpoint()
                    if not valid(result, 'risk'):
                        failures.append(ticker + ': risk')
                update(completed=index + 1)
            except Exception as error:
                failures.append(ticker + ': ' + type(error).__name__)
                update(last_error=str(error))
                checkpoint()
        update(status='partial' if failures else 'completed', phase='done', failures=failures, finished_at=time.time())
    except Exception as error:
        update(status='failed', phase='failed', last_error=str(error))
        raise
    finally:
        stop.set()
        monitor.join(timeout=2)
        request_path.unlink(missing_ok=True)


if __name__ == '__main__':
    execute(Path(sys.argv[1]))
