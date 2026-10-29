"""The drawer retries an existing answer's translation without duplicating chat."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_chinese_question_is_preserved_and_retry_replaces_only_failed_answer(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    import chat_panel
    from chat_context import report_chat_key
    from chat_state import chat_scope
    from chat_translation import ChatTranslationError
    import i18n
    import research_store

    original_user_dir = research_store.user_dir
    monkeypatch.setattr(research_store, 'user_dir', lambda root, account: original_user_dir(tmp_path, account))
    monkeypatch.setenv('DEEPSEEK_API_KEY', '')
    monkeypatch.setenv('OPENAI_API_KEY', '')
    i18n.configure('en')
    meta = research_store.create_research(ROOT, 'retryqa', 'Translation retry regression')
    items = []
    for code, name, business in [('000089', '深圳机场', 'Airport operations.'), ('000554', '泰山石油', 'Petroleum distribution.')]:
        items.append({
            'stock_code': code, 'company_name': name, 'report_year': 2025, 'report_type': '年度报告',
            'status': '通过', 'selected': True, 'business': business,
            'driver': 'Operating performance.', 'substance': 'Review filing evidence.',
            'screening_conclusion': '暂定待补证', 'screening_hits': [],
            'screening_note': 'Further evidence is required.',
        })
    research_store.save_summaries(ROOT, 'retryqa', meta['id'], items)
    scope_state = {'user_account': 'retryqa', 'research_id': meta['id'], 'ui_language': 'en'}
    current_scope = chat_scope(scope_state, report_chat_key(items[0]))
    other_scope = chat_scope(scope_state, report_chat_key(items[1]))
    question = '主营是什么'
    generated_source = '主营业务为机场运营。'
    english_answer = 'Its principal business is airport operations.'
    calls, financial_generation_calls = [], []
    original_drawer = chat_panel.render_chat_drawer

    def offline_drawer(state, **kwargs):
        def fake_reply(message, *, prepared_messages):
            calls.append({'question': message, 'messages': prepared_messages})
            assert message == question
            assert prepared_messages[-1]['content'] == question
            drafts = state.setdefault('llm_chat_answer_drafts', {})
            if len(calls) == 1:
                financial_generation_calls.append(message)
                drafts['failed-answer'] = {'source': generated_source, 'scope': current_scope, 'question': message}
                yield 'translation', ''
                raise ChatTranslationError('Stubbed temporary translation failure', source_text=generated_source, cache_key='failed-answer')
            # The retry consumes the existing completed financial answer. It
            # does not perform a second financial-generation step.
            assert drafts['failed-answer']['source'] == generated_source
            assert drafts['failed-answer']['scope'] == current_scope
            yield 'translation', ''
            drafts.pop('failed-answer')
            yield 'replace', english_answer
        kwargs['stream_reply'] = fake_reply
        return original_drawer(state, **kwargs)

    monkeypatch.setattr(chat_panel, 'render_chat_drawer', offline_drawer)
    at = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=30)
    for key, value in {
        'ui_language': 'en', 'user_name': 'QA', 'user_account': 'retryqa', 'view': 'research',
        'research_id': meta['id'], 'summaries': items, 'llm_drawer_open': False,
    }.items():
        at.session_state[key] = value
    at.run()
    at.button(key='llm_pick_0_000089_深圳机场').click().run()
    assert not at.exception
    at.chat_input[0].set_value(question).run()
    assert not at.exception
    failed = at.session_state['llm_chat_messages']
    assert len(failed) == 2
    assert failed[0]['role'] == 'user' and failed[0]['content'] == question
    assert failed[1]['role'] == 'assistant' and failed[1]['error']
    assert failed[1]['retry_translation'] is True
    assert failed[1]['question'] == question
    assert 'English translation needs another attempt' in failed[1]['content']
    assert generated_source not in failed[1]['content']
    assert at.session_state['llm_chat_scope'] == current_scope
    assert at.button(key='llm_retry_translation_1').label == 'Retry translation'
    assert any(element.value == question for element in at.markdown)

    at.button(key='llm_retry_translation_1').click().run()
    assert not at.exception
    messages = at.session_state['llm_chat_messages']
    assert len(messages) == 2
    assert messages[0]['content'] == question
    assert messages[1]['content'] == english_answer
    assert not messages[1].get('error') and not messages[1].get('retry_translation')
    assert len(calls) == 2 and financial_generation_calls == [question]
    assert at.session_state['llm_pending_prompt'] == ''
    assert at.session_state['llm_chat_scope'] == current_scope
    assert at.session_state['llm_active_company_key'] == report_chat_key(items[0])
    assert at.session_state['llm_chat_answer_drafts'] == {}
    assert not [button for button in at.button if str(button.key or '').startswith('llm_retry_translation_')]
    assert at.session_state['llm_chat_conversations'][current_scope]['messages'] == messages

    # New conversation clears this report's unfinished translations while
    # preserving both another report's draft and its saved conversation.
    other_messages = [{'role': 'user', 'content': 'Other report question.'},
                      {'role': 'assistant', 'content': 'Other report answer.'}]
    at.session_state['llm_chat_conversations'] = {
        **at.session_state['llm_chat_conversations'],
        other_scope: {'messages': other_messages, 'last_status': 'Reply complete'},
    }
    at.session_state['llm_chat_answer_drafts'] = {
        'current-unused': {'source': '当前报告草稿', 'scope': current_scope, 'question': 'A'},
        'other-unused': {'source': '另一报告草稿', 'scope': other_scope, 'question': 'B'},
    }
    at.button(key='llm_chat_new').click().run()
    assert not at.exception
    assert at.session_state['llm_chat_messages'] == []
    assert set(at.session_state['llm_chat_answer_drafts']) == {'other-unused'}
    assert at.session_state['llm_chat_conversations'][current_scope]['messages'] == []
    assert at.session_state['llm_chat_conversations'][other_scope]['messages'] == other_messages
    at.button(key='llm_pick_1_000554_泰山石油').click().run()
    assert not at.exception
    assert at.session_state['llm_chat_messages'] == other_messages
    assert at.session_state['llm_chat_scope'] == other_scope
    i18n.configure('zh')
