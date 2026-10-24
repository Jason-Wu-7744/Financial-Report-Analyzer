"""Explicit Streamlit presentation adapter; never changes domain values globally."""
from functools import lru_cache, wraps
import json
from pathlib import Path
import re
import streamlit as native
from i18n import english, translate


@lru_cache(maxsize=1)
def _issuer_names():
    path = Path(__file__).parent / 'assets' / 'issuer-english-names.json'
    try:
        names = json.loads(path.read_text(encoding='utf-8'))
        return names if isinstance(names, dict) else {}
    except (OSError, ValueError):
        return {}


def company_display_name(value, stock_code=''):
    """Render issuer names offline so large disclosure lists never wait on an LLM.

    Canonical names are retained in the returned editor data. Romanization is
    deliberately not presented as an issuer's registered English legal name.
    """
    if not isinstance(value, str) or not re.search(r'[\u3400-\u9fff]', value):
        return value
    code = str(stock_code or '').strip().upper()
    lookup_code = re.sub(r'\.(SH|SZ|BJ)$', '', code)
    known = _issuer_names().get(lookup_code) if lookup_code else None
    if isinstance(known, str) and known.strip() and not re.search(r'[\u3400-\u9fff]', known):
        # A current name cache can carry an ST designation acquired after the
        # historical filing. Never introduce that designation into its title.
        current_status = re.match(r'^\*?ST\b|^\*?ST(?=[A-Z])', known, re.I)
        source_status = re.match(r'^\s*\*?ST', value, re.I)
        if not current_status or source_status:
            return known.strip()
    from pypinyin import lazy_pinyin
    return ' '.join(part.capitalize() for part in lazy_pinyin(value))


def company_display_label(value, stock_code=''):
    """Stable issuer identity for cards, reports and chat; never calls an API."""
    name, code = str(value or '').strip(), str(stock_code or '').strip()
    shown = company_display_name(name, code) if english() else name
    if not shown:
        return code or ('Unnamed company' if english() else '未命名公司')
    if not code:
        return shown
    return f'{shown} ({code})' if english() else f'{shown}（{code}）'


def _company_node_label(value):
    # Older saved card templates pass a complete name/ticker node through this
    # adapter. Recognize only that bounded shape, never prose mentioning a firm.
    match = re.fullmatch(r'(\s*)(\*\*)?([^\n<>（）()]{1,50})[（(](\d{5,6}(?:\.(?:HK|SH|SZ|BJ))?)[）)](\*\*)?(\s*)', value, re.I)
    if not match or bool(match[2]) != bool(match[5]):
        return None
    return match[1] + (match[2] or '') + company_display_label(match[3], match[4]) + (match[5] or '') + match[6]

_TEXT_METHODS = {'markdown','caption','title','header','subheader','text','write','info','warning','error','success','exception','button','form_submit_button','download_button','text_input','text_area','number_input','slider','checkbox','toggle','radio','selectbox','multiselect','file_uploader','date_input','time_input','expander','popover','dialog','spinner','chat_input','link_button','metric','status'}
_CONTAINERS = {'container','empty','expander','popover','form','chat_message','status'}


def text(value):
    if not isinstance(value, str): return value
    if '<style' in value or '<script' in value: return value
    if english():
        issuer_label = _company_node_label(value)
        if issuer_label is not None:
            return issuer_label
    if re.search(r'<[a-zA-Z][^>]*>', value):
        # Translate visible nodes and accessibility labels, preserving all markup.
        pieces = re.split(r'(<[^>]+>)',value)
        for i,piece in enumerate(pieces):
            if piece.startswith('<'):
                pieces[i] = re.sub(r'(aria-label|title)=("[^"]*"|\x27[^\x27]*\x27)',lambda m: m[1]+'='+m[2][0]+text(m[2][1:-1])+m[2][-1],piece)
            else: pieces[i] = text(piece)
        return ''.join(pieces)
    return translate(value,strict=False)


class StreamlitUI:
    def __init__(self, target=native): self._target=target
    def __enter__(self):
        self._target.__enter__(); return self
    def __exit__(self,*args): return self._target.__exit__(*args)
    def __getattr__(self,name):
        target=getattr(self._target,name)
        if name in ('sidebar','column_config'): return StreamlitUI(target)
        if not callable(target): return target
        @wraps(target)
        def call(*args,**kwargs):
            args=list(args)
            if english():
                if name in _TEXT_METHODS or name.endswith('Column'):
                    if args: args[0]=text(args[0])
                    for key in ('label','body','help','placeholder','text','title'):
                        if key in kwargs: kwargs[key]=text(kwargs[key])
                if name=='progress':
                    if 'text' in kwargs: kwargs['text']=text(kwargs['text'])
                if name=='set_page_config':
                    if 'page_title' in kwargs: kwargs['page_title']=text(kwargs['page_title'])
                    kwargs['page_icon']='R'
                if name in ('radio','selectbox','multiselect'):
                    original=kwargs.get('format_func',str)
                    options=args[1] if len(args)>1 else kwargs.get('options',[])
                    labels={repr(option):text(original(option)) for option in options}
                    kwargs['format_func']=lambda option: labels.get(repr(option), original(option))
                if name=='tabs' and args: args[0]=[text(x) for x in args[0]]
                if name in ('dataframe','table','data_editor') and args:
                    frame=args[0]
                    if hasattr(frame,'columns'):
                        original_frame=frame.copy()
                        display=frame.copy()
                        # Keep internal column identifiers stable; labels are presentation only.
                        config=dict(kwargs.get('column_config') or {})
                        for column in display.columns:
                            if column not in config: config[column]=text(str(column))
                            from pandas.api.types import is_string_dtype, is_object_dtype
                            if is_string_dtype(display[column].dtype) or is_object_dtype(display[column].dtype):
                                if column in ('证券名称', '公司名称', 'company_name') and any(c in display.columns for c in ('证券代码', 'stock_code')):
                                    display[column]=display[column].map(company_display_name)
                                else:
                                    display[column]=display[column].map(lambda v:text(v) if isinstance(v,str) else v)
                        # Streamlit's built-in CSV download uses actual column IDs,
                        # not column_config labels. Localize those IDs for export,
                        # then map editable selections back to canonical columns.
                        names={column:text(str(column)) for column in display.columns}
                        if len(set(names.values())) == len(names):
                            display=display.rename(columns=names)
                            config={names.get(column,column):value for column,value in config.items()}
                        else:
                            names={column:column for column in display.columns}
                        kwargs['column_config']=config
                        args[0]=display
                        result=target(*args,**kwargs)
                        if name=='data_editor':
                            # v8 research list only allows editing the selection column.
                            for column in original_frame.columns:
                                if original_frame[column].dtype=='bool': original_frame[column]=result[names[column]]
                            return original_frame
                        return result
            result=target(*args,**kwargs)
            if name in _CONTAINERS or name=='progress': return StreamlitUI(result)
            if name in ('columns','tabs'): return [StreamlitUI(x) for x in result]
            return result
        return call

st=StreamlitUI()
