"""Chat repair must use the API without changing the generated reply's facts."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import chat_translation as repair
import i18n


class Client:
    def __init__(self, respond):
        self.requests = []
        self.respond = respond
        self.chat = NS(completions=NS(create=self.create))

    def create(self, **request):
        self.requests.append(request)
        value = self.respond(json.loads(request['messages'][-1]['content']), len(self.requests))
        if isinstance(value, Exception):
            raise value
        return NS(choices=[NS(message=NS(content=json.dumps(value, ensure_ascii=False)))],
                  usage=NS(prompt_tokens=12, completion_tokens=8))


def run(text, client=None, **kwargs):
    return repair.ensure_english_chat_reply(text, api_key='fake-key', model='fake',
                                           base_url='https://api.deepseek.com', client=client, **kwargs)


def test_already_english_and_known_issuer_are_not_sent_to_a_provider():
    client = Client(lambda *_: AssertionError('API not expected'))
    assert run('Revenue grew 7.8%.', client) == 'Revenue grew 7.8%.'
    original = '圆通速递 (600233): revenue grew 7.8% and profit grew 60.9%.'
    assert run(original, client, issuer_aliases={'圆通速递': 'YTO Express'}) == 'YTO Express (600233): revenue grew 7.8% and profit grew 60.9%.'
    assert client.requests == []


def test_static_label_in_an_english_answer_uses_the_catalog_without_api():
    client = Client(lambda *_: AssertionError('API not expected'))
    original = 'The field `营收同比_%` is 7.8%.'
    translated = run(original, client)
    assert 'Revenue YoY (%)' in translated and '7.8%' in translated
    assert client.requests == []


def test_cached_issuer_label_is_scoped_to_the_supplied_historical_alias():
    source = '合力泰: revenue grew 12.3%.'
    cache = {}
    client = Client(lambda *_: AssertionError('API not expected'))
    assert run(source, client, cache=cache, issuer_aliases={'合力泰': 'Helitai'}).startswith('Helitai:')
    assert run(source, client, cache=cache, issuer_aliases={'合力泰': 'ST Helitai'}).startswith('ST Helitai:')
    assert len(cache['translations']) == 2 and client.requests == []


def test_chat_api_prompt_explicitly_declares_json_and_disables_thinking():
    client = Client(lambda payload, _: {'text': 'Its principal business is e-paper display modules.'})
    cache = {}
    answer = run('主要业务是电子纸显示模组。', client, cache=cache)
    assert answer == 'Its principal business is e-paper display modules.'
    request = client.requests[0]
    assert 'json' in request['messages'][0]['content'].lower()
    assert request['response_format'] == {'type': 'json_object'}
    assert request['extra_body'] == {'thinking': {'type': 'disabled'}}
    assert cache['last_request_count'] == 1
    assert cache['input_tokens'] == 12 and cache['output_tokens'] == 8


def translate_revenue_masked(payload):
    return payload['content'].replace('收入为', 'Revenue was ').replace('增长', 'increased ').replace('，', '; ').replace('。', '.')


def test_missing_fact_markers_are_retried_without_rescaling_or_reordering():
    source = '收入为100亿元，同比增长7.8%。'
    client = Client(lambda payload, n: {'text': 'Revenue was 99 billion.'} if n == 1 else {'text': translate_revenue_masked(payload)})
    answer = run(source, client)
    assert len(client.requests) == 2
    assert not i18n.translation_validation_errors(source, answer)
    assert '100' in answer and 'hundred million' in answer and '7.8%' in answer
    assert i18n.numeric_tokens(source) == i18n.numeric_tokens(answer)


def test_prose_fallback_keeps_all_facts_outside_provider_output():
    source = '收入为100亿元，同比增长7.8%。'
    def response(payload, count):
        if count <= 2:
            return {}
        assert 'prose_fragments' in payload
        values = {}
        for key, text in payload['prose_fragments'].items():
            # No original figure or protected marker enters a requested span.
            assert not repair._MARKER.search(text)
            assert not i18n.numeric_tokens(text)
            values[key] = text.replace('收入为', 'Revenue was ').replace('增长', 'increased ').replace('，', '; ').replace('。', '.')
        return values
    client = Client(response)
    answer = run(source, client)
    assert len(client.requests) == 3
    assert not i18n.translation_validation_errors(source, answer)
    assert '100' in answer and '7.8%' in answer
    assert all('json' in request['messages'][0]['content'].lower() for request in client.requests)


def test_api_failure_retains_original_draft_and_successful_retry_is_cached():
    source = '主要业务是电子纸显示模组。'
    cache = {}
    down = Client(lambda *_: ConnectionError('Provider unavailable'))
    with pytest.raises(repair.ChatTranslationError) as caught:
        run(source, down, cache=cache)
    error = caught.value
    assert error.retryable and error.source_text == source
    assert cache['drafts'][error.cache_key] == source
    assert error.cache_key not in cache['translations']
    assert len(down.requests) == 1
    working = Client(lambda *_: {'text': 'Its principal business is e-paper display modules.'})
    expected = run(source, working, cache=cache)
    assert run(source, down, cache=cache) == expected
    assert len(working.requests) == 1 and len(down.requests) == 1


def test_an_error_placeholder_cannot_be_reused_as_a_translation():
    source = '主要业务是电子纸显示模组。'
    cache = {}
    client = Client(lambda *_: {'text': 'Its principal business is e-paper display modules.'})
    result = run(source, client, cache=cache)
    key = next(iter(cache['translations']))
    cache['translations'][key] = i18n.TRANSLATION_UNAVAILABLE
    assert run(source, client, cache=cache) == result
    assert len(client.requests) == 2


def test_invalid_provider_content_never_replaces_the_retained_draft():
    source = '主要业务是电子纸显示模组。'
    cache = {}
    client = Client(lambda *_: {'text': '这仍然是中文。'})
    with pytest.raises(repair.ChatTranslationError) as caught:
        run(source, client, cache=cache)
    assert cache['drafts'][caught.value.cache_key] == source
    assert not cache['translations']
    assert len(client.requests) <= repair.MAX_REQUESTS


def test_request_budget_is_bounded_and_no_api_key_is_saved():
    source = '\n\n'.join('这是一段需要翻译的说明' + str(n) + '。' for n in range(80))
    cache = {}
    client = Client(lambda *_: {})
    with pytest.raises(repair.ChatTranslationError):
        run(source, client, cache=cache)
    assert len(client.requests) <= repair.MAX_REQUESTS
    assert 'fake-key' not in json.dumps(cache, ensure_ascii=False)


def test_draft_cache_is_bounded_when_provider_is_unconfigured():
    cache = {}
    for index in range(repair.MAX_CACHE_ITEMS + 3):
        with pytest.raises(repair.ChatTranslationError):
            repair.ensure_english_chat_reply('待翻译的正文' + str(index), api_key='', model='fake',
                                            base_url='https://invalid.example', cache=cache)
    assert len(cache['drafts']) == repair.MAX_CACHE_ITEMS


def test_issuer_alias_cannot_introduce_new_numeric_facts():
    client = Client(lambda *_: {'text': 'San Liu Ling provides security software.'})
    answer = run('三六零提供安全软件。', client, issuer_aliases={'三六零': '360 Security'})
    assert '360' not in answer and i18n.numeric_tokens(answer) == i18n.numeric_tokens('三六零提供安全软件。')
    assert len(client.requests) == 1
