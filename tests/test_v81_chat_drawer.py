"""Offline integration regression for the independent company chat drawer."""
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_company_drawer_supports_followups_report_identity_and_reopening(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    import chat_panel
    from chat_context import report_chat_key
    import deep_research
    import engine
    import i18n
    import research_store

    original_user_dir = research_store.user_dir
    monkeypatch.setattr(research_store, 'user_dir', lambda root, account: original_user_dir(tmp_path, account))
    monkeypatch.setenv('DEEPSEEK_API_KEY', '')
    monkeypatch.setenv('OPENAI_API_KEY', '')
    i18n.configure('en')
    meta = research_store.create_research(ROOT, 'chatqa', 'Chat drawer regression')
    items = []
    for code, name, year, kind, revenue in [
        ('000089', '深圳机场', 2025, '年度报告', 111),
        ('000089', '深圳机场', 2026, '三季度报告', 987),
        ('000554', '泰山石油', 2025, '年度报告', 222),
    ]:
        pdf = tmp_path / f'{code}-{year}.pdf'
        pdf.write_bytes(b'fake PDF; extraction is stubbed')
        items.append({
            'stock_code': code, 'company_name': name, 'report_year': year, 'report_type': kind,
            'revenue_billion': revenue, 'status': '通过', 'selected': True,
            'business': 'Filing-specific business.', 'driver': 'Revenue and cash flow.',
            'substance': 'Review source evidence.', 'screening_conclusion': '暂定待补证',
            'screening_hits': [], 'screening_note': 'Further evidence is required.',
            'matched_pdf_path': str(pdf),
        })
    research_store.save_summaries(ROOT, 'chatqa', meta['id'], items)
    monkeypatch.setattr(engine, 'extract_pdf_pages', lambda path, cache: [
        SimpleNamespace(page=7, text=f'FILING_EVIDENCE_{Path(path).stem}')])
    monkeypatch.setattr(deep_research, 'select_deep_evidence', lambda pages, **kwargs: pages)
    original_drawer = chat_panel.render_chat_drawer
    captured = []

    def fake_reply(question, *, prepared_messages):
        captured.append({'question': question, 'messages': prepared_messages})
        yield 'content', 'The selected filing evidence is available. '
        yield 'content', 'Follow-up questions keep this report context.'

    def offline_drawer(state, **kwargs):
        kwargs['stream_reply'] = fake_reply
        return original_drawer(state, **kwargs)

    monkeypatch.setattr(chat_panel, 'render_chat_drawer', offline_drawer)
    at = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=30)
    for key, value in {
        'ui_language': 'en', 'user_name': 'QA', 'user_account': 'chatqa', 'view': 'research',
        'research_id': meta['id'], 'summaries': items, 'llm_drawer_open': False,
    }.items():
        at.session_state[key] = value
    at.run()
    assert not at.exception
    entries = [button for button in at.button if str(button.key or '').startswith('llm_pick_')]
    assert len(entries) == len(items)
    assert all(button.label == '' for button in entries)
    assert len([button for button in at.button if button.key == 'llm_drawer_toggle']) == 1
    assert len(at.chat_input) == 0

    # The second card is the same ticker's newer filing. It must not resolve to
    # the first annual report just because ticker/name are identical.
    at.button(key='llm_pick_1_000089_深圳机场').click().run()
    assert not at.exception
    assert at.session_state['llm_active_company_key'] == report_chat_key(items[1])
    assert len(at.chat_input) == 1
    at.chat_input[0].set_value('What drove revenue?').run()
    assert not at.exception
    assert len(at.session_state['llm_chat_messages']) == 2
    first_context = '\n'.join(message['content'] for message in captured[0]['messages'])
    assert 'FILING_EVIDENCE_000089-2026' in first_context
    assert 'FILING_EVIDENCE_000089-2025' not in first_context
    assert '987' in first_context and '111' not in first_context
    assert captured[0]['messages'][-1]['content'] == 'What drove revenue?'

    at.chat_input[0].set_value('And what about cash flow?').run()
    assert not at.exception
    assert len(at.session_state['llm_chat_messages']) == 4
    second_prompt = captured[1]['messages']
    assert any(message['content'] == 'What drove revenue?' for message in second_prompt)
    assert any('Follow-up questions keep this report context.' in message['content'] for message in second_prompt)
    assert 'FILING_EVIDENCE_000089-2026' in '\n'.join(message['content'] for message in second_prompt)

    # Close/reopen and a repeat click are presentation actions, not resets.
    at.button(key='llm_chat_close').click().run()
    assert not at.exception and len(at.chat_input) == 0
    at.button(key='llm_drawer_toggle').click().run()
    assert not at.exception and len(at.chat_input) == 1
    assert len(at.session_state['llm_chat_messages']) == 4
    at.button(key='llm_pick_1_000089_深圳机场').click().run()
    assert len(at.session_state['llm_chat_messages']) == 4

    # Switching to another issuer gets its own context and transcript. Going
    # back restores only the original report's conversation.
    at.button(key='llm_pick_2_000554_泰山石油').click().run()
    assert not at.exception
    assert at.session_state['llm_chat_messages'] == []
    at.chat_input[0].set_value('Explain this business.').run()
    assert not at.exception
    third_context = '\n'.join(message['content'] for message in captured[-1]['messages'])
    assert 'FILING_EVIDENCE_000554-2025' in third_context
    assert 'What drove revenue?' not in third_context
    assert len(at.session_state['llm_chat_messages']) == 2
    at.button(key='llm_pick_1_000089_深圳机场').click().run()
    assert len(at.session_state['llm_chat_messages']) == 4
    at.button(key='llm_pick_0_000089_深圳机场').click().run()
    assert at.session_state['llm_chat_messages'] == []
    assert at.session_state['llm_active_company_key'] == report_chat_key(items[0])
    at.button(key='llm_pick_1_000089_深圳机场').click().run()
    assert len(at.session_state['llm_chat_messages']) == 4
    i18n.configure('zh')
