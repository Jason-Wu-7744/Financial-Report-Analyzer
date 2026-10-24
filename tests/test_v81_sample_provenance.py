import pytest

from sample_provenance import official_filing_url


@pytest.mark.parametrize("url", [
    "https://static.cninfo.com.cn/finalpage/2025-08-13/1224462930.PDF",
    "https://www1.hkexnews.hk/listedco/listconews/sehk/2025/0826/2025082600677_c.pdf",
])
def test_actual_sample_filing_links_are_allowed(url):
    assert official_filing_url(url) == url


@pytest.mark.parametrize("url", [
    "http://static.cninfo.com.cn/filing.pdf",
    "https://static.cninfo.com.cn.evil.example/filing.pdf",
    "https://static.cninfo.com.cn@evil.example/filing.pdf",
    "https://user@static.cninfo.com.cn/filing.pdf",
    "https://www1.hkexnews.hk:8443/filing.pdf",
    "https://static.cninfo.com.cn/filing.pdf?redirect=https://evil.example",
    "https://static.cninfo.com.cn/filing.pdf#javascript:alert(1)",
    "https://static.cninfo.com.cn/filing.pdf) [other](https://evil.example)",
    "https://static.cninfo.com.cn/\nfiling.pdf",
    "javascript:alert(1)",
    None,
])
def test_untrusted_or_non_direct_urls_never_render_as_official_links(url):
    assert official_filing_url(url) == ""
