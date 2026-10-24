"""Offline presentation labels for summary cards.

The summary's ``status`` describes extraction/generation checks. It must never
be presented as the outcome of the independent preliminary risk screening.
"""
from __future__ import annotations

from html import escape


def summary_status_label(status: str, *, is_english: bool) -> str:
    value = str(status or "").strip()
    if value in {"通过", "完成", "Pass", "Passed", "Complete", "Completed"}:
        return "Summary ready" if is_english else "摘要已生成"
    if value in {"需复核", "Needs Review", "Needs review", "Review required"}:
        return "Summary needs review" if is_english else "摘要需复核"
    if value in {"失败", "Failed", "Failure"}:
        return "Summary failed" if is_english else "摘要生成失败"
    if value in {"", "待看", "未完成", "Not completed"}:
        return "Summary pending" if is_english else "摘要待完成"
    return "Summary status unknown" if is_english else "摘要状态待确认"


def summary_status_badge_html(status: str, *, is_english: bool) -> str:
    explanation = (
        "Summary generation and source checks. Preliminary risk screening is shown below."
        if is_english else "此状态仅指摘要生成与来源检查；初步风险筛查见下方。"
    )
    return (
        "<span class='pick-tag priority' title='" + escape(explanation, quote=True) + "'>"
        + escape(summary_status_label(status, is_english=is_english)) + "</span>"
    )


def preliminary_risk_html(conclusion: str, hits: list[str], note: str, *, is_english: bool) -> str:
    """Render the saved quick-screen result, without inferring a new decision."""
    value = str(conclusion or "未完成")
    excluded = value in {"淘汰", "暂定淘汰", "Exclude", "Preliminary Exclude"}
    passed = value in {"通过", "暂定通过", "Pass", "Preliminary Pass"}
    klass = "risk-kill" if excluded else ("risk-pass" if passed else "risk-gap")
    labels = {
        "淘汰": "Preliminary Exclude", "暂定淘汰": "Preliminary Exclude",
        "通过": "Preliminary Pass", "暂定通过": "Preliminary Pass",
        "待补证": "Preliminary Evidence Gap", "暂定待补证": "Preliminary Evidence Gap",
        "未完成": "Not completed",
    }
    label = labels.get(value, value) if is_english else value
    heading = "Preliminary Risk Screening" if is_english else "初步风险筛查"
    hit_label = "Triggers " if is_english else "命中 "
    separator = ", " if is_english else "、"
    hit_html = (
        f"<span class='pick-tag {klass}'>{hit_label}{escape(separator.join(str(hit) for hit in hits))}</span>"
        if hits else ""
    )
    return (
        f"<div class='pick-row'><div class='pick-label'>{heading}</div>"
        f"<div class='pick-tags'><span class='pick-tag {klass}'>{escape(label)}</span>{hit_html}</div>"
        f"<div class='pick-body'>{escape(str(note or '').strip() or '—')}</div></div>"
    )
