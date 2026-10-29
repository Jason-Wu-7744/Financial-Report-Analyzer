"""Session-local chat history, scoped to the selected filing workspace.

The UI owns rendering and model calls. These helpers only move plain session
state, so opening a drawer or choosing another company cannot erase a chat or
attach it to a different account, study, language, or issuer.
"""
from __future__ import annotations

from collections.abc import MutableMapping
from copy import deepcopy
import json
from typing import Any


_CONVERSATIONS = "llm_chat_conversations"
_ACTIVE_SCOPE = "llm_chat_scope"
_MESSAGE_LIMIT = 80


def chat_scope(state: MutableMapping[str, Any], company_key: str = "") -> str:
    """Return an unambiguous identifier with no credentials or report content."""
    return json.dumps([
        str(state.get("user_account") or "").strip(),
        str(state.get("research_id") or "").strip(),
        "en" if state.get("ui_language") == "en" else "zh",
        str(company_key or "").strip(),
    ], ensure_ascii=False, separators=(",", ":"))


def _messages(value: Any) -> list[dict[str, Any]]:
    return deepcopy([item for item in value if isinstance(item, dict)][-_MESSAGE_LIMIT:]) if isinstance(value, list) else []


def save_chat(state: MutableMapping[str, Any], messages: list[dict[str, Any]] | None = None) -> None:
    """Checkpoint the visible conversation under its original tracked scope.

    The stored scope is deliberately used before the current research/language
    fields: those fields can already have changed during a navigation callback.
    """
    if messages is not None:
        state["llm_chat_messages"] = _messages(messages)
    scope = state.get(_ACTIVE_SCOPE) or chat_scope(state, state.get("llm_active_company_key") or "")
    conversations = dict(state.get(_CONVERSATIONS) or {})
    conversations[scope] = {
        "messages": _messages(state.get("llm_chat_messages")),
        "last_status": str(state.get("llm_last_status") or ""),
    }
    state[_CONVERSATIONS] = conversations
    state[_ACTIVE_SCOPE] = scope


def select_chat_company(state: MutableMapping[str, Any], company_key: str = "") -> None:
    """Open an issuer's chat, saving the old one before changing any identity.

    Repeated clicks on the same card preserve its transcript. A switch restores
    only the target scope's history and clears transient work from the previous
    scope; pending questions must never run against the newly selected issuer.
    """
    company = str(company_key or "").strip()
    target = chat_scope(state, company)
    previous = state.get(_ACTIVE_SCOPE) or chat_scope(state, state.get("llm_active_company_key") or "")
    save_chat(state)
    if previous != target:
        saved = (state.get(_CONVERSATIONS) or {}).get(target) or {}
        state["llm_chat_messages"] = _messages(saved.get("messages"))
        state["llm_last_status"] = str(saved.get("last_status") or "")
        state["llm_pending_prompt"] = ""
        state["llm_chat_prefill"] = ""
        state["llm_ignore_prompt_once"] = ""
    state[_ACTIVE_SCOPE] = target
    state["llm_active_company_key"] = company
    state["llm_drawer_open"] = True


def open_chat(state: MutableMapping[str, Any]) -> None:
    """Reopen the current study's chat without resuming another study's issuer."""
    company = str(state.get("llm_active_company_key") or "").strip()
    tracked = state.get(_ACTIVE_SCOPE)
    if tracked:
        try:
            tracked_base = json.loads(tracked)[:3]
        except (TypeError, ValueError):
            tracked_base = []
        if tracked_base != json.loads(chat_scope(state, company))[:3]:
            company = ""
    select_chat_company(state, company)


def close_chat(state: MutableMapping[str, Any]) -> None:
    """Hide the drawer while retaining the selected company and conversation."""
    save_chat(state)
    state["llm_drawer_open"] = False

