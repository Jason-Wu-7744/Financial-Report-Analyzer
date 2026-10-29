"""Offline reproductions of the provider JSON contract and chat retry path."""
import ast
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import i18n
import ui_i18n
from chat_state import chat_scope
from chat_translation import ChatTranslationError


@pytest.fixture(autouse=True)
def reset_language():
    i18n.configure('zh')
    yield
    i18n.configure('zh')


def json_constrained_provider(monkeypatch, respond):
    """Model DeepSeek's real 400 guard instead of accepting malformed prompts."""
    requests = []
    def create(**request):
        requests.append(request)
        if request.get('response_format') == {'type': 'json_object'}:
            messages = '\n'.join(str(message.get('content', '')) for message in request['messages'])
            if 'json' not in messages.lower():
                raise ValueError("400: Prompt must contain the word 'json'")
        value = respond(request, len(requests))
        return NS(choices=[NS(message=NS(content=json.dumps(value, ensure_ascii=False)))], usage=None)
    client = NS(chat=NS(completions=NS(create=create)))
    monkeypatch.setattr('openai.OpenAI', lambda **kwargs: client)
    return client, requests


def test_single_text_translation_satisfies_real_json_mode_contract(monkeypatch):
    client, requests = json_constrained_provider(
        monkeypatch, lambda *_: {'text': 'Its principal business is express delivery services.'})
    translator = i18n.EnglishTranslator('fake-key', 'fake-model', 'https://api.deepseek.com')
    source = '主要业务是快递服务。'
    result = translator.text(source)
    assert result == 'Its principal business is express delivery services.'
    assert not i18n.translation_validation_errors(source, result)
    assert len(requests) == 1
    assert requests[0]['extra_body'] == {'thinking': {'type': 'disabled'}}
    assert 'json' in requests[0]['messages'][0]['content'].lower()


def test_single_fixed_fact_recovery_keeps_json_instruction_and_facts(monkeypatch):
    source = '收入100，上期80，增长20%，目标90，预测120'
    masked, tokens = i18n.protected_translation_input(source, financial_context=True)
    requested = {str(index): part for index, (part, needed) in
                 enumerate(i18n.fixed_fact_prose_plan(masked, tokens)) if needed}
    assert len(requested) == 5
    bad_key = list(requested)[-1]
    good = {key: part.replace('收入', 'Revenue').replace('，上期', ', prior')
                     .replace('，增长', ', growth').replace('，目标', ', target')
            for key, part in requested.items() if key != bad_key}
    responses = [good, {}, {'text': ', forecast'}]
    client, requests = json_constrained_provider(monkeypatch, lambda _, count: responses[count-1])
    translator = i18n.EnglishTranslator('fake-key', 'fake-model', 'https://api.deepseek.com')
    result = translator._translate_fixed_fact_prose(source, masked, tokens, client)
    assert not i18n.translation_validation_errors(source, result)
    assert len(requests) == 3 and translator.fixed_fact_fallback_calls == 3
    final_request = requests[-1]
    assert 'json' in final_request['messages'][0]['content'].lower()
    assert '"text"' in final_request['messages'][0]['content']
    assert 'mapping every exact prose span ID' not in final_request['messages'][0]['content']
    assert i18n.numeric_tokens(result) == i18n.numeric_tokens(source)


def test_static_tabs_and_cover_caption_never_need_an_api():
    class NoProvider:
        cache = {}
        calls = 0
        def text(self, value):
            self.calls += 1
            raise AssertionError('A static UI label must not require provider translation')
    translator = NoProvider()
    i18n.configure('en', translator)
    captured = {}
    class Surface:
        def tabs(self, labels):
            captured['tabs'] = labels
            return [NS(), NS()]
        def caption(self, value):
            captured['caption'] = value
    adapter = ui_i18n.StreamlitUI(Surface())
    adapter.tabs(['深度研究', '风险核验'])
    adapter.caption('输出仅供研究辅助，不构成投资建议。')
    assert captured['tabs'] == ['Deep Research', 'Risk Review']
    assert captured['caption'] == i18n.CATALOG['输出仅供研究辅助，不构成投资建议。']
    assert not i18n.HAN.search(captured['caption'])
    assert 'translation unavailable' not in captured['caption'].lower()
    assert translator.calls == 0


class State(dict):
    def __getattr__(self, key):
        return self[key]
    def __setattr__(self, key, value):
        self[key] = value


def extracted_chat_stream(state, create, repair):
    """Compile the real boundary only; no UI boot, keys or external calls."""
    source = ast.parse((ROOT / 'app.py').read_text(encoding='utf-8'))
    function = next(node for node in source.body if isinstance(node, ast.FunctionDef)
                    and node.name == 'stream_general_llm')
    namespace = {
        'st': NS(session_state=state), 'hashlib': hashlib, 'chat_scope': chat_scope,
        '_active_summary_from_message': lambda _: {'company_name': '圆通速递', 'stock_code': '600233'},
        'company_display_name': lambda *_: 'YTO Express', 'company_display_label': lambda *_: 'YTO Express (600233)',
        'english': lambda: True, 'api_key': 'fake-key', 'model': 'fake-model',
        'base_url': 'https://api.deepseek.com', 'ensure_english_chat_reply': repair,
        'translation_api_options': i18n.translation_api_options, 'time': time, 're': re,
        'httpx_runtime': NS(Timeout=lambda *args, **kwargs: None),
        'OpenAI': lambda **kwargs: NS(chat=NS(completions=NS(create=create))),
        'build_llm_messages': lambda question: ([{'role': 'user', 'content': question}], '', 'YTO Express (600233)'),
    }
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(ROOT / 'app.py'), 'exec'), namespace)
    return namespace['stream_general_llm']


