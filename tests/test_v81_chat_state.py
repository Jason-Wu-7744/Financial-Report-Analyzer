"""Conversation continuity and source-scope isolation, with no UI or API."""
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from chat_state import chat_scope, close_chat, open_chat, save_chat, select_chat_company


def session(**overrides):
    return {
        "user_account": "demo1", "research_id": "study1", "ui_language": "en",
        "llm_active_company_key": "", "llm_chat_messages": [],
        "llm_last_status": "", "llm_pending_prompt": "", "llm_chat_prefill": "",
        **overrides,
    }


def conversation(company="000089"):
    return [
        {"role": "user", "content": "What changed?"},
        {"role": "assistant", "content": f"Evidence from {company}.", "company": company},
    ]


def test_card_selection_opens_chat_and_loads_stable_issuer_context():
    state = session()
    select_chat_company(state, "000089")
    assert state["llm_drawer_open"] is True
    assert state["llm_active_company_key"] == "000089"
    assert state["llm_chat_messages"] == []
    assert state["llm_chat_scope"] == chat_scope(state, "000089")


def test_close_reopen_and_repeat_card_click_preserve_the_full_conversation():
    state = session()
    select_chat_company(state, "000089")
    state["llm_chat_messages"] = conversation()
    state["llm_last_status"] = "Source filing loaded"
    close_chat(state)
    assert state["llm_drawer_open"] is False
    assert state["llm_active_company_key"] == "000089"
    open_chat(state)
    select_chat_company(state, "000089")
    assert state["llm_chat_messages"] == conversation()
    assert state["llm_last_status"] == "Source filing loaded"


def test_switching_company_saves_previous_history_and_never_copies_it_to_new_company():
    state = session()
    select_chat_company(state, "000089")
    state["llm_chat_messages"] = conversation()
    state["llm_pending_prompt"] = "Old issuer question"
    state["llm_chat_prefill"] = "@000089 "
    state["llm_ignore_prompt_once"] = "old"
    select_chat_company(state, "000554")
    assert state["llm_chat_messages"] == []
    assert state["llm_pending_prompt"] == state["llm_chat_prefill"] == state["llm_ignore_prompt_once"] == ""
    state["llm_chat_messages"] = conversation("000554")
    select_chat_company(state, "000089")
    assert state["llm_chat_messages"] == conversation()
    select_chat_company(state, "000554")
    assert state["llm_chat_messages"] == conversation("000554")


@pytest.mark.parametrize("field,value", [
    ("user_account", "demo2"), ("research_id", "study2"), ("ui_language", "zh"),
])
def test_account_research_and_language_changes_cannot_reuse_prior_history(field, value):
    state = session()
    select_chat_company(state, "000089")
    state["llm_chat_messages"] = conversation()
    state[field] = value
    select_chat_company(state, "000089")
    assert state["llm_chat_messages"] == []
    state[field] = {"user_account": "demo1", "research_id": "study1", "ui_language": "en"}[field]
    select_chat_company(state, "000089")
    assert state["llm_chat_messages"] == conversation()


def test_open_in_another_research_does_not_silently_select_prior_issuer():
    state = session()
    select_chat_company(state, "000089")
    state["llm_chat_messages"] = conversation()
    close_chat(state)
    state["research_id"] = "study2"
    open_chat(state)
    assert state["llm_active_company_key"] == ""
    assert state["llm_chat_messages"] == []
    state["research_id"] = "study1"
    select_chat_company(state, "000089")
    assert state["llm_chat_messages"] == conversation()


def test_snapshots_are_copies_and_cannot_be_mutated_through_old_or_new_transcript():
    state = session()
    select_chat_company(state, "000089")
    original = conversation()
    save_chat(state, original)
    original[1]["content"] = "Caller mutation"
    assert state["llm_chat_messages"][1]["content"] == "Evidence from 000089."
    state["llm_chat_messages"][1]["content"] = "Visible transcript mutation"
    saved = state["llm_chat_conversations"][chat_scope(state, "000089")]["messages"]
    assert saved[1]["content"] == "Evidence from 000089."


def test_old_untracked_session_history_is_saved_under_its_old_company():
    state = session(llm_active_company_key="000089", llm_chat_messages=conversation())
    select_chat_company(state, "000554")
    assert state["llm_chat_messages"] == []
    select_chat_company(state, "000089")
    assert state["llm_chat_messages"] == conversation()


def test_scope_cannot_collide_when_user_labels_contain_separator_characters():
    first = session(user_account="a|b", research_id="c")
    second = session(user_account="a", research_id="b|c")
    assert chat_scope(first, "000089") != chat_scope(second, "000089")


def test_different_filing_periods_of_the_same_issuer_keep_separate_context_and_history():
    state = session()
    annual = "000089|2025|年度报告"
    quarterly = "000089|2026|三季度报告"
    select_chat_company(state, annual)
    state["llm_chat_messages"] = conversation(annual)
    select_chat_company(state, quarterly)
    assert state["llm_chat_messages"] == []
    assert state["llm_active_company_key"] == quarterly
    state["llm_chat_messages"] = conversation(quarterly)
    select_chat_company(state, annual)
    assert state["llm_chat_messages"] == conversation(annual)
    select_chat_company(state, quarterly)
    assert state["llm_chat_messages"] == conversation(quarterly)
