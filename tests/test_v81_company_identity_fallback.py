"""Issuer identity must remain usable when the translation provider is offline."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import i18n
import ui_i18n


@pytest.fixture(autouse=True)
def reset_language():
    i18n.configure('zh')
    yield
    i18n.configure('zh')


class OfflineTranslator:
    def __init__(self):
        self.cache = {}
        self.calls = 0

    def text(self, value):
        self.calls += 1
        raise ConnectionError('Provider is offline')


@pytest.mark.parametrize(('name', 'code', 'expected'), [
    ('皇庭国际', '000056', 'Huang Ting Guo Ji (000056)'),
    ('深圳机场', '000089', 'Shenzhen Airport (000089)'),
    ('泰山石油', '000554', 'Taishan Petroleum (000554)'),
    ('腾讯控股', '00700.HK', 'TENCENT (00700.HK)'),
])
def test_real_company_headers_are_offline_and_preserve_ticker(name, code, expected):
    translator = OfflineTranslator()
    translator.cache[f'{name}（{code}）'] = i18n.TRANSLATION_UNAVAILABLE
    i18n.configure('en', translator)
    assert ui_i18n.company_display_label(name, code) == expected
    assert ui_i18n.text(f'<h3>{name}（{code}）</h3>') == f'<h3>{expected}</h3>'
    assert ui_i18n.text(f'<h3 aria-label="{name}（{code}）">{name}（{code}）</h3>') == f'<h3 aria-label="{expected}">{expected}</h3>'
    assert ui_i18n.text(f'**{name}（{code}）**') == f'**{expected}**'
    assert translator.calls == 0


def test_historical_canonical_name_does_not_gain_current_st_designation(monkeypatch):
    monkeypatch.setattr(ui_i18n, '_issuer_names', lambda: {'000056': '*ST Huangting'})
    i18n.configure('en')
    assert ui_i18n.company_display_name('皇庭国际', '000056') == 'Huang Ting Guo Ji'
    assert ui_i18n.company_display_name('*ST皇庭', '000056') == '*ST Huangting'


def test_unknown_issuer_uses_romanization_and_keeps_original_identifier():
    i18n.configure('en')
    label = ui_i18n.company_display_label('新示例公司', '123456.SZ')
    assert label == 'Xin Shi Li Gong Si (123456.SZ)'
    assert not i18n.HAN.search(label)
    assert ui_i18n.company_display_label('', '123456.SZ') == '123456.SZ'


def test_issuer_lookup_normalizes_mainland_suffix_but_display_keeps_it():
    i18n.configure('en')
    assert ui_i18n.company_display_label('深圳机场', '000089.SZ') == 'Shenzhen Airport (000089.SZ)'


def test_chinese_company_identity_and_browsing_romanization_are_unchanged():
    i18n.configure('zh')
    assert ui_i18n.company_display_label('皇庭国际', '000056') == '皇庭国际（000056）'
    assert ui_i18n.text('<h3>皇庭国际（000056）</h3>') == '<h3>皇庭国际（000056）</h3>'
    assert ui_i18n.company_display_name('贵州茅台') == 'Gui Zhou Mao Tai'


def test_failure_placeholder_cache_is_evicted_and_valid_translation_retried():
    class Translator(OfflineTranslator):
        def text(self, value):
            self.calls += 1
            self.cache[value] = 'The issuer'
            return 'The issuer'
    translator = Translator()
    translator.cache['公司主体'] = i18n.TRANSLATION_UNAVAILABLE
    i18n.configure('en', translator)
    assert i18n.translate('公司主体') == 'The issuer'
    assert translator.cache['公司主体'] == 'The issuer'
    assert translator.calls == 1


def test_failure_placeholder_return_is_not_a_success_or_cache_entry():
    class Translator(OfflineTranslator):
        def text(self, value):
            self.cache[value] = i18n.TRANSLATION_UNAVAILABLE
            return i18n.TRANSLATION_UNAVAILABLE
    translator = Translator()
    i18n.configure('en', translator)
    with pytest.raises(i18n.TranslationError):
        i18n.translate('公司主体')
    assert '公司主体' not in translator.cache
    assert 'translation failure placeholder' in i18n.translation_validation_errors('公司主体', i18n.TRANSLATION_UNAVAILABLE)


def test_english_translator_cannot_reuse_or_remember_error_placeholder():
    translator = i18n.EnglishTranslator('', 'fake', 'https://invalid.example')
    translator.cache['公司主体'] = i18n.TRANSLATION_UNAVAILABLE
    with pytest.raises(i18n.TranslationError):
        translator.text('公司主体')
    assert '公司主体' not in translator.cache
    with pytest.raises(i18n.TranslationError):
        translator._remember('公司主体', i18n.TRANSLATION_UNAVAILABLE)
    assert '公司主体' not in translator.cache
    translator.cache['公司主体'] = i18n.TRANSLATION_UNAVAILABLE
    with pytest.raises(i18n.TranslationError):
        translator.prefetch(['公司主体'])
    assert '公司主体' not in translator.cache