def test_failed_language_repair_reuses_the_generated_answer_on_retry():
    state = State(ui_language='en', user_account='qa', research_id='translation-test',
                  llm_active_company_key='600233|2026|三季度报告', ds_test_mode=False)
    raw = '圆通速递主营快递服务。Revenue grew 7.8%.'
    qa_requests, repair_inputs = [], []
    def create(**request):
        qa_requests.append(request)
        return iter([NS(choices=[NS(delta=NS(content=raw, reasoning_content=None))])])
    def repair(value, **kwargs):
        repair_inputs.append(value)
        if len(repair_inputs) == 1:
            raise ChatTranslationError('Temporary translation failure', source_text=value, cache_key='test-draft')
        return 'YTO Express principally provides express delivery services. Revenue grew 7.8%.'
    stream = extracted_chat_stream(state, create, repair)
    with pytest.raises(ChatTranslationError):
        list(stream('主营是什么'))
    assert len(qa_requests) == 1
    assert len(state['llm_chat_answer_drafts']) == 1
    assert next(iter(state['llm_chat_answer_drafts'].values()))['source'] == raw
    assert 'fake-key' not in json.dumps(state, ensure_ascii=False)
    result = list(stream('主营是什么'))
    assert result[-1][0] == 'replace' and 'express delivery services' in result[-1][1]
    assert len(qa_requests) == 1, 'A translation retry must not regenerate the financial answer'
    assert repair_inputs == [raw, raw]
    assert state['llm_chat_answer_drafts'] == {}


def test_english_stream_is_not_retranslated_or_repeated():
    state = State(ui_language='en', user_account='qa', research_id='english-test',
                  llm_active_company_key='600233|2026|三季度报告', ds_test_mode=False)
    chunks = ['Revenue grew ', '7.8%.']
    calls = []
    def create(**request):
        calls.append(request)
        return iter([NS(choices=[NS(delta=NS(content=piece, reasoning_content=None))]) for piece in chunks])
    def unexpected_translation(*args, **kwargs):
        raise AssertionError('Already-English text must not be translated again')
    stream = extracted_chat_stream(state, create, unexpected_translation)
    assert list(stream('Quote revenue growth.')) == [('content', piece) for piece in chunks]
    assert len(calls) == 1 and state['llm_chat_answer_drafts'] == {}


def test_retry_button_replaces_failed_translation_without_duplicate_question():
    from streamlit.testing.v1 import AppTest
    source = f'''
import sys
sys.path.insert(0, {str(ROOT)!r})
import streamlit as st
from chat_panel import render_chat_drawer
from chat_translation import ChatTranslationError
defaults = {{'llm_chat_messages': [], 'llm_pending_prompt': '', 'llm_chat_prefill': '',
            'llm_last_status': '', 'user_account': 'qa', 'research_id': 'retry-ui',
            'ui_language': 'en', 'llm_active_company_key': '600233|2026|三季度报告',
            'translation_attempts': 0}}
for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value
def build(question):
    return [], 'Summary context loaded.', 'YTO Express (600233)'
def reply(question, prepared_messages=None):
    st.session_state.translation_attempts += 1
    if st.session_state.translation_attempts == 1:
        raise ChatTranslationError('Temporary translation failure',
                                   source_text='公司主营快递服务。', cache_key='draft')
    yield 'replace', 'YTO Express principally provides express delivery services.'
render_chat_drawer(st.session_state, model='fake-model', is_english=True,
                   summary={{'company_name':'圆通速递','stock_code':'600233','report_year':2026,'report_type':'三季度报告'}},
                   display_label=lambda *_:'YTO Express (600233)', build_messages=build, stream_reply=reply)
'''
    at = AppTest.from_string(source, default_timeout=30).run()
    assert not at.exception
    at.chat_input[0].set_value('主营是什么').run()
    assert not at.exception
    assert len(at.session_state['llm_chat_messages']) == 2
    assert at.session_state['llm_chat_messages'][-1]['retry_translation']
    retry = at.button(key='llm_retry_translation_1')
    assert retry.label == 'Retry translation'
    retry.click().run()
    assert not at.exception
    history = at.session_state['llm_chat_messages']
    assert len(history) == 2
    assert history[0]['content'] == '主营是什么'
    assert history[1]['content'] == 'YTO Express principally provides express delivery services.'
    assert not history[1].get('error')
    assert at.session_state['translation_attempts'] == 2
    assert not any(button.label == 'Retry translation' for button in at.button)
