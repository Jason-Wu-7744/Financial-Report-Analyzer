"""Trace consolidated/parent statement boundaries, including mixed-page continuations."""
from __future__ import annotations

from decimal import Decimal
import re
import unicodedata


def _text(value):
    return unicodedata.normalize("NFKC", str(value or ""))


def statement_segments(pages):
    scope, kind, title_page, unit = "unknown", "unknown", None, ""
    segments = []
    for page in sorted(pages, key=lambda item: item.page):
        lines = _text(page.text).splitlines()
        start = 0
        for index, line in enumerate(lines):
            stripped = re.sub(r"^[\s\d一二三四五六七八九十、.)]+", "", line).strip()
            match = re.fullmatch(r"(合并|合併|綜合|综合|母公司)(资产负债|資產負債|财务状况|財務狀況|利润|利潤|损益|損益|收益|现金流量|現金流量)表(?:[（(]续[）)])?", stripped)
            if match:
                if index > start:
                    segments.append({"page": page.page, "start": start, "end": index, "scope": scope, "kind": kind, "title_page": title_page, "unit": unit, "lines": lines[start:index]})
                scope = "parent_only" if match.group(1) == "母公司" else "consolidated"
                kind = "income" if match.group(2) in {"利润", "利潤", "损益", "損益", "收益"} else ("cashflow" if "流量" in match.group(2) else "balance")
                title_page, start = page.page, index
            if re.search(r"(?:财务报表附注|財務報表附註|財務報表附注|财务报表项目注释)", stripped) and len(stripped) < 50:
                if index > start:
                    segments.append({"page": page.page, "start": start, "end": index, "scope": scope, "kind": kind, "title_page": title_page, "unit": unit, "lines": lines[start:index]})
                scope, kind, title_page, start = "unknown", "notes", page.page, index
            found_unit = re.search(r"单位\s*[:：]\s*(亿元|百万元|万元|千元|元)", stripped)
            if found_unit:
                unit = found_unit.group(1)
        if len(lines) > start:
            segments.append({"page": page.page, "start": start, "end": len(lines), "scope": scope, "kind": kind, "title_page": title_page, "unit": unit, "lines": lines[start:]})
    return segments


def statement_scope_context(pages, selected_pages=None, max_chars=7000):
    wanted = {page.page for page in selected_pages} if selected_pages is not None else {page.page for page in pages}
    lines = ["【报表主体与续页边界：程序仅识别原文标题，不能将母公司报表与合并报表拼接】",
             "同一PDF页可能先为母公司利润表续页，页底才出现合并现金流量表标题；页底标题不追溯改变页上方数字的口径。",
             "合并经营现金流只能与合并净利润比较；归母净利润、合并净利润、母公司单体净利润与综合收益分别列示。"]
    for segment in statement_segments(pages):
        if segment["page"] not in wanted or segment["scope"] == "unknown":
            continue
        lines.append(f"PDF第{segment['page']}页第{segment['start']+1}—{segment['end']}行："
                     f"{'母公司单体' if segment['scope']=='parent_only' else '合并'}{segment['kind']}，"
                     f"标题承接PDF第{segment['title_page']}页，单位{segment['unit'] or '按原表确认'}。")
    return "\n".join(lines)[:max_chars]


def income_records(pages):
    records = []
    for segment in statement_segments(pages):
        if segment["kind"] != "income":
            continue
        lines = segment["lines"]
        for index, line in enumerate(lines):
            if not re.search(r"(?:净利润|淨利潤|营业利润|營業利潤|利润总额|利潤總額|资产减值损失|資產減值損失)", line):
                continue
            if any(word in line for word in ("归属于", "歸屬於", "持续经营", "持續經營", "终止经营", "終止經營")):
                continue
            metric = next((name for name in ("营业利润", "利润总额", "资产减值损失", "净利润") if name in line), "净利润")
            row = "\n".join(lines[index:index+4])
            # Avoid the ordinal 五/四 prefix and include the next wrapped amount line.
            numbers = re.findall(r"(?<![\d.])-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\d.])-?\d{4,}(?:\.\d+)?", row)
            if numbers:
                records.append({"page": segment["page"], "scope": segment["scope"], "kind": metric,
                                "unit": segment["unit"], "current": Decimal(numbers[0].replace(",", "")), "row": row})
    return records


