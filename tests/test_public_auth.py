import json

import auth


def test_no_account_is_enabled_without_configuration(monkeypatch):
    monkeypatch.delenv("RESEARCH_ACCOUNTS_JSON", raising=False)
    assert auth.authenticate("demo1", "arbitrary-input") is None
    assert auth.configured_accounts() == ()


def test_explicit_account_supports_unicode_password_and_username_normalization(monkeypatch):
    monkeypatch.setenv("RESEARCH_ACCOUNTS_JSON", json.dumps([["Reviewer", "test-密码-42", "Reviewer"]]))
    assert auth.authenticate(" REVIEWER ", "test-密码-42") == {"username": "reviewer", "display_name": "Reviewer"}
    assert auth.authenticate("reviewer", "incorrect") is None


def test_invalid_or_duplicate_config_fails_closed(monkeypatch):
    for value in ["not json", "{}", '[["name", "", "Name"]]',
                  '[["same", "one", "A"], ["SAME", "two", "B"]]']:
        monkeypatch.setenv("RESEARCH_ACCOUNTS_JSON", value)
        assert auth.configured_accounts() == ()
