"""Allow only direct official filing URLs for read-only sample provenance."""
from __future__ import annotations

import re
from urllib.parse import urlsplit


def official_filing_url(value: object) -> str:
    if not isinstance(value, str):
        return ""
    url = value.strip()
    if re.search(r"[\s\x00-\x1f\x7f]", url):
        return ""
    try:
        parts = urlsplit(url)
        if (parts.scheme != "https" or
                parts.hostname not in {"static.cninfo.com.cn", "www1.hkexnews.hk"} or
                parts.username is not None or parts.password is not None or
                parts.port not in {None, 443} or parts.query or parts.fragment or
                not re.fullmatch(r"/[A-Za-z0-9/_\-.]+\.pdf", parts.path, re.I)):
            return ""
    except ValueError:
        return ""
    return url
