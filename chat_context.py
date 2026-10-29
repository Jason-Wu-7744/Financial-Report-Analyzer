"""Resolve a clicked filing independently of display language and report order."""
from __future__ import annotations

import re


def report_chat_key(item: dict) -> str:
    issuer = str(item.get('stock_code') or item.get('company_name') or '').strip()
    return '|'.join((issuer, str(item.get('report_year') or ''), str(item.get('report_type') or '')))


def resolve_chat_context(items, active_key, message, display_name):
    """Return the exact filing and strip only a recognized issuer mention.

    A plain follow-up retains its clicked filing. An explicit ticker keeps that
    filing when several periods exist for the issuer; an unknown mention never
    clears the selected context or silently chooses a substring match.
    """
    items = [item for item in (items or []) if isinstance(item, dict)]
    active = next((item for item in items if report_chat_key(item) == active_key), None)
    if active is None:
        active = next((item for item in items
                       if active_key and active_key in {str(item.get('stock_code') or ''), str(item.get('company_name') or '')}), None)
    text = str(message or '')
    marker = re.search(r'@', text)
    if marker is None:
        return active or {}, text.strip()
    tail = text[marker.end():]
    matches = []
    for item in items:
        name, code = str(item.get('company_name') or '').strip(), str(item.get('stock_code') or '').strip()
        for alias in {name, code, str(display_name(name, code) or '').strip()} - {''}:
            if not tail.casefold().startswith(alias.casefold()):
                continue
            rest = tail[len(alias):]
            if rest and not (rest[0].isspace() or rest[0] in ',，。.;；:：!?！？'):
                continue
            matches.append((len(alias), item is active, item, alias))
    if not matches:
        return active or {}, text.strip()
    _, _, item, alias = max(matches, key=lambda entry: (entry[0], entry[1]))
    cleaned = (text[:marker.start()] + text[marker.end()+len(alias):]).strip()
    return item, cleaned or text.strip()
