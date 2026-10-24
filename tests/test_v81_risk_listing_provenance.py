from __future__ import annotations

from zipfile import ZipFile

import pytest

import screening_engine as screening


HSBC_URL = "https://www1.hkexnews.hk/listedco/listconews/sehk/2025/0822/2025082200026_c.pdf"


def hsbc_report():
    raw = {
        "sources": [{"id": "S1", "title": "HSBC 2025 Interim Report", "url": HSBC_URL,
                     "published_at": "2026-10-15"}],
        "checks": [{"id": "C8", "evidence_state": "证据不足", "outcome": "证据不足",
                    "finding": "汇丰控股是长期上市公司，上市已远超2-3年。",
                    "basis": "未取得上市直接引文。[S1]", "source_ids": ["S1"],
                    "evidence_quote": "HSBC Holdings plc 2025 Interim Report", "proof_type": "all_conditions_verified"}],
        "limitations": ["候选页非全文覆盖。", "C8次新股项：未提供IPO日期，但长期上市，标记为通过。"],
    }
    return screening.normalize_report(raw, company_name="匯豐控股", stock_code="00005.HK",
                                     industry="银行", screening_date="2026-10-15")


def test_actual_hsbc_c8_stale_pass_is_removed_from_every_rendered_section(tmp_path):
    data = hsbc_report()
    c8 = next(row for row in data["checks"] if row["id"] == "C8")
    assert c8["evidence_state"] == c8["outcome"] == "证据不足"
    assert "长期上市公司" not in c8["finding"]
    assert "须补证后判断" in c8["finding"]
    assert c8["evidence_quote"] == c8["proof_type"] == ""
    assert data["limitations"][0] == "候选页非全文覆盖。"
    assert sum("C8" in row for row in data["limitations"]) == 1
    assert "保留证据不足" in data["limitations"][-1]
    assert data["meta"]["screening_date"] == "2026-10-15"
    assert data["sources"][0]["published_at"] == "2025-08-22"
    markdown = screening.report_to_markdown(data)
    assert "长期上市公司" not in markdown
    assert "标记为通过。" not in markdown
    assert "发布/报告期：2025-08-22" in markdown
    path, error = screening.try_build_docx(data, tmp_path / "hsbc-risk.docx")
    assert path and not error
    with ZipFile(path) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    assert "长期上市公司" not in xml
    assert "标记为通过。" not in xml
    assert "2025-08-22" in xml and "2026-10-15" in xml


@pytest.mark.parametrize("url,supplied,expected", [
    (HSBC_URL, "2026-10-15", "2025-08-22"),
    (HSBC_URL, "2025-07-30", "2025-08-22"),
    ("https://static.cninfo.com.cn/finalpage/2025-08-13/1224462930.PDF", "", "2025-08-13"),
    ("https://example.com/2025/0822/2025082200026_c.pdf", "", "未核实"),
    ("https://www1.hkexnews.hk/listedco/listconews/sehk/2025/0821/2025082200026_c.pdf", "", "未核实"),
    ("https://issuer.example/report.pdf", "2025-08-22", "2025-08-22"),
    ("https://issuer.example/report.pdf", "", "未核实"),
    ("https://issuer.example/report.pdf", "not a date", "未核实"),
])
def test_source_publication_date_is_document_specific(url, supplied, expected):
    assert screening.source_publication_date(url, supplied) == expected


def test_verified_listing_evidence_keeps_its_finding_and_limitation():
    checks = [{"id": "C8", "evidence_state": "已核验未触发", "finding": "股份自2004年6月16日上市。"}]
    limits = ["C8已按原文上市日期核验。"]
    assert screening.align_listing_gap(checks, limits) == limits
    assert checks[0]["finding"] == "股份自2004年6月16日上市。"
