from __future__ import annotations

import inspect
import json
import os
import re
import shutil
import tempfile
import time
from collections import defaultdict
from dataclasses import asdict
from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path

import pandas as pd
import streamlit as native_st
from ui_i18n import st, company_display_name, company_display_label
from company_list_ui import render_company_list
from card_presentation import summary_status_badge_html, preliminary_risk_html
from i18n import configure, english, translate, EnglishTranslator, localized_generation, localize_artifact, TranslationError
from openai import OpenAI
try:
    import httpx2 as httpx_runtime
except ImportError:
    import httpx as httpx_runtime
from engine import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    CompanyRow,
    collect_pdfs,
    comment_one_company,
    extract_pdf_pages,
    match_pdf,
    read_company_rows,
    safely_extract_zip,
    select_evidence_pages,
    summarize_one_fast,
    test_deepseek_connection,
)
from cninfo import (
    CninfoAnnouncement,
    download_announcements,
    download_reports_for_rows,
    list_reports_by_date,
    load_cninfo_metadata,
    normalise_company_rows,
    parse_company_identifiers,
    search_reports_for_company,
)
from dotenv import load_dotenv

import auth
import research_store
import screening_engine
from screening_engine import screen_full
from styles import css_for_theme, login_css
from background_jobs import active_job, job_path, launch_job, read_job


ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
CLOUD_SHARE = os.getenv("CLOUD_SHARE", "1").strip() not in {"0", "false", "False", ""}
REPORT_TYPES = ["一季度报告", "半年度报告", "三季度报告", "年度报告"]
WORKLIST_COLUMNS = ["研究", "证券代码", "证券名称", "报告类型", "报告期年份", "披露日期"]
A_SHARE = "A股"
HK_SHARE = "港股"
A_AUTO_SOURCE = "巨潮资讯自动下载"
HK_AUTO_SOURCE = "港交所披露易自动下载"
AUTO_SOURCES = {A_AUTO_SOURCE, HK_AUTO_SOURCE}


def _stretch() -> dict:
    try:
        if "width" in inspect.signature(st.button).parameters:
            return {"width": "stretch"}
    except (TypeError, ValueError):
        pass
    return {"use_container_width": True}


STRETCH = _stretch()

# Configure language before rendering the cover or login form. The URL can be
# shared with an admissions reviewer as ?lang=en; session state owns the choice.
if "ui_language" not in st.session_state:
    st.session_state.ui_language = "en" if native_st.query_params.get("lang") == "en" else "zh"
configure(st.session_state.ui_language)


st.set_page_config(
    page_title="财报经营分析助手 · V8.1",
    page_icon="研",
    layout="wide",
    initial_sidebar_state="collapsed",
)