def financial_statement_scope_issues(markdown, pages):
    """Detect cited parent-only figures presented as generic/consolidated results."""
    issues = []
    records = [record for record in income_records(pages) if record["scope"] == "parent_only"]
    scales = {"元": Decimal(1), "千元": Decimal(1000), "万元": Decimal(10000), "百万元": Decimal(1000000), "亿元": Decimal(100000000)}
    for paragraph in re.split(r"\n\s*\n|(?=^\|)", markdown, flags=re.M):
        refs = {int(number) for citation in re.findall(r"\[本期PDF第([^\]]+)\]", paragraph) for number in re.findall(r"\d+", citation)}
        if not refs:
            continue
        for record in records:
            if record["page"] not in refs or record["kind"] not in paragraph:
                continue
            if re.search(r"母公司(?:单体|單體|个别|個別)?(?:报表|報表|口径|口徑|净利润|淨利潤|利润|利潤)|parent.only", paragraph, re.I):
                continue
            value = record["current"]
            scale = scales.get(record["unit"], Decimal(1))
            alternatives = {value, value*scale/Decimal(1e8), value*scale/Decimal(1e6)}
            reported = [Decimal(number.replace(",", "")) for number in re.findall(r"(?<![\d.])-?\d+(?:,\d{3})*(?:\.\d+)?(?![\d.])", paragraph)]
            if any(abs(number-alternative) <= Decimal("0.005") for number in reported for alternative in alternatives):
                issue = f"PDF第{record['page']}页{record['kind']}{value}{record['unit']}属于母公司单体，不能作为合并或未限定口径的{record['kind']}引用"
                if issue not in issues:
                    issues.append(issue)
    return issues


def displayed_cash_bridge_issues(markdown):
    """Check explicit addition/subtraction equalities only; never infer inputs.

    This does not certify the source, cash-flow classification, units or any
    undisplayed calculation. Decimal preserves the displayed precision.
    """
    issues = []
    number = r"[+-]?\d+(?:,\d{3})*(?:\.\d+)?"
    term = rf"(?:[A-Za-z\u3400-\u9fff\s]*)(?:\(?\s*{number}\s*\)?)(?:[A-Za-z\u3400-\u9fff]*)"
    expression = rf"{term}(?:\s*[+\-]\s*{term}){{2,}}\s*=\s*(?:[A-Za-z\u3400-\u9fff\s]*)({number})"
    for paragraph in re.split(r"\n\s*\n|(?=^\|)", _text(markdown), flags=re.M):
        if not re.search(r"现金桥|現金橋|cash bridge", paragraph, re.I):
            continue
        for match in re.finditer(expression, paragraph):
            equation = match.group(0)
            lhs, rhs = equation.rsplit("=", 1)
            # Remove descriptive labels, whitespace and grouping brackets only.
            clean = re.sub(r"[A-Za-z\u3400-\u9fff\s,()]", "", lhs)
            clean = clean.replace("+-", "-").replace("--", "+")
            if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?(?:[+-]\d+(?:\.\d+)?){2,}", clean):
                continue
            actual = sum((Decimal(value) for value in re.findall(r"[+-]?\d+(?:\.\d+)?", clean)), Decimal(0))
            target = Decimal(match.group(1).replace(",", ""))
            difference = actual - target
            if difference:
                zero_claim = re.search(r"差[额額](?:为|為|是|[:：])?\s*0(?:\D|$)|勾稽(?:成立|一致)|reconcil(?:es|ed)|difference\s*(?:is|=|:)\s*zero", paragraph, re.I)
                disclosed = re.search(r"相差|差[额額]|差异|差異|舍入|捨入|rounding|difference|discrepancy", paragraph, re.I)
                if zero_claim or not disclosed:
                    issues.append(f"现金桥显示算式不成立：按列示数计算为{actual}，等号右侧为{target}，差额{difference}；须明确披露差额，不得称零差额或改写原财报数值")
    return issues
