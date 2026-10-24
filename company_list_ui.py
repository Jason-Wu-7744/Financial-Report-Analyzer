"""Accessible company list: no canvas and no model calls to browse issuers."""
from html import escape
from pathlib import Path
import json
from functools import lru_cache
import math
import hashlib
import streamlit as native_st

from i18n import english, static_text
from ui_i18n import st, company_display_name


# Established issuer names; unlisted names use a clearly labelled romanization.
ISSUER_ENGLISH = {
    '600519': 'Kweichow Moutai', '300750': 'CATL', '000333': 'Midea Group',
    '00700.HK': 'Tencent Holdings', '00005.HK': 'HSBC Holdings', '01810.HK': 'Xiaomi Corporation',
    '000063': 'ZTE', '000001': 'Ping An Bank', '600036': 'China Merchants Bank',
    '601318': 'Ping An Insurance', '601398': 'ICBC', '600000': 'Shanghai Pudong Development Bank',
    '002594': 'BYD', '01211.HK': 'BYD', '09988.HK': 'Alibaba Group', '03690.HK': 'Meituan',
}


@lru_cache(maxsize=1)
def issuer_english_cache():
    path = Path(__file__).parent / 'assets' / 'issuer-english-names.json'
    if path.is_file():
        return json.loads(path.read_text(encoding='utf-8'))
    return {}


def bilingual_company_name(name, code):
    import re
    if not isinstance(name, str) or not re.search(r'[\u3400-\u9fff]', name):
        return name
    english_name = ISSUER_ENGLISH.get(str(code)) or issuer_english_cache().get(str(code))
    if not english_name:
        english_name = company_display_name(name) + '; romanized'
    return f'{name} ({english_name})'


def display_frame(frame, is_english):
    shown = frame.copy()
    if is_english:
        shown['证券名称'] = [bilingual_company_name(name, code) for name, code in zip(shown['证券名称'], shown['证券代码'])]
        shown['报告类型'] = shown['报告类型'].map(static_text)
        shown = shown.rename(columns={column: static_text(str(column)) for column in shown.columns})
    return shown


def company_table_html(frame):
    header = ''.join('<th scope="col">'+escape(str(c))+'</th>' for c in frame.columns)
    rows = []
    for row in frame.itertuples(index=False, name=None):
        cells = ['✓' if v is True else '—' if v is False else str(v) for v in row]
        rows.append('<tr>'+''.join('<td>'+escape(v)+'</td>' for v in cells)+'</tr>')
    return ('<div style="overflow-x:auto"><table class="company-list-table" style="width:100%;font-size:13px;white-space:nowrap">'
            '<thead><tr>'+header+'</tr></thead><tbody>'+''.join(rows)+'</tbody></table></div>')


def render_company_list(frame, research_id):
    """Use a bounded native checkbox editor and map edits back by original index."""
    edited = frame.copy()
    is_english = english()
    shown = display_frame(edited, is_english)
    query = st.text_input('筛选表格（名称或代码）', key=f'company_filter_{research_id}').strip().casefold()
    code_column = 'Ticker' if is_english else '证券代码'
    name_column = 'Company' if is_english else '证券名称'
    selection_column = 'Research' if is_english else '研究'
    if query:
        mask = [query in str(code).casefold() or query in str(name).casefold()
                for code, name in zip(shown[code_column], shown[name_column])]
        filtered = shown.loc[mask]
    else:
        filtered = shown
    count = len(filtered)
    pages = max(1, math.ceil(count / 50))
    page = st.selectbox('页码', list(range(1, pages+1)), key=f'company_page_{research_id}_{query}')
    visible = filtered.iloc[(page-1)*50:page*50].copy()
    if count:
        # A fresh key when the saved selection changes avoids stale editor diffs
        # after Select all/Clear selection and when reopening a research project.
        identity = repr((research_id,is_english,query,page,visible.to_dict('split')))
        key = 'company_checkbox_' + hashlib.sha256(identity.encode()).hexdigest()[:20]
        changed = native_st.data_editor(
            visible, key=key, hide_index=True, num_rows='fixed',
            width='stretch', height=min(530, 38+35*len(visible)),
            disabled=[column for column in visible.columns if column != selection_column],
            column_config={
                selection_column: native_st.column_config.CheckboxColumn('Select' if is_english else '勾选',width='small',required=True),
                code_column: native_st.column_config.TextColumn(code_column,width='small'),
                name_column: native_st.column_config.TextColumn(name_column,width='large'),
            },
        )
        edited.loc[changed.index,'研究'] = changed[selection_column].astype(bool).to_numpy()
    else:
        st.info('没有匹配的公司，请修改名称或代码。')
    st.caption(f'Page {page} / {pages} · {count} rows' if is_english else f'第 {page} / {pages} 页 · 共 {count} 行')
    st.download_button('下载公司名单 CSV', display_frame(edited,is_english).to_csv(index=False).encode('utf-8-sig'),
                       file_name='company_list.csv', mime='text/csv', key=f'company_csv_{research_id}')
    return edited