defaults = {
    "user_name": None,
    "user_account": None,
    "view": "history",
    "research_id": None,
    "worklist": [],
    "worklist_announcements": {},
    "summaries": [],
    "comments": [],
    "screenings": [],
    "market_mode": A_SHARE,
    "source_mode": A_AUTO_SOURCE,
    "market_messages": [],
    "api_key_override_input": "",
    "ds_model": "deepseek-v4-flash",
    "ds_base_url": os.getenv("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL),
    "ds_max_pages": 28,
    "ds_max_chars": 70000,
    "ds_test_mode": False,
    "ds_test_limit": 0,
    "pending_quick": False,
    "pending_deep": False,
    "llm_drawer_open": False,
    "llm_chat_messages": [],
    "llm_active_company_key": "",
    "llm_chat_prefill": "",
    "llm_pending_prompt": "",
    "llm_ignore_prompt_once": "",
    "llm_clear_input": False,
    "ui_theme": "Dark",
    "ui_language": st.session_state.ui_language,
}
for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value

if st.session_state.get("pending_logout"):
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    for key, value in defaults.items():
        st.session_state[key] = value


def select_language():
    native_st.selectbox(
        "Language / 语言" if not english() else "Language",
        ["zh", "en"],
        format_func=lambda value, is_en=english(): ("Chinese" if is_en else "中文") if value == "zh" else "English",
        key="ui_language", on_change=change_language,
    )


def change_language():
    native_st.query_params["lang"] = st.session_state.ui_language
    # The next rerun reloads the matching language's saved results.
    configure(st.session_state.ui_language, st.session_state.get("_translator"))
    research_id = st.session_state.get("research_id")
    account = st.session_state.get("user_account")
    if research_id and account:
        st.session_state.summaries = research_store.load_summaries(ROOT, account, research_id)
        st.session_state.comments = research_store.load_comments(ROOT, account, research_id)
        st.session_state.screenings = research_store.load_screenings(ROOT, account, research_id)
    st.session_state.pending_quick = False
    st.session_state.pending_deep = False
    st.session_state.llm_chat_messages = []
    st.session_state.llm_pending_prompt = ""
    for key in ("worklist_editor", "summary_editor"):
        st.session_state.pop(key, None)


def configure_translation():
    key = (st.session_state.get("api_key_override_input") or "").strip() or os.getenv("DEEPSEEK_API_KEY", "").strip() or os.getenv("OPENAI_API_KEY", "").strip()
    model_name = st.session_state.get("ds_model") or DEFAULT_MODEL
    endpoint = st.session_state.get("ds_base_url") or DEFAULT_BASE_URL
    identity = (key, model_name, endpoint)
    if st.session_state.get("_translation_identity") != identity or not isinstance(st.session_state.get("_translator"), EnglishTranslator):
        st.session_state._translator = EnglishTranslator(*identity)
        st.session_state._translation_identity = identity
    configure(st.session_state.ui_language, st.session_state.get("_translator"))


configure_translation()
# Wrap only public generation boundaries; extraction, source quotations and
# financial/risk validation continue to use the established canonical schema.
summarize_one_fast = localized_generation(summarize_one_fast)
comment_one_company = localized_generation(comment_one_company)
screen_full = localized_generation(screen_full)


def logged_in() -> bool:
    return bool(st.session_state.user_name)


def current_account() -> str:
    return str(st.session_state.user_account or "")


def render_sample() -> None:
    """Show explicitly dated, pre-generated research without a model call."""
    sample_root = (ROOT / "samples").resolve()
    manifest = json.loads((sample_root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "ready":
        return
    language = "en" if english() else "zh"
    entries = [item for item in manifest.get("samples", []) if item.get("language") == language]
    if not entries:
        return
    st.caption("Pre-generated research based on official filings. Review the dated evidence and scope below."
               if english() else "根据官方财报预生成的研究示例；请留意披露时间与证据范围。")
    index = st.selectbox("Research example" if english() else "研究示例", range(len(entries)),
                         format_func=lambda number: f"{entries[number]['company_name']} ({entries[number]['ticker']}) · {entries[number]['report_year']}",
                         key="cover_sample_choice")
    entry = entries[index]
    report_type = str(entry.get("report_type", "—"))
    if english():
        report_type = {"一季度报告": "First Quarter Report", "半年度报告": "Interim Report",
                       "三季度报告": "Third Quarter Report", "年度报告": "Annual Report"}.get(report_type, report_type)
    path = (sample_root / str(entry.get("path", ""))).resolve()
    if path.suffix.lower() != ".md" or not path.is_relative_to(sample_root) or not path.is_file():
        st.error("The sample file is unavailable." if english() else "示例文件暂不可用。")
        return
    st.caption(("Sample prepared {generated}; automated checks {validated}. Source period: {year} {kind}."
                if english() else "样例整理于 {generated}；自动校验于 {validated}。财报期间：{year} {kind}。")
               .format(generated=entry.get("generated_at", "—"), validated=entry.get("validated_at", "—"),
                       year=entry.get("report_year", "—"), kind=report_type))
    from sample_provenance import official_filing_url
    source_url = official_filing_url(entry.get("source_url"))
    if source_url:
        label = "Official filing" if english() else "财报原文"
        native_st.markdown(f"[{label}]({source_url})")
    with st.expander("View research brief" if english() else "查看研究简报", expanded=True):
        native_st.markdown(path.read_text(encoding="utf-8"))
    native_st.download_button("Download sample MD" if english() else "下载示例 MD", path.read_bytes(),
                              file_name=path.name, mime="text/markdown", key="sample_download")


def render_login() -> None:
    st.markdown(login_css(ROOT / "static" / "cover-v81.webp"), unsafe_allow_html=True)
    with st.container():
        st.markdown('<div class="login-shell-anchor"></div>', unsafe_allow_html=True)
        brand, credentials = st.columns([1.65, 1], gap="large")
        with brand:
            st.markdown(
                '<div class="hero-mini"><div class="page-kicker">FINANCIAL RESEARCH · V8.1</div>'
                '<div class="page-title">财报经营分析助手</div>'
                '<div class="cover-rule"></div>'
                '<div class="page-subtitle">从财报披露到深入研究，让分析更有依据。</div>'
                '<div class="cover-workflow">市场筛选 · 快速分析 · 深度研究</div></div>',
                unsafe_allow_html=True,
            )
        with credentials:
            select_language()
            with st.form("login_form"):
                username = st.text_input("账号", placeholder="demo1")
                password = st.text_input("密码", type="password", placeholder="请输入发放的密码")
                submitted = st.form_submit_button("登录", type="primary", **STRETCH)
            if submitted:
                user = auth.authenticate(username, password)
                if user:
                    st.session_state.user_name = user["display_name"]
                    st.session_state.user_account = user["username"]
                    st.session_state.view = "history"
                    st.session_state.research_id = None
                    st.rerun()
                st.error("账号或密码不正确。")
            st.caption("输出仅供研究辅助，不构成投资建议。")
            sample_manifest = ROOT / "samples" / "manifest.json"
            if sample_manifest.is_file() and json.loads(sample_manifest.read_text(encoding="utf-8")).get("status") == "ready":
                if st.button("查看真实研究示例", key="cover_sample", **STRETCH):
                    st.session_state.show_sample = True
            if st.session_state.get("show_sample"):
                render_sample()
    st.stop()


if not logged_in():
    render_login()


def logout_session() -> None:
    st.session_state.pending_logout = True
    st.rerun()


def default_report_year(report_type: str) -> int:
    now = datetime.now()
    if report_type == "年度报告":
        return now.year - 1
    if report_type == "半年度报告":
        return now.year - 1 if now.month < 9 else now.year
    if report_type == "一季度报告":
        return now.year - 1 if now.month < 5 else now.year
    return now.year - 1 if now.month < 11 else now.year


def worklist_frame() -> pd.DataFrame:
    rows = st.session_state.get("worklist") or []
    if not rows:
        return pd.DataFrame(columns=WORKLIST_COLUMNS)
    return pd.DataFrame(rows)[WORKLIST_COLUMNS]


def set_worklist(rows: list[dict], announcements: dict[str, dict] | None = None) -> None:
    st.session_state.worklist = rows
    if announcements is not None:
        st.session_state.worklist_announcements = announcements
    st.session_state.pop("worklist_editor", None)
    st.session_state.pop("company_selection_v81", None)


def clear_for_market_change() -> None:
    """Keep a research project single-market when the market selector changes."""
    st.session_state.worklist = []
    st.session_state.worklist_announcements = {}
    st.session_state.summaries = []
    st.session_state.comments = []
    st.session_state.screenings = []
    st.session_state.market_messages = []
    st.session_state.source_mode = A_AUTO_SOURCE if st.session_state.market_mode == A_SHARE else HK_AUTO_SOURCE
    st.session_state.pop("worklist_editor", None)
    st.session_state.pop("company_selection_v81", None)
    st.session_state.pop("summary_editor", None)
    st.session_state.pending_quick = False
    st.session_state.pending_deep = False
    persist_screen(source=f"{st.session_state.market_mode}研究")
    persist_summaries()
    persist_screenings()
    if st.session_state.research_id:
        research_store.save_comments(ROOT, current_account(), st.session_state.research_id, [])
        research_store.update_meta(
            ROOT,
            current_account(),
            st.session_state.research_id,
            stage="screen",
            quick_count=0,
            selected_count=0,
            deep_count=0,
            screening_count=0,
        )


def worklist_key(code: str, report_type: str, year: int, extra: str = "") -> str:
    return f"{code}|{report_type}|{year}|{extra}"


def selected_worklist_rows() -> pd.DataFrame:
    frame = worklist_frame()
    if frame.empty:
        return frame
    mask = frame["研究"].fillna(False).astype(bool)
    return frame.loc[mask].copy()


def announcement_for_row(row: pd.Series) -> CninfoAnnouncement | None:
    payload = st.session_state.worklist_announcements.get(
        worklist_key(str(row["证券代码"]), str(row["报告类型"]), int(row["报告期年份"]))
    )
    if not payload:
        return None
    try:
        return CninfoAnnouncement(**payload)
    except TypeError:
        return None


def persist_screen(source: str = "", title: str | None = None) -> None:
    research_id = st.session_state.research_id
    if not research_id:
        return
    research_store.save_screen(
        ROOT,
        current_account(),
        research_id,
        st.session_state.worklist or [],
        st.session_state.worklist_announcements or {},
        st.session_state.get("source_mode") or A_AUTO_SOURCE,
        market_mode=st.session_state.get("market_mode") or A_SHARE,
        source=source,
        title=title,
    )


def persist_summaries() -> None:
    research_id = st.session_state.research_id
    if not research_id:
        return
    research_store.save_summaries(ROOT, current_account(), research_id, st.session_state.summaries or [])


def persist_screenings() -> None:
    research_id = st.session_state.research_id
    if not research_id:
        return
    research_store.save_screenings(ROOT, current_account(), research_id, st.session_state.screenings or [])


def open_research(research_id: str) -> None:
    screen = research_store.load_screen(ROOT, current_account(), research_id)
    st.session_state.view = "research"
    st.session_state.research_id = research_id
    st.session_state.worklist = screen.get("worklist") or []
    st.session_state.worklist_announcements = screen.get("announcements") or {}
    st.session_state.market_mode = screen.get("market_mode") or A_SHARE
    st.session_state.source_mode = screen.get("source_mode") or (
        A_AUTO_SOURCE if st.session_state.market_mode == A_SHARE else HK_AUTO_SOURCE
    )
    st.session_state.summaries = research_store.load_summaries(ROOT, current_account(), research_id)
    st.session_state.comments = research_store.load_comments(ROOT, current_account(), research_id)
    st.session_state.screenings = research_store.load_screenings(ROOT, current_account(), research_id)
    st.session_state.pop("worklist_editor", None)
    st.session_state.pop("company_selection_v81", None)
    st.session_state.pop("summary_editor", None)
    for key in [item for item in st.session_state.keys() if str(item).startswith("pick_")]:
        st.session_state.pop(key, None)
    st.session_state.pending_quick = False
    st.session_state.pending_deep = False
    st.rerun()


def start_new_research(title: str = "") -> None:
    st.session_state.new_research_open = False
    meta = research_store.create_research(ROOT, current_account(), (title or "").strip() or "未命名研究")
    open_research(meta["id"])


_dialog_kwargs = {}
try:
    if "width" in inspect.signature(st.dialog).parameters:
        _dialog_kwargs["width"] = "small"
except (TypeError, ValueError, AttributeError):
    pass


@st.dialog("新建研究", **_dialog_kwargs)
def new_research_dialog() -> None:
    title = st.text_input("研究名称", placeholder="例如：2026半年报初筛", max_chars=80)
    create_col, cancel_col = st.columns(2)
    if create_col.button("创建", type="primary", **STRETCH):
        start_new_research(title)
    if cancel_col.button("取消", **STRETCH):
        st.session_state.new_research_open = False
        st.rerun()


def go_history() -> None:
    persist_screen()
    persist_summaries()
    st.session_state.view = "history"
    st.rerun()


st.markdown(
    css_for_theme(
        st.session_state.get("ui_theme", "Dark"),
        None,
    ),
    unsafe_allow_html=True,
)
st.markdown(
    f'<div class="app-topbar"><div class="app-topbar-user">{escape(str(st.session_state.user_name))}'
    f'<span class="app-topbar-account">{escape(str(st.session_state.user_account or ""))}</span></div></div>',
    unsafe_allow_html=True,
)

in_research = st.session_state.view == "research" and bool(st.session_state.research_id)
if in_research:
    st.markdown('<div class="nav-history"></div>', unsafe_allow_html=True)
    if st.button("研究历史", key="topbar_history"):
        go_history()

env_api_key = os.getenv("DEEPSEEK_API_KEY", "").strip() or os.getenv("OPENAI_API_KEY", "").strip()
st.markdown('<div class="topbar-dots"></div>', unsafe_allow_html=True)
with st.popover("⋮", help="设置"):
    select_language()
    if english():
        st.caption("English reports are translated after source-language validation. Translation uses additional model tokens; demo mode stays offline.")
        translator = st.session_state.get("_translator")
        if translator:
            st.caption(f"Translation tokens this session: {translator.input_tokens} input / {translator.output_tokens} output")
    with st.expander("页面风格", expanded=False):
        st.selectbox("界面风格", ["Dark", "Light"], key="ui_theme")
        st.caption("默认 Dark。可切换为浅色纸感界面，仅对本次登录有效。")
    if st.button("退出登录", **STRETCH):
        logout_session()
    with st.expander("API Key 设置", expanded=False):
        st.text_input(
            "API Key",
            type="password",
            placeholder="留空则用管理员密钥",
            help="所有人默认使用服务器密钥。原密钥不显示、不可复制；填写后仅本次登录有效。",
            key="api_key_override_input",
            autocomplete="off",
        )
        st.selectbox("模型", ["deepseek-v4-flash", "deepseek-v4-pro"], key="ds_model")
        st.text_input("API 地址", key="ds_base_url")
        st.slider("候选页数（深度点评）", 12, 48, key="ds_max_pages")
        st.slider("候选字符数（深度点评）", 30000, 120000, step=5000, key="ds_max_chars")
        st.checkbox("测试模式：不调用 DeepSeek", key="ds_test_mode")
        st.number_input("最多处理公司数（0=全部）", min_value=0, max_value=10000, step=1, key="ds_test_limit")
        if st.button("测试连接", **STRETCH):
            try:
                with st.spinner("正在测试……"):
                    connected_model = test_deepseek_connection(
                        (st.session_state.get("api_key_override_input") or "").strip() or env_api_key,
                        st.session_state.get("ds_model") or DEFAULT_MODEL,
                        st.session_state.get("ds_base_url") or DEFAULT_BASE_URL,
                    )
                st.success(f"连接成功：{connected_model}")
            except Exception as error:
                st.error(f"连接失败：{error}")

configure_translation()

override_key = (st.session_state.get("api_key_override_input") or "").strip()
api_key = override_key or env_api_key
model = st.session_state.get("ds_model") or DEFAULT_MODEL
base_url = st.session_state.get("ds_base_url") or DEFAULT_BASE_URL
max_pages = int(st.session_state.get("ds_max_pages") or 28)
max_chars = int(st.session_state.get("ds_max_chars") or 70000)
test_mode = bool(st.session_state.get("ds_test_mode"))
test_limit = int(st.session_state.get("ds_test_limit") or 0)


def render_history() -> None:
    st.markdown('<div class="page-mode-history"></div>', unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown('<div class="history-hero-anchor"></div>', unsafe_allow_html=True)
        st.markdown(
            """
            <div class="brandline"><span class="brandmark">研</span><span>财报经营分析助手 · V8.1</span></div>
            <div class="page-kicker">RESEARCH HISTORY</div>
            """,
            unsafe_allow_html=True,
        )
        col_kwargs = {}
        if "vertical_alignment" in inspect.signature(st.columns).parameters:
            col_kwargs["vertical_alignment"] = "center"
        title_col, new_col = st.columns([6.4, 0.9], **col_kwargs)
        with title_col:
            st.markdown('<div class="page-title history-page-title">研究历史</div>', unsafe_allow_html=True)
        with new_col:
            st.markdown('<div class="title-new"></div>', unsafe_allow_html=True)
            if st.button("新建", key="history_new", **STRETCH):
                st.session_state.new_research_open = True
            if st.session_state.get("new_research_open"):
                new_research_dialog()
        st.markdown(
            '<div class="page-subtitle">每位用户独立保存。先全市场筛选，再快速提炼，最后只对有意思的公司写点评。</div>',
            unsafe_allow_html=True,
        )
    items = research_store.list_researches(ROOT, current_account())
    if not items:
        st.info("还没有研究记录。点击标题右侧「新建」开始。")
        return
    st.caption(f"共 {len(items)} 条，仅显示当前账号。")
    for start in range(0, len(items), 2):
        cols = st.columns(2, gap="medium")
        for offset, col in enumerate(cols):
            index = start + offset
            if index >= len(items):
                break
            item = items[index]
            stage = research_store.STAGE_LABELS.get(str(item.get("stage") or "screen"), "全市场筛选")
            with col:
                with st.container(border=True):
                    st.markdown('<div class="history-card-anchor"></div>', unsafe_allow_html=True)
                    st.markdown(
                        f"<div class='pick-title'>{escape(str(item.get('title') or '未命名研究'))}</div>"
                        f"<div class='history-card'><div class='meta'>{escape(str(item.get('updated_at') or ''))}"
                        f"　{escape(stage)}　名单 {int(item.get('company_count') or 0)}"
                        f"　快筛 {int(item.get('quick_count') or 0)}"
                        f"　点评 {int(item.get('deep_count') or 0)}</div></div>",
                        unsafe_allow_html=True,
                    )
                    if st.button("打开", key=f"open_{item.get('id')}", **STRETCH):
                        open_research(str(item.get("id")))


def render_stage_header(current: str) -> None:
    states = {
        "screen": ("current", "future", "future"),
        "quick": ("done", "current", "future"),
        "deep": ("done", "done", "current"),
    }
    a, b, c = states.get(current, ("current", "future", "future"))
    st.markdown(
        f"""
        <div class="top-stagebar" aria-label="研究进度">
          <div class="top-stage {a}"><span class="top-stage-num">1</span><span class="top-stage-label">全市场筛选</span></div>
          <span class="top-stage-connector {a}"></span>
          <div class="top-stage {b}"><span class="top-stage-num">2</span><span class="top-stage-label">快速提炼</span></div>
          <span class="top-stage-connector {b}"></span>
          <div class="top-stage {c}"><span class="top-stage-num">3</span><span class="top-stage-label">深度点评</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_screen_panel() -> None:
    left, right = st.columns([1.05, 1.15], gap="large")
    with left:
        st.subheader("研究输入")
        st.radio(
            "上市市场",
            [A_SHARE, HK_SHARE],
            horizontal=True,
            key="market_mode",
            on_change=clear_for_market_change,
            help="每项研究只能选择一个市场；切换市场会清空当前研究名单及后续结果。",
        )
        market_mode = st.session_state.market_mode
        st.caption(
            "A股财报从巨潮资讯下载。"
            if market_mode == A_SHARE
            else "港股会先核验港交所正式报告；业绩公告不会被当作中期报告或年报。"
        )
        for message in st.session_state.get("market_messages") or []:
            st.warning(str(message))
        input_modes = (
            ["按日期选择", "上传 Excel", "直接输入名称/代码"]
            if market_mode == A_SHARE
            else ["上传 Excel", "直接输入名称/代码"]
        )
        input_mode = st.radio(
            "公司来源",
            input_modes,
            horizontal=True,
            key=f"company_source_{market_mode}",
        )
        date_mode = input_mode == "按日期选择"
        excel_upload = None
        company_text = ""
        zip_upload = None
        folder_value = ""
        auto_source = A_AUTO_SOURCE if market_mode == A_SHARE else HK_AUTO_SOURCE
        source_mode = st.session_state.get("source_mode") or auto_source

        if date_mode:
            default_yesterday = date.today() - timedelta(days=1)
            disclosure_date = st.date_input(
                "披露日期",
                value=default_yesterday,
                max_value=date.today(),
                format="YYYY-MM-DD",
                help="默认昨天。按巨潮公告披露日检索 A 股定期报告全文。",
                key="yesterday_disclosure_date",
            )
            if disclosure_date.weekday() >= 5:
                st.caption("昨天是周末时往往没有新披露，可改选最近交易日。")
            yesterday_types = st.multiselect(
                "报告类型",
                REPORT_TYPES,
                default=REPORT_TYPES,
                key="disclosure_report_types",
                help="可同时勾选季报、半年报、年报。",
            )
            if st.button("查询新披露名单", type="primary", **STRETCH):
                if not yesterday_types:
                    st.error("请至少选择一种报告类型。")
                else:
                    try:
                        with st.spinner("正在从巨潮资讯检索名单……"):
                            found = list_reports_by_date(ROOT / ".cache" / "cninfo", disclosure_date, yesterday_types)
                    except Exception:
                        st.error("财报数据源暂时无法连接，请稍后重试。现有名单未被修改。")
                        found = None
                    if found is None:
                        return
                    rows = []
                    announcements = {}
                    default_checked = len(found) <= 30
                    for item in found:
                        key = worklist_key(item.sec_code, item.report_type, item.report_year)
                        rows.append(
                            {
                                "研究": default_checked,
                                "证券代码": item.sec_code,
                                "证券名称": item.sec_name,
                                "报告类型": item.report_type,
                                "报告期年份": item.report_year,
                                "披露日期": item.announcement_date,
                            }
                        )
                        announcements[key] = asdict(item)
                    set_worklist(rows, announcements)
                    st.session_state.disclosure_search_count = len(rows)
                    st.session_state.source_mode = A_AUTO_SOURCE
                    persist_screen(
                        source="按日期选择",
                        title=f"{disclosure_date.isoformat()} 新披露 · {len(rows)}家",
                    )
                    st.rerun()
            if st.session_state.get("disclosure_search_count") == 0:
                st.info("所选披露日和报告类型没有匹配的财报。请尝试其他披露日；披露日期不是报告期截止日。")
        else:
            if input_mode == "上传 Excel":
                excel_upload = st.file_uploader(
                    "原始 Excel（.xlsx）",
                    type=["xlsx"],
                    help="只需有证券代码或证券名称任一列。",
                )
            else:
                company_text = st.text_area(
                    "股票名称或代码",
                    placeholder=(
                        "贵州茅台/600519/巨星科技/002444"
                        if market_mode == A_SHARE
                        else "腾讯控股/00700.HK/汇丰控股/00005.HK"
                    ),
                    height=92,
                )
            report_type = st.selectbox("报告类型", REPORT_TYPES, index=1)
            report_year = st.number_input(
                "报告期年份",
                min_value=2000,
                max_value=datetime.now().year,
                value=default_report_year(report_type),
                step=1,
                help="填写报告所属年份，不是公告发布年份。",
            )
            source_choices = [auto_source, "ZIP 压缩包"]
            if not CLOUD_SHARE:
                source_choices.append("本机文件夹")
            if st.session_state.get("source_mode") not in source_choices:
                st.session_state.source_mode = auto_source
            source_mode = st.radio(
                "PDF 来源",
                source_choices,
                horizontal=True,
                key="source_mode",
            )
            if source_mode == "ZIP 压缩包":
                zip_upload = st.file_uploader("包含财报 PDF 的 ZIP", type=["zip"])
            elif source_mode == "本机文件夹":
                folder_value = st.text_input("PDF 文件夹完整路径")
            if st.button("识别公司并列入右侧名单", **STRETCH):
                cninfo_cache = ROOT / ".cache" / "cninfo"
                try:
                    if input_mode == "上传 Excel":
                        if not excel_upload:
                            raise ValueError("请先上传 Excel。")
                        preview_dir = Path(tempfile.mkdtemp(prefix="filing_preview_"))
                        preview_excel = preview_dir / "input.xlsx"
                        preview_excel.write_bytes(excel_upload.getvalue())
                        _, identified = read_company_rows(preview_excel)
                        identified = normalise_company_rows(identified, cninfo_cache, market=market_mode)
                        shutil.rmtree(preview_dir, ignore_errors=True)
                        companies = [(row.stock_code, row.company_name) for row in identified]
                        source_name = "上传 Excel"
                    else:
                        if not company_text.strip():
                            raise ValueError("请填写至少一个股票名称或证券代码。")
                        resolved = parse_company_identifiers(company_text, cninfo_cache, market=market_mode)
                        companies = [(item.stock_code, item.company_name) for item in resolved]
                        source_name = "名称/代码"
                    rows = []
                    announcements: dict[str, dict] = {}
                    missing_reports: list[str] = []
                    for code, name in companies:
                        announcement = None
                        if market_mode == HK_SHARE and source_mode == HK_AUTO_SOURCE:
                            candidates = search_reports_for_company(
                                code,
                                name,
                                int(report_year),
                                report_type,
                                cninfo_cache,
                            )
                            if not candidates:
                                missing_reports.append(
                                    f"{code} {name}：港交所尚未发布{int(report_year)}年正式{report_type}；"
                                    "业绩公告不作为替代。"
                                )
                                continue
                            announcement = candidates[0]
                        row = {
                            "研究": True,
                            "证券代码": code,
                            "证券名称": name,
                            "报告类型": report_type,
                            "报告期年份": int(report_year),
                            "披露日期": announcement.announcement_date if announcement else "",
                        }
                        rows.append(row)
                        if announcement is not None:
                            announcements[worklist_key(code, report_type, int(report_year))] = asdict(announcement)
                    st.session_state.market_messages = missing_reports
                    set_worklist(rows, announcements)
                    persist_screen(source=source_name, title=f"{source_name} · {len(rows)}家")
                    if not rows and missing_reports:
                        raise ValueError(missing_reports[0])
                    st.rerun()
                except Exception as error:
                    st.error(str(error))
        st.session_state["_zip_upload"] = zip_upload
        st.session_state["_folder_value"] = folder_value

    with right:
        st.subheader("研究名单")
        current = worklist_frame()
        if current.empty:
            if st.session_state.market_mode == A_SHARE:
                st.info("按日期选择查询新披露，或识别 Excel / 名称代码后，A股公司会列在这里供勾选。")
            else:
                st.info("仅已找到港交所正式报告的港股公司会进入名单；业绩公告和未发布报告会被拦截。")
        else:
            selected_count = int(current['研究'].fillna(False).astype(bool).sum())
            if english():
                total_n = len(current)
                st.caption(
                    f"Total: {total_n} {'company' if total_n == 1 else 'companies'}; "
                    f"selected: {selected_count} {'company' if selected_count == 1 else 'companies'}. "
                    "Continue to quick analysis after selecting."
                )
            else:
                st.caption(f"共 {len(current)} 家，已勾选 {selected_count} 家。勾选后进入快速提炼。")
            if english():
                st.caption("股票名称按中文（英文）显示，可直接在表格中勾选。")
            action_left, action_right = st.columns(2)
            if action_left.button("全选", **STRETCH):
                updated = current.copy()
                updated["研究"] = True
                set_worklist(updated.to_dict("records"), st.session_state.worklist_announcements)
                persist_screen()
                st.rerun()
            if action_right.button("清空勾选", **STRETCH):
                updated = current.copy()
                updated["研究"] = False
                set_worklist(updated.to_dict("records"), st.session_state.worklist_announcements)
                persist_screen()
                st.rerun()
            edited = render_company_list(current, str(st.session_state.research_id))
            selection_changed = not current["研究"].equals(edited["研究"])
            st.session_state.worklist = edited.to_dict("records")
            persist_screen()
            if selection_changed:
                st.rerun()


def collect_pdfs_for_group(
    group: pd.DataFrame,
    year: int,
    rtype: str,
    job_dir: Path,
    download_bar=None,
    download_box=None,
    phase_label: str = "",
):
    source_mode = st.session_state.get("source_mode") or A_AUTO_SOURCE
    working_rows = [
        CompanyRow(index + 2, str(row["证券代码"]), str(row["证券名称"]), {})
        for index, row in enumerate(group.to_dict("records"))
    ]
    cninfo_cache = ROOT / ".cache" / "cninfo"
    if source_mode in AUTO_SOURCES:
        label = phase_label or f"{year}年{rtype}"
        if download_bar is None:
            download_bar = st.progress(0, text=f"正在下载 {label}……")
        if download_box is None:
            download_box = st.empty()
        download_records = []

        def update_download(current, total, record, bar=download_bar, box=download_box, tag=label):
            download_records.append(record)
            if english():
                bar.progress(current / max(total, 1), text=f"Downloading reports {current}/{total} · {company_display_label(record.company_name, record.stock_code)}")
                statuses = {"已缓存": "Cached", "已下载": "Downloaded", "未找到/下载失败": "Download failed"}
                box.dataframe(pd.DataFrame([
                    {"Ticker": item.stock_code, "Company": company_display_name(item.company_name, item.stock_code),
                     "Status": statuses.get(item.status, "Download failed"),
                     "Disclosure date": item.announcement_date, "Source": item.source_url}
                    for item in download_records[-12:]
                ]), hide_index=True)
            else:
                bar.progress(current / max(total, 1), text=f"下载 {tag}　{current}/{total}　{record.stock_code} {record.company_name}")
                box.dataframe(pd.DataFrame([item.__dict__ for item in download_records[-12:]]), hide_index=True)

        anns = []
        for row in group.to_dict("records"):
            item = announcement_for_row(pd.Series(row))
            if item is not None:
                anns.append(item)
        if source_mode == HK_AUTO_SOURCE:
            if len(anns) != len(working_rows):
                raise ValueError("港股名单缺少正式报告预检记录，请返回筛选页重新识别公司。")
            pdfs, _records = download_announcements(anns, cninfo_cache, progress=update_download)
            if len(pdfs) != len(working_rows):
                failed = len(working_rows) - len(pdfs)
                raise ValueError(f"有 {failed} 家港股正式报告下载或校验失败，已停止提炼，避免分析错误文件。")
        elif anns:
            pdfs, _records = download_announcements(anns, cninfo_cache, progress=update_download)
        else:
            pdfs, _records = download_reports_for_rows(
                working_rows, year, rtype, cninfo_cache, progress=update_download
            )
        download_bar.progress(1.0, text=f"{label} 下载完成：{len(pdfs)}/{len(working_rows)} 份")
        return pdfs, working_rows
    if source_mode == "ZIP 压缩包":
        zip_upload = st.session_state.get("_zip_upload")
        if not zip_upload:
            raise ValueError("请上传包含 PDF 的 ZIP。")
        return safely_extract_zip(zip_upload.getvalue(), job_dir / "pdfs"), working_rows
    folder = Path(st.session_state.get("_folder_value") or "").expanduser()
    if not folder.is_dir():
        raise ValueError("PDF 文件夹不存在。")
    return collect_pdfs(folder), working_rows


def run_quick_pass() -> bool:
    selected = selected_worklist_rows()
    if selected.empty:
        st.error("请先在研究名单中勾选至少一家公司。")
        return False
    if not test_mode and not api_key.strip():
        st.error("请填写 DeepSeek API Key，或先启用测试模式。")
        return False
    if int(test_limit):
        selected = selected.head(int(test_limit))
    job_dir = Path(tempfile.mkdtemp(prefix="filing_quick_"))
    summaries: list[dict] = []
    try:
        grouped: dict[tuple[int, str], list[dict]] = defaultdict(list)
        for record in selected.to_dict("records"):
            grouped[(int(record["报告期年份"]), str(record["报告类型"]))].append(record)
        group_items = list(grouped.items())
        st.subheader("快速提炼进行中")
        st.caption("先下载报告全文，下载完成后再逐家提炼。")
        download_bar = st.progress(0.0, text="正在下载报告全文……")
        download_box = st.empty()
        prepared: list[tuple[int, str, list[dict], list, dict]] = []
        for index, ((year, rtype), rows) in enumerate(group_items, start=1):
            group = pd.DataFrame(rows)
            try:
                pdfs, working_rows = collect_pdfs_for_group(
                    group,
                    year,
                    rtype,
                    job_dir,
                    download_bar=download_bar,
                    download_box=download_box,
                    phase_label=f"{index}/{len(group_items)}　{year}年{rtype}",
                )
            except Exception as error:
                st.error(str(error))
                continue
            prepared.append((year, rtype, rows, pdfs, {item.stock_code: item for item in working_rows}))
        download_bar.progress(1.0, text="报告下载完成，开始提炼。")
        extract_bar = st.progress(0.0, text="正在快速提炼……")
        status_box = st.empty()
        total = sum(len(rows) for _year, _rtype, rows, _pdfs, _map in prepared)
        done = 0
        for year, rtype, rows, pdfs, row_by_code in prepared:
            for record in rows:
                done += 1
                code = str(record["证券代码"])
                company_row = row_by_code.get(code) or CompanyRow(done + 1, code, str(record["证券名称"]), {})
                pdf, match_message = match_pdf(company_row, pdfs)
                summary = summarize_one_fast(
                    company_row,
                    pdf,
                    report_type=rtype,
                    report_year=year,
                    cache_dir=ROOT / ".cache",
                    api_key=api_key,
                    model=model,
                    base_url=base_url,
                    test_mode=test_mode,
                    disclosure_date=str(record.get("披露日期") or ""),
                    match_message=match_message,
                )
                summaries.append(summary)
                extract_bar.progress(done / max(total, 1), text=(f"Analyzing {done}/{total} · {code}" if english() else f"提炼 {done}/{total}　{code} {record['证券名称']}"))
                status_box.info(summary.get("headline") or summary.get("message") or "完成")
        st.session_state.summaries = summaries
        persist_summaries()
        if summaries:
            st.success(f"快速提炼完成：{len(summaries)} 家。")
        else:
            st.error("没有形成任何快筛结果。")
    finally:
        shutil.rmtree(job_dir, ignore_errors=True)
    return bool(summaries)


def _deep_result_key(item: dict) -> str:
    return "|".join(
        str(item.get(field) or "").strip().upper()
        for field in ("stock_code", "report_year", "report_type")
    )


def _valid_comment(item: dict | None) -> bool:
    if not item or str(item.get("status") or "完成") == "失败" or item.get("retryable"):
        return False
    raw = str(item.get("path") or "").strip()
    return bool(raw and Path(raw).is_file())


def _valid_screening(item: dict | None) -> bool:
    if not item or str(item.get("status") or "") != "完成" or item.get("retryable"):
        return False
    return bool(item.get("path") and Path(item["path"]).is_file()
                and not str(item.get("note") or "").startswith("排雷生成失败"))


def _deep_pending_items() -> list[dict]:
    comments = {_deep_result_key(item): item for item in (st.session_state.get("comments") or [])}
    screenings = {_deep_result_key(item): item for item in (st.session_state.get("screenings") or [])}
    return [
        item for item in (st.session_state.get("summaries") or [])
        if item.get("selected") and not (
            _valid_comment(comments.get(_deep_result_key(item)))
            and _valid_screening(screenings.get(_deep_result_key(item)))
        )
    ]


def current_job() -> dict:
    if not st.session_state.get("research_id"):
        return {}
    folder = research_store.research_dir(ROOT, current_account(), st.session_state.research_id)
    return read_job(job_path(folder, "en" if english() else "zh"))


def start_deep_background() -> None:
    chosen = [item for item in (st.session_state.summaries or []) if item.get("selected")]
    if not chosen:
        st.error("请先勾选至少一家有意思的公司。")
        return
    if not test_mode and not api_key.strip():
        st.error("请填写 DeepSeek API Key，或先启用测试模式。")
        return
    account, research_id = current_account(), st.session_state.research_id
    folder = research_store.research_dir(ROOT, account, research_id)
    launch_job(ROOT, folder, "en" if english() else "zh", {
        "account": account, "research_id": research_id, "chosen": chosen,
        "announcements": st.session_state.worklist_announcements,
        "model": model, "base_url": base_url, "test_mode": test_mode,
        "max_pages": max_pages, "max_chars": max_chars,
    }, api_key)


def run_deep_pass() -> None:
    chosen = [item for item in (st.session_state.summaries or []) if item.get("selected")]
    if not chosen:
        st.error("请先在快筛结果中勾选至少一家公司。")
        return
    if not test_mode and not api_key.strip():
        st.error("请填写 DeepSeek API Key，或先启用测试模式。")
        return
    research_id = st.session_state.research_id
    out_dir = research_store.comments_dir(ROOT, current_account(), research_id)
    job_dir = Path(tempfile.mkdtemp(prefix="filing_deep_"))
    comment_map = {_deep_result_key(item): item for item in (st.session_state.get("comments") or [])}
    screening_map = {_deep_result_key(item): item for item in (st.session_state.get("screenings") or [])}
    pending = [
        item for item in chosen
        if not (_valid_comment(comment_map.get(_deep_result_key(item))) and _valid_screening(screening_map.get(_deep_result_key(item))))
    ]
    if not pending:
        st.success("所选公司的深度点评与排雷报告均已完成，无需重复生成。")
        return

    def ordered(mapping: dict[str, dict]) -> list[dict]:
        keys = [_deep_result_key(item) for item in chosen]
        result = [mapping[key] for key in keys if key in mapping]
        result.extend(value for key, value in mapping.items() if key not in keys)
        return result

    def checkpoint() -> tuple[list[dict], list[dict]]:
        comments_now = ordered(comment_map)
        screenings_now = ordered(screening_map)
        st.session_state.comments = comments_now
        st.session_state.screenings = screenings_now
        research_store.save_comments(ROOT, current_account(), research_id, comments_now)
        persist_screenings()
        return comments_now, screenings_now

    try:
        st.subheader("深度点评进行中")
        st.caption("先核对并下载报告全文，再写深度点评并按 V3.0 框架生成排雷报告。已完成的公司可先预览或下载。")
        download_bar = st.progress(0.0, text="正在下载报告全文……")
        download_box = st.empty()
        grouped: dict[tuple[int, str], list[dict]] = defaultdict(list)
        for item in pending:
            grouped[(int(item["report_year"]), str(item["report_type"]))].append(item)
        group_items = list(grouped.items())
        prepared: list[tuple[int, str, list[dict], list, dict]] = []
        for index, ((year, rtype), rows) in enumerate(group_items, start=1):
            frame = pd.DataFrame(
                [
                    {
                        "证券代码": item["stock_code"],
                        "证券名称": item["company_name"],
                        "报告类型": rtype,
                        "报告期年份": year,
                        "披露日期": item.get("disclosure_date") or "",
                    }
                    for item in rows
                ]
            )
            try:
                pdfs, working_rows = collect_pdfs_for_group(
                    frame,
                    year,
                    rtype,
                    job_dir,
                    download_bar=download_bar,
                    download_box=download_box,
                    phase_label=f"{index}/{len(group_items)}　{year}年{rtype}",
                )
            except Exception as error:
                st.error(str(error))
                continue
            prepared.append((year, rtype, rows, pdfs, {item.stock_code: item for item in working_rows}))
        download_bar.progress(1.0, text="报告下载完成，开始撰写点评与排雷报告。")
        progress_bar = st.progress(0.0, text="正在生成点评与排雷报告……")
        status_box = st.empty()
        done_box = st.empty()
        screening_dir = research_store.screenings_dir(ROOT, current_account(), research_id)
        total = sum(len(rows) for _year, _rtype, rows, _pdfs, _map in prepared)
        done = 0
        for year, rtype, rows, pdfs, row_by_code in prepared:
            for item in rows:
                done += 1
                code = str(item["stock_code"])
                result_key = _deep_result_key(item)
                company_row = row_by_code.get(code) or CompanyRow(done + 1, code, str(item["company_name"]), {})
                pdf, match_message = match_pdf(company_row, pdfs)
                filename = research_store.safe_comment_filename(code, company_row.company_name, year, rtype)
                output_path = out_dir / filename
                comment = comment_map.get(result_key)
                if not _valid_comment(comment):
                    progress_bar.progress((done-1) / max(total, 1), text=(
                        f"Writing deep report {done}/{total} · {code}" if english()
                        else f"正在撰写深度点评 {done}/{total}　{code} {company_row.company_name}"
                    ))
                    status_box.info("The report is being generated. Completed files are saved automatically." if english()
                                    else "正在核对财报并生成点评，已完成文件会自动保存。")
                    try:
                        comment = comment_one_company(
                            company_row, pdf, output_path, report_type=rtype, report_year=year,
                            cache_dir=ROOT / ".cache", api_key=api_key, model=model, base_url=base_url,
                            test_mode=test_mode, max_pages=max_pages, max_chars=max_chars,
                            disclosure_date=str(item.get("disclosure_date") or ""), match_message=match_message,
                        )
                    except Exception as error:
                        comment = {
                            "stock_code": code, "company_name": company_row.company_name,
                            "report_type": rtype, "report_year": year, "path": "", "status": "失败",
                            "message": f"{type(error).__name__}: {error}",
                        }
                    comment_map[result_key] = comment
                    checkpoint()
                if not _valid_comment(comment):
                    progress_bar.progress(done / max(total, 1), text=f"{done}/{total}　{code} 点评失败，可稍后续跑")
                    status_box.error(str(comment.get("message") or "深度点评失败"))
                    continue
                evidence_text = ""
                source_url = screening_engine.cninfo_search_url(code)
                if pdf:
                    try:
                        pages = extract_pdf_pages(pdf, ROOT / ".cache" / "pdf_text")
                        evidence_pages = select_evidence_pages(pages, company_row.metrics or {}, max_pages=max_pages, max_chars=max_chars)
                        evidence_text = "\n\n".join(
                            f"===== PDF第{page.page}页 =====\n{page.text}" for page in evidence_pages
                        )
                        meta_pdf = load_cninfo_metadata(pdf)
                        if str(meta_pdf.get("source_url") or "").startswith("http"):
                            source_url = str(meta_pdf["source_url"])
                    except Exception:
                        evidence_text = ""
                screening = screening_map.get(result_key)
                if not _valid_screening(screening):
                    progress_bar.progress((done-1) / max(total, 1), text=(
                        f"Writing risk report {done}/{total} · {code}" if english()
                        else f"正在生成排雷报告 {done}/{total}　{code} {company_row.company_name}"
                    ))
                    try:
                        screening = screen_full(
                            company_name=company_row.company_name, stock_code=code, report_type=rtype,
                            report_year=year, metrics=company_row.metrics or {}, evidence_text=evidence_text,
                            source_url=source_url, output_dir=screening_dir, api_key=api_key, model=model,
                            base_url=base_url, test_mode=test_mode, industry=str(item.get("business") or ""),
                            disclosure_date=str(item.get("disclosure_date") or ""),
                        )
                    except Exception as error:
                        screening = {
                            "stock_code": code, "company_name": company_row.company_name,
                            "report_type": rtype, "report_year": year, "status": "失败", "retryable": True,
                            "note": f"排雷生成失败：{type(error).__name__}: {error}", "message": str(error),
                        }
                    screening_map[result_key] = screening
                comments, screenings = checkpoint()
                progress_bar.progress(done / max(total, 1), text=(
                    f"Processed {done}/{total} · {company_display_label(str(item['company_name']), code)}" if english()
                    else f"{done}/{total}　{code} {item['company_name']}"
                ))
                if _valid_screening(screening):
                    status_box.info(f"点评已完成；排雷结论 {screening.get('conclusion')}")
                else:
                    status_box.warning("点评已完成；排雷报告失败，可稍后续跑。")
                with done_box.container():
                    st.caption(f"已完成 {done}/{total}，可先预览或下载，其余继续生成。")
                    render_completed_outputs(comments, screenings, key_prefix=f"live_{done}")
        comments, screenings = checkpoint()
        remaining = len(_deep_pending_items())
        if comments and not remaining:
            st.success(f"已生成 {len(comments)} 份点评和 {len(screenings)} 份排雷报告。")
        elif comments:
            st.warning(f"本轮已保存进度，仍有 {remaining} 家未完成或失败；可点击继续按钮断点续跑。")
        else:
            st.error("没有生成点评文件。")
    finally:
        shutil.rmtree(job_dir, ignore_errors=True)


def pick_checkbox_key(item: dict, index: int) -> str:
    return f"pick_{item.get('stock_code')}_{item.get('report_type')}_{item.get('report_year')}_{index}"


def apply_pick_selection(selected: bool) -> None:
    for index, item in enumerate(st.session_state.summaries or []):
        item["selected"] = selected
        st.session_state[pick_checkbox_key(item, index)] = selected
    persist_summaries()


def render_pick_card(index: int, item: dict) -> bool:
    code = str(item.get("stock_code") or "")
    name = str(item.get("company_name") or "")
    rtype = str(item.get("report_type") or "")
    year = item.get("report_year") or ""
    status = str(item.get("status") or "")
    selected = bool(item.get("selected"))
    metrics = []
    if item.get("revenue_yoy_pct") is not None:
        metrics.append(f"营收同比 {item['revenue_yoy_pct']:+.1f}%")
    if item.get("parent_profit_yoy_pct") is not None:
        label = '普通股股东利润同比' if item.get('parent_profit_basis') == 'ordinary_shareholders' else '归母同比'
        metrics.append(f"{label} {item['parent_profit_yoy_pct']:+.1f}%")
    driver = str(item.get("driver") or item.get("headline") or "—")
    if metrics:
        driver = f"{driver}　{' · '.join(metrics)}"
    business = str(item.get("business") or "").strip() or "候选页未写明主营业务"
    substance = str(item.get("substance") or item.get("summary") or "业绩实质无法判断").strip()
    substance = re.sub(r"\s*\n+\s*", "", substance)
    changed = False
    widget_key = pick_checkbox_key(item, index)
    if widget_key not in st.session_state:
        st.session_state[widget_key] = selected
    with st.container(border=True):
        check_col, title_col, ask_col = st.columns([0.14, 0.68, 0.18], gap="small")
        with check_col:
            checked = st.checkbox(
                "选择",
                key=widget_key,
                label_visibility="collapsed",
            )
        with title_col:
            native_st.markdown(
                f"<div class='pick-title'>{escape(company_display_label(name, code))}</div>",
                unsafe_allow_html=True,
            )
        with ask_col:
            help_text = f"Ask the research assistant about {company_display_label(name, code)}" if english() else f"让右侧助手分析 {name}"
            if st.button("👉", key=f"llm_pick_{index}_{code}_{name}", help=help_text, **STRETCH):
                st.session_state.llm_chat_messages = []
                st.session_state.llm_pending_prompt = ""
                st.session_state.llm_last_status = ""
                st.session_state.llm_ignore_prompt_once = ""
                st.session_state.pop("llm_chat_input", None)
                st.session_state.llm_drawer_open = True
                st.session_state.llm_active_company_key = code or name
                # Ticker mentions survive both language changes and multiword
                # English issuer names when the chat parser selects context.
                st.session_state.llm_chat_prefill = f"@{code or name} "
                st.rerun()
        if bool(checked) != selected:
            item["selected"] = bool(checked)
            selected = bool(checked)
            changed = True
        anchor = "pick-card-anchor selected" if selected else "pick-card-anchor"
        st.markdown(f'<div class="{anchor}"></div>', unsafe_allow_html=True)
        st.markdown(
            f"<div class='pick-card{' selected' if selected else ''}'>"
            f"<div class='pick-tags'>"
            f"<span class='pick-tag'>{escape(str(year))}年{escape(rtype)}</span>"
            f"{summary_status_badge_html(status, is_english=english())}"
            f"</div>"
            f"<div class='pick-row'><div class='pick-label'>主要业务</div>"
            f"<div class='pick-body'>{escape(business)}</div></div>"
            f"{preliminary_risk_html(str(item.get('screening_conclusion') or '未完成'), item.get('screening_hits') or [], str(item.get('screening_note') or ''), is_english=english())}"
            f"<div class='pick-row'><div class='pick-label'>业绩要点</div>"
            f"<div class='pick-body'>{escape(driver)}</div></div>"
            f"<div class='pick-row'><div class='pick-label'>业绩实质</div>"
            f"<div class='pick-body substance'>{escape(substance)}</div></div>"
            f"</div>",
            unsafe_allow_html=True,
        )
    return changed


def render_quick_panel(*, workspace: bool = False) -> None:
    summaries = st.session_state.get("summaries") or []
    if not summaries:
        return
    st.subheader("快速提炼结果")
    st.caption("勾选值得继续研究的公司，业务实质卡片保留在左侧，右侧查看深度研究与风险核验。")
    action_left, action_right = st.columns(2)
    if action_left.button("全选有意思的", key="sum_all", **STRETCH):
        apply_pick_selection(True)
        st.rerun()
    if action_right.button("清空勾选", key="sum_none", **STRETCH):
        apply_pick_selection(False)
        st.rerun()

    changed = False
    step = 1 if workspace else 2
    for start in range(0, len(summaries), step):
        cols = [st.container()] if workspace else st.columns(2, gap="medium")
        for offset, col in enumerate(cols):
            index = start + offset
            if index >= len(summaries):
                break
            with col:
                if render_pick_card(index, summaries[index]):
                    changed = True
    if changed:
        persist_summaries()
    selected_n = sum(1 for item in summaries if item.get("selected"))
    st.caption(f"已勾选 {selected_n} / {len(summaries)} 家。")
    running = current_job()
    if st.button("生成深度点评", type="primary", disabled=active_job(running), **STRETCH):
        if selected_n <= 0:
            st.error("请先勾选至少一家有意思的公司。")
        else:
            st.session_state.pending_deep = True
            st.rerun()


def preview_markdown(path: Path, label: str, *, expanded: bool, key: str) -> None:
    if not path.is_file():
        return
    try:
        path = localize_artifact(path)
    except TranslationError as error:
        st.error(str(error))
        return
    kwargs = {"expanded": expanded}
    try:
        if "key" in inspect.signature(st.expander).parameters:
            kwargs["key"] = key
    except (TypeError, ValueError):
        pass
    with st.expander(label, **kwargs):
        try:
            text = path.read_text(encoding="utf-8")
        except Exception as error:
            st.error(f"无法读取预览：{error}")
            return
        if not text.strip():
            st.caption("文件为空。")
            return
        st.markdown(text)


def render_completed_outputs(comments: list[dict], screenings: list[dict], key_prefix: str = "done", *, focused: bool = False) -> None:
    bundles: dict[str, dict] = {}
    order: list[str] = []

    def _key_of(item: dict) -> str:
        return "|".join(
            [
                str(item.get("stock_code") or ""),
                str(item.get("report_year") or ""),
                str(item.get("report_type") or ""),
            ]
        )

    for item in comments or []:
        key = _key_of(item) or f"comment_{len(order)}"
        if key not in bundles:
            bundles[key] = {}
            order.append(key)
        bundles[key]["comment"] = item
    for item in screenings or []:
        key = _key_of(item) or f"screening_{len(order)}"
        if key not in bundles:
            bundles[key] = {}
            order.append(key)
        bundles[key]["screening"] = item
    if not order:
        return
    if focused:
        def company_label(key):
            entry = bundles[key].get('comment') or bundles[key].get('screening') or {}
            name, code = str(entry.get('company_name') or ''), str(entry.get('stock_code') or '')
            return company_display_label(name, code)
        chosen = native_st.selectbox('Company' if english() else '公司', order, format_func=company_label,
                                     key=f'{key_prefix}_report_company')
        order = [chosen]

    for index, key in enumerate(order):
        bundle = bundles[key]
        comment = bundle.get("comment") or {}
        screening = bundle.get("screening") or {}
        name = comment.get("company_name") or screening.get("company_name") or "未命名公司"
        code = comment.get("stock_code") or screening.get("stock_code") or ""
        year = comment.get("report_year") or screening.get("report_year") or ""
        rtype = comment.get("report_type") or screening.get("report_type") or ""
        conclusion = screening.get("conclusion") or ""
        hits = screening.get("hits") or []
        hit_text = f"　命中 {'、'.join(hits)}" if hits else ""
        title_bits = [f"**{company_display_label(str(name), str(code))}**"]
        if year or rtype:
            title_bits.append(translate(f"{year}年{rtype}" if year else str(rtype), strict=False))
        if conclusion:
            title_bits.append(f"**{translate(str(conclusion), strict=False)}**{translate(hit_text, strict=False)}")
        native_st.markdown("　".join(title_bits))
        if screening.get("note") or comment.get("message"):
            st.caption(str(screening.get("note") or comment.get("message") or ""))

        comment_path = Path(comment.get("path") or "")
        md_path = Path(screening.get("path") or "")
        docx_path = Path(screening.get("docx_path") or "")
        try:
            comment_path = localize_artifact(comment_path)
            md_path = localize_artifact(md_path)
            docx_path = localize_artifact(docx_path)
        except TranslationError as error:
            st.error(str(error))
            continue
        buttons = st.columns([1.1, 1.1, 1.1, 1.7])
        with buttons[0]:
            if comment_path.is_file():
                st.download_button(
                    "下载点评 MD",
                    data=comment_path.read_bytes(),
                    file_name=comment_path.name,
                    mime="text/markdown",
                    key=f"{key_prefix}_c_{index}",
                    **STRETCH,
                )
        with buttons[1]:
            if md_path.is_file():
                st.download_button(
                    "下载排雷 MD",
                    data=md_path.read_bytes(),
                    file_name=md_path.name,
                    mime="text/markdown",
                    key=f"{key_prefix}_smd_{index}",
                    **STRETCH,
                )
        with buttons[2]:
            if docx_path.is_file():
                st.download_button(
                    "下载排雷 Word",
                    data=docx_path.read_bytes(),
                    file_name=docx_path.name,
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    key=f"{key_prefix}_sdocx_{index}",
                    **STRETCH,
                )
            elif screening and screening.get("docx_error"):
                st.caption("Word 未生成")
        if focused:
            brief_tab, risk_tab = st.tabs(['深度研究', '风险核验'])
            with brief_tab:
                preview_markdown(comment_path, '研究简报', expanded=True, key=f'{key_prefix}_cprev_{index}')
            with risk_tab:
                preview_markdown(md_path, '风险核验报告', expanded=True, key=f'{key_prefix}_sprev_{index}')
        else:
            preview_markdown(comment_path, f"预览深度点评　{comment_path.name or name}",
                             expanded=index == 0, key=f"{key_prefix}_cprev_{index}")
            preview_markdown(md_path, f"预览排雷报告　{md_path.name or name}",
                             expanded=False, key=f"{key_prefix}_sprev_{index}")
        if screening.get("docx_error") and not docx_path.is_file():
            st.caption(f"排雷 Word 未生成：{screening.get('docx_error')}")


def render_comments_panel() -> None:
    comments = st.session_state.get("comments") or []
    screenings = st.session_state.get("screenings") or []
    pending = _deep_pending_items()
    if not comments and not screenings and not pending:
        return
    st.subheader("深度点评与排雷报告")
    st.caption("每家公司一份七章研究简报与风险核验报告。证据不足会单独列出，结论可回到原始财报核查。")
    if pending:
        job = current_job()
        attempted = bool(comments or screenings or job)
        if not active_job(job):
            if attempted:
                st.warning(f"还有 {len(pending)} 家未完成或上次失败，已完成结果不会被覆盖。")
            else:
                st.info((f"{len(pending)} selected company is ready for report generation." if len(pending) == 1
                         else f"{len(pending)} selected companies are ready for report generation.") if english()
                        else f"已选择 {len(pending)} 家公司，可以开始生成报告。")
        action_label = ("继续未完成/失败公司" if attempted else
                        ("Generate selected reports" if english() else "生成所选公司报告"))
        if st.button(action_label, key="resume_deep_pass", disabled=active_job(job), **STRETCH):
            st.session_state.pending_deep = True
            st.rerun()
    render_completed_outputs(comments, screenings, key_prefix="final", focused=True)


def _summary_key(item: dict) -> str:
    return str(item.get("stock_code") or item.get("company_name") or "").strip()


def _active_summary_from_message(message: str) -> dict:
    token = ""
    found = re.search(r"@([^\s，,。；;：:]+)", message or "")
    if found:
        token = found.group(1).strip()
    if not token:
        token = str(st.session_state.get("llm_active_company_key") or "").strip()
    for item in st.session_state.get("summaries") or []:
        name = str(item.get("company_name") or "").strip()
        code = str(item.get("stock_code") or "").strip()
        if token and (token == name or token == code or token in name or token in code):
            return item
    return {}


def _resolve_summary_pdf(summary: dict) -> Path | None:
    raw = str(summary.get("matched_pdf_path") or "").strip()
    if raw:
        path = Path(raw)
        if path.is_file():
            return path
    filename = str(summary.get("matched_pdf") or "").strip()
    if not filename:
        return None
    roots = [
        ROOT / ".cache",
        ROOT / "data",
        research_store.research_dir(ROOT, current_account(), st.session_state.research_id) if st.session_state.get("research_id") else ROOT,
    ]
    for root in roots:
        try:
            for hit in root.rglob(filename):
                if hit.is_file():
                    return hit
        except Exception:
            continue
    return None


def _llm_context_for_message(message: str) -> tuple[str, str, str]:
    summary = _active_summary_from_message(message)
    if not summary:
        return "", "", ""
    st.session_state.llm_active_company_key = _summary_key(summary)
    hk_mode = str(summary.get('stock_code') or '').upper().endswith('.HK')
    currency = str(summary.get('currency') or ('CNY' if not hk_mode else '未核验原币'))
    amount_unit = f'亿{currency}'
    adjusted_label = '发行人经调整利润（非GAAP）' if hk_mode else '扣非净利润'
    parent_label = '母公司普通股股东应占利润' if summary.get('parent_profit_basis') == 'ordinary_shareholders' else '归母净利润'
    facts = {
        "证券代码": summary.get("stock_code"),
        "证券名称": summary.get("company_name"),
        "报告类型": summary.get("report_type"),
        "报告期年份": summary.get("report_year"),
        "披露日期": summary.get("disclosure_date"),
        f"营业总收入_{amount_unit}": summary.get("revenue_billion") if not hk_mode or summary.get('currency') else None,
        f"{parent_label}_{amount_unit}": summary.get("parent_profit_billion") if not hk_mode or summary.get('currency') else None,
        f"{adjusted_label}_{amount_unit}": summary.get("adjusted_profit_billion") if not hk_mode or summary.get('currency') else None,
        "营收同比_%": summary.get("revenue_yoy_pct"),
        f"{parent_label}同比_%": summary.get("parent_profit_yoy_pct"),
        f"{adjusted_label}同比_%": summary.get("adjusted_profit_yoy_pct"),
        "主要业务": summary.get("business"),
        "业绩要点": summary.get("driver") or summary.get("headline"),
        "业绩实质": summary.get("substance") or summary.get("summary"),
        "快速排雷": summary.get("screening_note"),
    }
    parts = ["当前选中公司快筛材料：", json.dumps(facts, ensure_ascii=False, default=str)]
    source_note = "已读取快筛卡片材料。"
    pdf = _resolve_summary_pdf(summary)
    if pdf:
        try:
            pages = extract_pdf_pages(pdf, ROOT / ".cache" / "llm_pdf_text")
            used = 0
            chunks = []
            limit = 65000
            from deep_research import select_deep_evidence
            for page in select_deep_evidence(pages, max_pages=28, max_chars=limit):
                text = (page.text or "").strip()
                if not text:
                    continue
                chunk = f"\n\n===== 财报PDF第{page.page}页 =====\n{text}"
                if used + len(chunk) > limit:
                    break
                chunks.append(chunk)
                used += len(chunk)
            if chunks:
                parts.append("当前选中公司财报可提取文本：" + "".join(chunks))
                source_note = f"已读取财报 PDF：{pdf.name}，本轮最多提供 {limit:,} 字。"
        except Exception as error:
            source_note = f"财报 PDF 抽取失败，已退回快筛材料：{type(error).__name__}: {error}"
    else:
        source_note = "未找到对应财报 PDF，已退回快筛卡片材料。"
    display = company_display_label(str(summary.get('company_name') or ''), str(summary.get('stock_code') or ''))
    return "\n".join(parts), source_note, display


def build_llm_messages(message: str) -> tuple[list[dict], str, str]:
    context, source_note, display = _llm_context_for_message(message)
    history = []
    for item in list(st.session_state.get("llm_chat_messages") or [])[-24:]:
        role = str(item.get("role") or "")
        if role == "user":
            content = str(item.get("content") or item.get("question") or "").strip()
            if content:
                history.append({"role": "user", "content": content})
        elif role == "assistant":
            content = str(item.get("content") or item.get("answer") or "").strip()
            if content:
                history.append({"role": "assistant", "content": content})
        else:
            question = str(item.get("question") or "").strip()
            answer = str(item.get("answer") or "").strip()
            if question:
                history.append({"role": "user", "content": question})
            if answer:
                history.append({"role": "assistant", "content": answer})
    system_text = (
        "你是财报经营分析助手内置的 LLM 对话框。回答要简洁、中文、投研工作台口吻。"
        "如果本轮提供了公司财报上下文，只能基于该上下文回答；涉及财务指标必须引用上下文中的数字。"
        "没有被提供材料时，不要假装看过某份财报。涉及投资判断时提醒用户这只是研究辅助，不构成投资建议。"
    )
    if english():
        system_text = (
            "You are the Financial Report Screening and Analysis System assistant. Answer entirely in English, including "
            "headings, company names and quoted evidence (label quotations as translations). "
            "Use only the supplied company context when present, and cite its figures accurately. "
            "Never claim to have read a filing that was not supplied. State uncertainty explicitly. "
            "Financial assessments are research assistance, not investment advice."
        )
    messages = [{"role": "system", "content": system_text}]
    if context:
        messages.append({"role": "user", "content": f"当前公司上下文如下：\n{context}\n\n上下文状态：{source_note}"})
    messages.extend(history)
    messages.append({"role": "user", "content": re.sub(r"@([^\s，,。；;：:]+)", "", message or "", count=1).strip() or message})
    return messages, source_note, display


def ask_general_llm(message: str) -> tuple[str, dict]:
    if st.session_state.get("ds_test_mode"):
        return "当前为测试模式：这里会显示模型回复。关闭测试模式并填写 API Key 后即可正常对话。", {}
    if not api_key.strip():
        raise RuntimeError("请先在右上角设置里填写 DeepSeek API Key，或在 .env 中配置管理员密钥。")
    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=180.0,
        max_retries=1,
    )
    messages, source_note, display = build_llm_messages(message)
    response = client.chat.completions.create(
        model=model,
        temperature=0.2,
        max_tokens=1600,
        messages=messages,
    )
    usage = getattr(response, "usage", None)
    meta = {
        "input_tokens": int(getattr(usage, "prompt_tokens", 0) or 0) if usage else 0,
        "output_tokens": int(getattr(usage, "completion_tokens", 0) or 0) if usage else 0,
    }
    meta["source_note"] = source_note
    meta["company"] = display
    return response.choices[0].message.content or "", meta


def stream_general_llm(message: str, prepared_messages: list[dict] | None = None):
    if st.session_state.get("ds_test_mode"):
        yield "content", "当前为测试模式：这里会显示模型回复。关闭测试模式并填写 API Key 后即可正常对话。"
        return
    if not api_key.strip():
        raise RuntimeError("请先在右上角设置里填写 DeepSeek API Key，或在 .env 中配置管理员密钥。")
    timeout = httpx_runtime.Timeout(30.0, connect=10.0, read=20.0, write=20.0, pool=10.0)
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=0)
    messages = prepared_messages or build_llm_messages(message)[0]
    stream = client.chat.completions.create(
        model=model,
        temperature=0.2,
        max_tokens=1600,
        messages=messages,
        stream=True,
    )
    started_at = time.monotonic()
    reasoning_chars = 0
    next_reasoning_update = 50
    english_buffer = []
    for chunk in stream:
        if time.monotonic() - started_at > 45:
            raise TimeoutError("模型思考超过 45 秒，已终止本轮，请缩短问题后重试。")
        delta = chunk.choices[0].delta if chunk.choices else None
        reasoning = str(getattr(delta, "reasoning_content", "") or "") if delta else ""
        if reasoning:
            reasoning_chars += len(reasoning)
            if reasoning_chars >= next_reasoning_update:
                next_reasoning_update += 50
                yield "thinking", str(reasoning_chars)
        content = str(getattr(delta, "content", "") or "") if delta else ""
        if content:
            if english():
                english_buffer.append(content)
            else:
                yield "content", content
    if english_buffer:
        yield "content", translate("".join(english_buffer))


def render_llm_toggle() -> None:
    is_open = bool(st.session_state.get("llm_drawer_open"))
    st.markdown(f'<div class="llm-drawer-state{" is-open" if is_open else ""}"></div>', unsafe_allow_html=True)
    if st.button("‹" if is_open else "›", key="llm_drawer_toggle", help="展开/收回对话框"):
        if is_open:
            st.session_state.llm_drawer_open = False
            st.session_state.llm_chat_messages = []
            st.session_state.llm_active_company_key = ""
            st.session_state.llm_chat_prefill = ""
            st.session_state.llm_pending_prompt = ""
            st.session_state.llm_last_status = ""
            st.session_state.llm_ignore_prompt_once = ""
            st.session_state.pop("llm_chat_input", None)
        else:
            st.session_state.llm_drawer_open = True
        st.rerun()


def render_llm_panel() -> None:
    st.markdown("<div class='llm-chat-root'></div>", unsafe_allow_html=True)
    messages = list(st.session_state.get("llm_chat_messages") or [])[-40:]
    pending_prompt = str(st.session_state.get("llm_pending_prompt") or "").strip()
    stream_placeholder = None
    active_summary = _active_summary_from_message("")
    active_name = str(active_summary.get("company_name") or "").strip()
    active_code = str(active_summary.get("stock_code") or "").strip()
    active_label = company_display_label(active_name, active_code) if active_name or active_code else ("No company selected" if english() else "未选择公司")
    assistant_title = "Research Assistant" if english() else "研究助手"
    context_title = "Current context: " if english() else "当前上下文："
    native_st.markdown(
        f"<div class='llm-header'><div><div class='llm-title'>{assistant_title}</div>"
        f"<div class='llm-subtitle'>{context_title}{escape(active_label)}</div></div>"
        f"<div class='llm-badge'>{escape(model)}</div></div>",
        unsafe_allow_html=True,
    )
    with st.container(border=False):
        st.markdown("<div class='llm-transcript-anchor'></div>", unsafe_allow_html=True)
        if not messages and not st.session_state.get("llm_pending_prompt"):
            st.markdown(
                "<div class='llm-empty'><div class='llm-empty-title'>我可以帮你读财报、拆业绩、找风险。</div>"
                "<div class='llm-empty-sub'>点击快筛卡片右上角 👉 会自动带入公司和财报上下文；也可以直接输入问题。</div></div>",
                unsafe_allow_html=True,
            )
        for item in messages:
            role = str(item.get("role") or "pair")
            token_note = ""
            if item.get("input_tokens") or item.get("output_tokens"):
                token_note = f" · {item.get('input_tokens', 0)} in / {item.get('output_tokens', 0)} out"
            if role == "user":
                st.markdown(
                    "<div class='llm-msg user'>"
                    f"{escape(str(item.get('content') or item.get('question') or '')).replace(chr(10), '<br>')}"
                    "</div>",
                    unsafe_allow_html=True,
                )
                continue
            if role == "assistant":
                st.markdown(
                    f"<div class='llm-meta'>DeepSeek{escape(' · ' + str(item.get('company')) if item.get('company') else '')}{escape(token_note)}</div>",
                    unsafe_allow_html=True,
                )
                st.markdown(str(item.get("content") or item.get("answer") or ""))
                continue
            st.markdown(
                "<div class='llm-msg user'>"
                f"{escape(str(item.get('question') or '')).replace(chr(10), '<br>')}"
                "</div>",
                unsafe_allow_html=True,
            )
            st.markdown(
                f"<div class='llm-meta'>DeepSeek{escape(' · ' + str(item.get('company')) if item.get('company') else '')}{escape(token_note)}</div>",
                unsafe_allow_html=True,
            )
            st.markdown(str(item.get("answer") or ""))
        if pending_prompt:
            st.markdown(
                "<div class='llm-msg user'>"
                f"{escape(pending_prompt).replace(chr(10), '<br>')}"
                "</div>",
                unsafe_allow_html=True,
            )
            stream_placeholder = st.empty()
    last = messages[-1] if messages else {}
    thinking_text = "模型正在阅读材料并生成回答……" if pending_prompt else "等待指令"
    if last and not pending_prompt:
        thinking_text = (
            f"上次完成于 {escape(str(last.get('time') or ''))}"
            f" · 输入 {int(last.get('input_tokens') or 0)} / 输出 {int(last.get('output_tokens') or 0)} tokens"
        )
    st.markdown(
        f"<div class='llm-thinking'><span class='llm-thinking-dot'></span>{thinking_text}</div>",
        unsafe_allow_html=True,
    )
    st.markdown("<div class='llm-input-marker'></div>", unsafe_allow_html=True)
    prefill = str(st.session_state.pop("llm_chat_prefill", "") or "")
    st.markdown(
        f"<div class='llm-composer-head'><span class='llm-plus'>＋</span>"
        f"<span class='llm-context-pill'>▦ {escape(active_label)}</span>"
        f"<span class='llm-model-pill'>{escape(model)}</span></div>",
        unsafe_allow_html=True,
    )
    prompt = st.chat_input(
        placeholder=(prefill + "请输入问题…") if prefill else "Tell AI what to do next…",
        key="llm_chat_input",
        disabled=bool(pending_prompt),
    )
    if prompt and str(prompt).strip() and not pending_prompt:
        st.session_state.llm_pending_prompt = str(prompt).strip()
        st.rerun()
    if pending_prompt and stream_placeholder is not None:
        try:
            prepared_messages, source_note, company_display = build_llm_messages(pending_prompt)
            st.session_state.llm_last_status = source_note or "正在调用模型流式输出……"
            answer_parts = []
            for event_type, piece in stream_general_llm(pending_prompt, prepared_messages=prepared_messages):
                if event_type == "thinking":
                    if not answer_parts:
                        stream_placeholder.info(f"模型正在思考，已处理约 {piece} 字推理过程……")
                    continue
                answer_parts.append(piece)
                stream_placeholder.markdown("".join(answer_parts) + "▌")
            answer = "".join(answer_parts).strip()
            if not answer:
                raise RuntimeError("接口没有返回有效内容，请稍后重试。")
            st.session_state.llm_chat_messages.extend(
                [
                    {"role": "user", "content": pending_prompt, "time": datetime.now().strftime("%H:%M")},
                    {
                        "role": "assistant",
                        "content": answer,
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "company": company_display,
                        "source_note": source_note,
                        "time": datetime.now().strftime("%H:%M"),
                    },
                ]
            )
        except Exception as error:
            error_text = f"本轮回答失败：{type(error).__name__}: {error}"
            stream_placeholder.error(error_text)
            st.session_state.llm_last_status = error_text
        finally:
            st.session_state.llm_pending_prompt = ""
        st.rerun()


def render_research_body(meta: dict, stage: str) -> None:
    st.markdown(
        f"<div class='page-kicker'>ACTIVE RESEARCH</div><div class='page-title' style='font-size:24px;margin-top:4px;'>"
        f"{escape(str(meta.get('title') or '未命名研究'))}</div>"
        f"<div class='page-subtitle'>{escape(str(meta.get('updated_at') or ''))}</div>",
        unsafe_allow_html=True,
    )
    if stage == "screen":
        render_screen_panel()
        if st.button("开始快速提炼", type="primary", **STRETCH):
            persist_screen()
            st.session_state.pending_quick = True
            st.rerun()
    else:
        with st.expander("调整筛选名单", expanded=False):
            render_screen_panel()
            if st.button("开始快速提炼", type="primary", **STRETCH):
                persist_screen()
                st.session_state.pending_quick = True
                st.rerun()
    if stage == "quick":
        if st.session_state.get("pending_quick"):
            st.session_state.pending_quick = False
            if run_quick_pass():
                st.rerun()
    if stage in {"quick", "deep"} and st.session_state.get("summaries"):
        if st.session_state.get("pending_deep"):
            st.session_state.pending_deep = False
            start_deep_background()
        left, right = st.columns([1, 1.45], gap="large")
        with left:
            st.markdown('<div class="research-cards-anchor"></div>', unsafe_allow_html=True)
            with st.container(height=760, border=False, key="research_cards_scroll"):
                render_quick_panel(workspace=True)
        with right:
            st.markdown('<div class="research-reports-anchor"></div>', unsafe_allow_html=True)
            render_report_workspace()
            if st.session_state.get("llm_drawer_open"):
                with st.expander("研究助手", expanded=True):
                    render_llm_panel()
    st.caption("研究结论附证据与研究边界；缺失材料会明确标注。输出仅供研究辅助。")


@native_st.fragment(run_every="3s")
def render_report_workspace() -> None:
    # Only the report pane refreshes; card selection and scroll position persist.
    configure_translation()
    job = current_job()
    account, research_id = current_account(), st.session_state.research_id
    if job:
        st.session_state.comments = research_store.load_comments(ROOT, account, research_id)
        st.session_state.screenings = research_store.load_screenings(ROOT, account, research_id)
    phase_labels = {
        "queued": ("等待开始", "Queued"), "source": ("核验与下载财报", "Verifying and downloading the filing"),
        "evidence": ("准备风险核验证据", "Preparing risk evidence"),
        "deep": ("生成深度研究与语言核验", "Writing and validating the research brief"),
        "risk": ("生成风险核验与语言校验", "Writing and validating the risk review"),
        "done": ("本轮已保存", "Results saved"),
    }
    if job:
        elapsed = max(0, int(float(job.get("finished_at") or time.time()) - float(job.get("started_at") or time.time())))
        label = phase_labels.get(job.get("phase"), ("任务已中断，可继续", "Job interrupted; resume available"))[int(english())]
        suffix = f" · {job.get('ticker', '')} · {elapsed // 60}:{elapsed % 60:02d}"
        if active_job(job):
            st.progress(min(.95, int(job.get("completed") or 0) / max(1, int(job.get("total") or 1))), text=label + suffix)
            st.caption("任务在后台运行，离开后可从研究历史继续查看。")
        elif job.get("status") == "completed":
            st.success(label + suffix)
        else:
            st.warning("本轮进度已保存，可继续未完成的报告。")
        events = job.get("events") or []
        if events:
            rows = [{("Ticker" if english() else "证券代码"): event["ticker"],
                     ("Stage" if english() else "阶段"): phase_labels.get(event["phase"], (event["phase"], event["phase"]))[int(english())],
                     ("Seconds" if english() else "用时（秒）"): event["seconds"]} for event in events]
            with st.expander("生成用时", expanded=False):
                native_st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    if not st.session_state.comments and not st.session_state.screenings:
        st.subheader("研究报告工作区")
        st.info("从左侧勾选公司并生成报告；已完成的点评和排雷报告会显示在这里。")
    render_comments_panel()


def render_research() -> None:
    research_id = st.session_state.research_id
    meta = research_store.load_meta(ROOT, current_account(), research_id) if research_id else {}
    st.markdown('<div class="page-mode-research"></div>', unsafe_allow_html=True)
    stage = str(meta.get("stage") or "screen")
    if st.session_state.get("pending_quick"):
        stage = "quick"
    elif st.session_state.get("pending_deep") or st.session_state.get("comments") or st.session_state.get("screenings"):
        stage = "deep"
    elif st.session_state.get("summaries"):
        stage = "quick"
    render_stage_header(stage)
    render_llm_toggle()
    if st.session_state.get("llm_drawer_open") and stage == "screen":
        st.markdown('<div class="llm-split-open"></div>', unsafe_allow_html=True)
        main_col, chat_col = st.columns([2, 1], gap="large")
        with main_col:
            render_research_body(meta, stage)
        with chat_col:
            render_llm_panel()
    else:
        render_research_body(meta, stage)


if st.session_state.view == "research" and st.session_state.research_id:
    render_research()
else:
    render_history()
