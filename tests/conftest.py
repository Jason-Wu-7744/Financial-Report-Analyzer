"""Isolated test account; no deployment credentials or paid model calls."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def isolated_test_accounts(monkeypatch):
    monkeypatch.setenv("RESEARCH_ACCOUNTS_JSON", json.dumps([
        ["test-reviewer", "test-only-not-a-live-password", "Test Reviewer"]
    ]))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
