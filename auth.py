"""Environment-configured access gate; not a production identity provider."""
from __future__ import annotations

import hmac
import json
import os
from typing import Any


def configured_accounts() -> tuple[tuple[str, str, str], ...]:
    """Reject malformed configurations without logging credentials."""
    try:
        rows = json.loads(os.getenv("RESEARCH_ACCOUNTS_JSON", "[]"))
        if not isinstance(rows, list):
            return ()
        result = []
        seen = set()
        for row in rows:
            if not isinstance(row, list) or len(row) != 3:
                return ()
            if not all(isinstance(value, str) and value.strip() for value in row):
                return ()
            username, password, display_name = row
            username = username.strip().lower()
            if username in seen:
                return ()
            seen.add(username)
            result.append((username, password, display_name.strip()))
        return tuple(result)
    except (ValueError, TypeError):
        return ()


def authenticate(username: str, password: str) -> dict[str, Any] | None:
    for account, stored, display_name in configured_accounts():
        if username.strip().lower() == account and hmac.compare_digest(
            password.encode("utf-8"), stored.encode("utf-8")
        ):
            return {"username": account, "display_name": display_name}
    return None
