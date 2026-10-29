"""A single keyed chat drawer, independent of report columns and refreshes."""
from __future__ import annotations

from datetime import datetime
from html import escape

import streamlit as st

from chat_state import close_chat, save_chat, chat_scope
from i18n import static_text


def render_chat_drawer(state, *, model, is_english, summary, display_label, build_messages, stream_reply):
    name, code = str(summary.get('company_name') or ''), str(summary.get('stock_code') or '')
    company = display_label(name, code) if name or code else ('No company selected' if is_english else '未选择公司')
    kind = str(summary.get('report_type') or '')
    period = ' '.join(filter(None, [str(summary.get('report_year') or ''), static_text(kind) if is_english else kind]))
    messages = list(state.get('llm_chat_messages') or [])
    pending = str(state.get('llm_pending_prompt') or '').strip()
    retry_index = state.get('llm_translation_retry_index')
    retrying = isinstance(retry_index, int) and 0 <= retry_index < len(messages) and bool(pending)
    response_area = None
    with st.container(key='llm_chat_drawer', border=False):
        with st.container(key='llm_chat_header', border=False):
            title, controls = st.columns([1, .15], gap='small')
            with title:
                st.markdown(
                    '<div class="llm-header" translate="no"><div>'
                    f'<div class="llm-title">{"Research Assistant" if is_english else "研究助手"}</div>'
                    f'<div class="llm-subtitle">{escape(company)}'
                    f'{" · " + escape(period) if period else ""}</div></div></div>', unsafe_allow_html=True)
            with controls:
                if st.button('', icon=':material/close:', key='llm_chat_close',
                             help='Close chat' if is_english else '收起对话'):
                    close_chat(state)
                    st.rerun()
            if st.button('New conversation' if is_english else '新对话', key='llm_chat_new',
                         disabled=bool(pending), icon=':material/edit_square:'):
                save_chat(state, [])
                scope = chat_scope(state, state.get('llm_active_company_key') or '')
                drafts = state.get('llm_chat_answer_drafts') or {}
                state['llm_chat_answer_drafts'] = {key: value for key, value in drafts.items()
                                                  if isinstance(value, dict) and value.get('scope') != scope}
                state['llm_last_status'] = ''
                st.rerun()
        with st.container(key='llm_chat_transcript', border=False):
            if not messages and not pending:
                st.markdown(
                    '<div class="llm-empty">'
                    f'<div class="llm-empty-title">{"What would you like to explore?" if is_english else "想进一步了解什么？"}</div>'
                    f'<div class="llm-empty-sub">{("The selected company’s summary and available filing evidence are loaded automatically for each question. You can ask follow-up questions here." if summary else "Select a company card to load its filing context, or ask a general question.") if is_english else ("已选公司的摘要及可用财报证据会自动载入每一轮提问，可直接连续追问。" if summary else "点击公司卡片的箭头载入财报上下文，也可以直接提问。")}</div>'
                    '</div>', unsafe_allow_html=True)
            for position, item in enumerate(messages):
                if retrying and position == retry_index:
                    continue
                role = 'user' if item.get('role') == 'user' else 'assistant'
                with st.chat_message(role):
                    content = str(item.get('content') or item.get('question' if role == 'user' else 'answer') or '')
                    if item.get('error'):
                        st.error(content)
                        if item.get('retry_translation'):
                            if st.button('Retry translation' if is_english else '重试翻译',
                                         key=f'llm_retry_translation_{position}', disabled=bool(pending), icon=':material/refresh:'):
                                state['llm_translation_retry_index'] = position
                                state['llm_pending_prompt'] = str(item.get('question') or '')
                                st.rerun()
                    else:
                        # User text and checked English replies must never be
                        # translated again while merely repainting the drawer.
                        st.markdown(content)
            if pending:
                if not retrying:
                    with st.chat_message('user'):
                        st.markdown(pending)
                with st.chat_message('assistant'):
                    response_area = st.empty()
                    response_area.caption('Reading the company context…' if is_english else '正在读取公司材料…')
        with st.container(key='llm_chat_status', border=False):
            st.caption(('Generating a reply…' if is_english else '正在生成回答…') if pending else
                       (str(state.get('llm_last_status') or '') or ('Ready for your question' if is_english else '可以开始提问')))
        with st.container(key='llm_chat_composer', border=False):
            st.markdown(f'<div class="llm-context-pill" translate="no">{escape(company)}</div>', unsafe_allow_html=True)
            prefill = str(state.pop('llm_chat_prefill', '') or '')
            placeholder = prefill + ('Ask about this filing…' if is_english else '围绕这份财报提问…')
            prompt = st.chat_input(placeholder, key='llm_chat_input', disabled=bool(pending))
            st.caption('Enter to send · Shift+Enter for a new line' if is_english else 'Enter 发送 · Shift+Enter 换行')
        if prompt and str(prompt).strip() and not pending:
            state['llm_pending_prompt'] = str(prompt).strip()
            st.rerun()
        if pending and response_area is not None:
            source_note, company_display = '', company
            try:
                prepared, source_note, company_display = build_messages(pending)
                answer_parts = []
                for event, piece in stream_reply(pending, prepared_messages=prepared):
                    if event == 'thinking':
                        if not answer_parts:
                            response_area.caption('Reviewing the filing evidence…' if is_english else '正在分析财报证据…')
                        continue
                    if event == 'translation':
                        response_area.caption('Translating the answer into English…' if is_english else '正在翻译回答…')
                        continue
                    if event == 'replace':
                        answer_parts = [piece]
                    else:
                        answer_parts.append(piece)
                    response_area.markdown(''.join(answer_parts) + '▌')
                answer = ''.join(answer_parts).strip()
                if not answer:
                    raise RuntimeError('Empty model response')
                pair = [{'role': 'user', 'content': pending, 'time': datetime.now().strftime('%H:%M')},
                        {'role': 'assistant', 'content': answer, 'company': company_display,
                         'source_note': source_note, 'time': datetime.now().strftime('%H:%M')}]
                if retrying:
                    state['llm_chat_messages'][retry_index] = pair[1]
                else:
                    state['llm_chat_messages'].extend(pair)
                state['llm_last_status'] = source_note or ('Reply complete' if is_english else '回答已完成')
            except Exception as error:
                translation_retry = bool(getattr(error, 'retryable', False) and getattr(error, 'source_text', None))
                detail = (('The answer was generated, but English translation needs another attempt. Use Retry translation below.' if is_english else '回答已生成，英文翻译尚未完成，可点击下方按钮单独重试翻译。')
                          if translation_retry else
                          (f'Reply failed ({type(error).__name__}). Your question was kept; send it again to retry.' if is_english else f'本轮回答失败（{type(error).__name__}）。问题已保留，可再次发送重试。'))
                failed = {'role': 'assistant', 'content': detail, 'error': True, 'company': company_display,
                          'retry_translation': translation_retry, 'question': pending}
                if retrying:
                    state['llm_chat_messages'][retry_index] = failed
                else:
                    state['llm_chat_messages'].extend([{'role': 'user', 'content': pending}, failed])
                state['llm_last_status'] = 'Reply failed; you can retry.' if is_english else '本轮回答未完成，可重试。'
            finally:
                state['llm_pending_prompt'] = ''
                state.pop('llm_translation_retry_index', None)
                save_chat(state)
            st.rerun()
