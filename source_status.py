"""Source availability is independent of generation and presentation language."""
from __future__ import annotations


def source_unavailable(item: dict) -> bool:
    canonical = item.get('canonical_result') or item
    return bool(canonical.get('source_unavailable') or (
        not canonical.get('matched_pdf') and not canonical.get('matched_pdf_path')
        and canonical.get('headline') in {'未匹配到全文', 'Report PDF not found'}))


def source_failure_message(item: dict, *, is_english: bool) -> str:
    canonical = item.get('canonical_result') or item
    if not is_english:
        reason = canonical.get('message') or canonical.get('summary') or '没有找到 PDF 文件'
        return f"未取得正式财报全文，尚未运行摘要分析。{reason} 请核对报告期年份/类型，或稍后重试、上传原版 PDF。"
    period = {'一季度报告': 'First Quarter Report', '半年度报告': 'Interim Report',
              '三季度报告': 'Third Quarter Report', '年度报告': 'Annual Report'}.get(canonical.get('report_type'), 'report')
    return (f"The official {canonical.get('report_year', '')} {period} PDF is unavailable for "
            f"{canonical.get('stock_code', '')}. Summary analysis has not run. Check the reporting year/type, "
            "retry the source, or upload the original PDF. An older period is never substituted automatically.")


def localize_source_failure(item: dict) -> dict:
    """Source failures must remain actionable even when translation is offline."""
    result = dict(item)
    result.update(headline='Report PDF not found', driver='Summary analysis has not run',
                  business='', summary=source_failure_message(item, is_english=True),
                  substance='No analysis: official report PDF unavailable.',
                  screening_note='Risk screening has not run because the source PDF is unavailable.',
                  message=source_failure_message(item, is_english=True), selected=False,
                  language='en', canonical_result=dict(item))
    return result


def download_failure_for(records, stock_code: str) -> str:
    return '; '.join(str(record.message) for record in records
                     if str(record.stock_code) == str(stock_code) and not record.pdf_path)
