"""Hong Kong filing evidence selection and accounting safeguards.

This module reads disclosed text only. It never substitutes market data or
currency conversions for an issuer's own financial statements.
"""
from __future__ import annotations

import re
import math
import unicodedata
from typing import Any


HK_EXTRACTION_RULES = """港股专用取证规则：
先识别原报告的报告期间、合并/綜合口径、币种和单位，再提取数字；保留原币，不换算汇率。
USD/US$/美元、HKD/HK$/港元、RMB/CNY/人民币不可混用。million=百万=0.01亿；billion=十亿=10亿；thousand/'000=千=0.00001亿。
同页多币种/单位必须逐表识别；找不到单位时返回null并说明需要哪张表，不沿用其他表的单位。
优先以正式年报/中期报告的综合损益表、综合现金流量表、综合财务状况表和附注交叉核验，摘要仅用于定位。
报告期利润、税前利润、非控股权益利润均不得代替股东应占利润；loss attributable to owners应保留负号；括号金额为负值。
经调整、non-GAAP、underlying利润是替代业绩指标，不等于A股扣非净利润。只有发行人明确披露该指标及口径才填写，并保留调整项目。
银行优先总经营收入/净经营收入、净利息收入、净息差、减值/信用损失、资本充足率、贷款/存款及流动性；保险优先保险服务结果、合同服务边际、偿付能力及投资结果。
不得对银行/保险机械应用工业企业的净利率、应收/收入、资产负债率和自由现金流红线。不适用必须解释行业原因，缺资料必须标记证据不足。
同比仅比较相同期间、币种、会计口径；中期对上年中期，期末资产对上年末。前期重述采用重述数并注明。
数字均应带PDF页码、原始科目、原始单位及期间；引用页码必须来自实际提供的候选页。
"""

TOPICS: dict[str, tuple[str, ...]] = {
    "highlights": ("財務摘要", "财务摘要", "業績摘要", "财务概要", "financialhighlights", "financialsummary"),
    "income": ("綜合損益表", "综合损益表", "綜合收益表", "综合收益表", "綜合利潤表", "consolidatedincomestatement", "consolidatedstatementofprofitorloss", "consolidatedstatementofincome"),
    "cashflow": ("綜合現金流量表", "综合现金流量表", "現金流量表", "现金流量表", "consolidatedcashflow", "consolidatedstatementofcashflows", "netcashfromoperating"),
    "balance": ("綜合財務狀況表", "综合财务状况表", "綜合資產負債表", "综合资产负债表", "consolidatedstatementoffinancialposition", "consolidatedbalancesheet"),
    "segments": ("分部資料", "分部资料", "分部業績", "分部业绩", "segmentinformation", "segmentresults", "operatingsegments"),
    "credit": ("信貸風險", "信贷风险", "預期信貸虧損", "预期信用损失", "信用減值", "creditrisk", "expectedcreditloss", "impairmentcharges", "capitaladequacy", "資本充足", "资本充足", "淨息差", "净息差", "netinterestmargin"),
    "insurance": ("保險服務", "保险服务", "合同服務邊際", "合同服务边际", "insuranceserviceresult", "contractualservicemargin", "solvencyratio", "償付能力", "偿付能力"),
    "notes": ("收入確認", "收入确认", "revenuefromcontracts", "貿易應收", "贸易应收", "tradereceivables", "借貸", "借贷", "borrowings", "關聯方", "关联方", "relatedpart", "減值", "减值", "impairment", "經調整", "经调整", "non-gaap"),
}


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(text or ""))).lower()


def page_topics(text: str) -> set[str]:
    compact = _compact(text)
    return {topic for topic, terms in TOPICS.items() if any(term in compact for term in terms)}


def _page_score(page: Any, topic: str) -> int:
    text = str(page.text or "")
    compact = _compact(text)
    hits = sum(term in compact for term in TOPICS[topic])
    numbers = len(re.findall(r"\(?-?\d[\d,]*(?:\.\d+)?\)?", text))
    toc = any(word in compact[:100] for word in ("目錄", "目录", "contents"))
    # An actual statement page has amounts, not just a title in the contents.
    return hits * 25 + min(numbers, 40) * 2 - (180 if toc else 0)


def select_hk_financial_pages(pages: list[Any], max_pages: int = 14, max_chars: int = 65000) -> list[Any]:
    """Select different statements before allowing repeated highlights to crowd them out.

    Return original page objects so engine callers retain PDF numbering and text.
    If one page exceeds the budget it is still kept intact when it is the sole
    selected page; the caller can chunk it with explicit boundary markers.
    """
    if max_pages <= 0 or max_chars <= 0:
        return []
    usable = [page for page in pages if str(page.text or "").strip()]
    by_number = {page.page: page for page in usable}
    selected: list[Any] = []
    seen: set[int] = set()
    budget = 0

    def add(page: Any) -> None:
        nonlocal budget
        if page.page in seen or len(selected) >= max_pages:
            return
        if any(word in _compact(page.text)[:100] for word in ("目錄", "目录", "contents")):
            return
        if selected and budget + len(page.text) > max_chars:
            return
        seen.add(page.page)
        selected.append(page)
        budget += len(page.text)

    anchors: list[Any] = []
    for topic in TOPICS:
        candidates = [page for page in usable if topic in page_topics(page.text)]
        if candidates:
            best = max(candidates, key=lambda page: (_page_score(page, topic), -page.page))
            if _page_score(best, topic) > 0:
                anchors.append(best)
                add(best)
    # Statement headers/units and attribution lines often continue on next page.
    for anchor in anchors:
        for number in (anchor.page + 1, anchor.page - 1):
            if number in by_number:
                add(by_number[number])
    if not selected:
        for page in usable[:max_pages]:
            add(page)
    return sorted(selected, key=lambda page: page.page)


HK_OPERATING_HEADINGS = (
    "financialreview", "financialperformance", "financialandoperatingreview",
    "financialandoperatinghighlights", "reviewoffinancialperformance", "performancereview",
    "operatingperformance", "reviewofoperations", "operatingreview", "businessreview",
    "managementdiscussionandanalysis", "management'sdiscussionandanalysis",
    "management’sdiscussionandanalysis", "chiefexecutive'sreview", "chiefexecutive’sreview",
    "財務回顧", "财务回顾", "財務表現", "财务表现", "財務業績", "财务业绩",
    "業務回顧", "业务回顾", "經營回顧", "经营回顾", "經營業績", "经营业绩",
    "管理層討論與分析", "管理层讨论与分析", "管理層討論及分析", "管理层讨论及分析",
    "業績回顧", "业绩回顾", "主席報告", "主席报告", "董事長報告", "董事长报告",
)
HK_OPERATING_METRICS = (
    "revenue", "turnover", "profitbeforetax", "profitaftertax", "profitattributable",
    "netinterestincome", "netinterestmargin", "netfeeincome", "feeandcommissionincome",
    "operatingexpenses", "operatingprofit", "costtoincomeratio", "cost-to-incomeratio",
    "gainondisposal", "gainsondisposal", "disposalof", "non-recurring", "one-off",
    "impairmentcharge", "expectedcreditloss", "netinsurance", "insuranceserviceresult",
    "收益", "營業額", "营业额", "收入", "除稅前溢利", "除税前利润", "股東應佔", "股东应占",
    "淨利息收益", "净利息收益", "淨利息收入", "净利息收入", "淨息差", "净息差",
    "手續費收入", "手续费收入", "營業支出", "营业支出", "營運支出", "运营支出",
    "出售收益", "出售所得", "出售業務", "出售业务", "一次性", "非經常", "非经常",
)
HK_OPERATING_CAUSES = (
    "drivenby", "mainlydue", "primarilydue", "largelydue", "reflecting", "reflected",
    "asaresultof", "benefitedfrom", "partlyoffset", "impactedby", "attributableto",
    "increasedby", "decreasedby", "higher", "lower", "growth", "decline",
    "主要由於", "主要由于", "主要因", "主要受", "反映", "受惠於", "受惠于",
    "帶動", "带动", "抵銷", "抵销", "增長", "增长", "減少", "减少", "下降",
)
HK_PURE_RISK_HEADINGS = (
    "riskmanagement", "creditriskexposure", "creditriskmanagement", "marketrisk",
    "tradingportfolios", "tradingportfolio", "valueatrisk", "value-at-risk", "riskweightedassets",
    "風險管理", "风险管理", "信貸風險敞口", "信贷风险敞口", "信貸風險承擔", "信贷风险承担",
    "交易組合", "交易组合", "市場風險", "市场风险", "風險加權資產", "风险加权资产",
)


def _operating_navigation(text: str) -> bool:
    compact = _compact(text)
    if any(word in compact[:120] for word in ("目錄", "目录", "contents")):
        return True
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    page_links = sum(bool(re.search(r"(?:\.{2,}|…|\s)\s*\d{1,3}\s*$", line)) for line in lines)
    return len(lines) >= 8 and page_links / len(lines) > 0.65 and len(compact) < 2500


def hk_operating_page_score(text: str) -> int:
    """Rank narrative explanations, not similarly worded risk exposure notes."""
    if _operating_navigation(text):
        return -1000
    compact = _compact(text)
    head = compact[:700]
    heading_hits = sum(term in head for term in HK_OPERATING_HEADINGS)
    narrative_hits = sum(term in compact for term in HK_OPERATING_HEADINGS)
    metrics = sum(term in compact for term in HK_OPERATING_METRICS)
    causes = sum(min(compact.count(term), 3) for term in HK_OPERATING_CAUSES)
    risk_heads = sum(term in head for term in HK_PURE_RISK_HEADINGS)
    risk_mentions = sum(term in compact for term in HK_PURE_RISK_HEADINGS)
    # Bank performance discussions naturally mention credit losses. Penalize
    # actual risk-management/exposure headings, not every mention of credit risk.
    score = heading_hits * 65 + narrative_hits * 15 + min(metrics, 12) * 9 + min(causes, 18) * 5
    score -= risk_heads * (75 if heading_hits else 160)
    if not heading_hits:
        score -= risk_mentions * 18
    # Pure statements cannot explain an earnings driver on their own.
    if page_topics(text) & {"income", "balance", "cashflow"} and causes < 2 and not heading_hits:
        score -= 80
    if len(compact) < 250:
        score -= 40
    return score


def select_hk_operating_pages(pages: list[Any], max_pages: int = 5, max_chars: int = 12000) -> list[Any]:
    """Return intact source pages focused on operating and financial explanations.

    Original objects/text/PDF numbering are retained. At least the strongest
    available narrative anchor is selected; adjacent continuation pages compete
    with other explanations instead of displacing them indiscriminately.
    """
    if max_pages <= 0 or max_chars <= 0:
        return []
    usable = [page for page in pages if str(page.text or "").strip() and not _operating_navigation(page.text)]
    ranked = sorted(usable, key=lambda page: (hk_operating_page_score(page.text), -page.page), reverse=True)
    good = [page for page in ranked if hk_operating_page_score(page.text) > 20]
    by_number = {page.page: page for page in usable}
    selected: list[Any] = []
    seen: set[int] = set()
    used_chars = 0

    def add(page: Any) -> None:
        nonlocal used_chars
        if page.page in seen or len(selected) >= max_pages:
            return
        if used_chars + len(page.text) > max_chars:
            return
        selected.append(page)
        seen.add(page.page)
        used_chars += len(page.text)

    # Select more than one narrative anchor before filling continuation pages.
    for page in good[:max_pages]:
        add(page)
    for anchor in good[:2]:
        for number in (anchor.page + 1, anchor.page - 1):
            page = by_number.get(number)
            if page and hk_operating_page_score(page.text) > 20:
                add(page)
    if not selected:
        for page in ranked:
            add(page)
            if selected:
                break
    return sorted(selected, key=lambda page: page.page)


def hk_accounting_context(pages: list[Any], company_name: str = "", industry: str = "") -> str:
    selected = select_hk_financial_pages(pages, max_pages=14)
    text = "\n".join(str(page.text or "") for page in selected)
    currencies = []
    for code, pattern in (
        ("USD", r"US\$|USD|美元|United States dollars|US dollars"),
        ("HKD", r"HK\$|HKD|港元|港幣|港币|Hong Kong dollars"),
        ("CNY", r"RMB|CNY|人民幣|人民币|Renminbi"),
    ):
        if re.search(pattern, text, re.I):
            currencies.append(code)
    identity = f"{company_name} {industry}".lower()
    sector = "银行" if re.search(r"銀行|银行|bank|hsbc|匯豐|汇丰|滙豐", identity) else (
        "保险" if re.search(r"保險|保险|insurance|assurance|aia", identity) else "按实际业务识别行业"
    )
    topics = sorted({topic for page in selected for topic in page_topics(page.text)})
    return (
        f"港股取证范围：PDF页码 {','.join(str(page.page) for page in selected) or '无'}；"
        f"识别币种线索 {','.join(currencies) or '未确认'}（多币种须逐表核实）；"
        f"行业线索：{sector}；已定位主题 {','.join(topics) or '无'}。\n" + HK_EXTRACTION_RULES
    )


def compact_risk_evidence(text: str, max_chars: int = 24000) -> str:
    """Retain diverse original excerpts across a long filing, with page provenance.

    No synthesized numbers: text is sliced verbatim and omitted content is
    explicitly marked. The resulting digest cannot assert whole-report coverage.
    """
    text = str(text or "").strip()
    if len(text) <= max_chars:
        return text
    blocks = re.split(r"(?=^=+\s*PDF第\d+页\s*=+)", text, flags=re.M)
    blocks = [block.strip() for block in blocks if block.strip()]
    if len(blocks) < 2:
        blocks = [text[index:index + 3500] for index in range(0, len(text), 3500)]
    # Round-robin topical anchors include later cash flow/debt/risk notes.
    retained: list[int] = []
    for topic in ("income", "cashflow", "balance", "credit", "insurance", "notes", "segments", "highlights"):
        ranked = sorted(range(len(blocks)), key=lambda index: sum(term in _compact(blocks[index]) for term in TOPICS[topic]), reverse=True)
        if ranked and topic in page_topics(blocks[ranked[0]]) and ranked[0] not in retained:
            retained.append(ranked[0])
    for index in range(len(blocks)):
        if index not in retained:
            retained.append(index)
    notice = "[材料为按主题保留的原文节选，非全文覆盖；省略内容不能用于推导已核验通过。]\n"
    budget = max_chars - len(notice)
    chunk_limit = min(5000, max(1400, budget // max(1, min(len(retained), 8))))
    output: list[tuple[int, str]] = []
    for index in retained:
        if budget < 200:
            break
        block = blocks[index]
        limit = min(chunk_limit, budget)
        piece = block[:limit]
        if len(block) > limit:
            piece = piece[:max(0, limit - 12)] + "\n[本页后文省略]"
        output.append((index, piece))
        budget -= len(piece) + 2
    return notice + "\n\n".join(piece for _, piece in sorted(output))


def _currencies(text: str) -> set[str]:
    return {code for code, pattern in (
        ("USD", r"US\$|\bUSD(?=m\b|bn\b|\b)|美元|United States dollars|US dollars"),
        ("HKD", r"HK\$|\bHKD(?=m\b|bn\b|\b)|港元|港幣|港币|Hong Kong dollars"),
        ("CNY", r"\b(?:RMB|CNY)(?=m\b|bn\b|\b)|人民幣|人民币|Renminbi"),
    ) if re.search(pattern, text, re.I)}


def _amount_scale(unit: str) -> float | None:
    compact = _compact(unit).replace("’", "'")
    # Prefer larger units; 千萬元 includes 萬 but means ten million.
    for pattern, scale in (
        (r"^(?:usd|hkd|rmb|cny|us\$|hk\$)?bn$", 10.0),
        (r"^(?:usd|hkd|rmb|cny|us\$|hk\$)?m$", 0.01),
        (r"(?:usd|hkd|rmb|cny|us\$|hk\$)bn$", 10.0),
        (r"(?:usd|hkd|rmb|cny|us\$|hk\$)m$", 0.01),
        (r"billion|十[億亿]", 10.0),
        (r"million|百[萬万]", 0.01),
        (r"thousand|千元|'000|000s", 0.00001),
        (r"[億亿]", 1.0),
        (r"[萬万]", 0.0001),
        (r"千", 0.00001),
        (r"(?:元|dollars?)$", 0.00000001),
    ):
        if re.search(pattern, compact):
            return scale
    return None


def _raw_number(value: Any) -> float | None:
    text = str(value if value is not None else "").strip().replace(",", "").replace("，", "").replace("−", "-")
    negative = (text.startswith("(") and text.endswith(")")) or (text.startswith("（") and text.endswith("）"))
    text = text.strip("()（） ")
    try:
        number = float(text)
        return -abs(number) if negative else number
    except (ValueError, TypeError):
        return None


def validate_hk_metric_payload(payload: dict, pages: list[Any]) -> tuple[dict, list[str]]:
    """Validate provenance/unit claims before engine uses an LLM metric.

    Amounts retain the issuer's original currency. Every non-null amount must
    have metric_evidence (raw_value/unit/currency/page/period/label) and pass
    arithmetic verification. This function never manufactures missing raw figures.
    """
    cleaned = dict(payload)
    issues: list[str] = []
    page_map = {int(page.page): str(page.text or "") for page in pages}
    refs = payload.get("page_refs") or []
    valid_refs = isinstance(refs, list) and bool(refs)
    parsed_refs: list[int] = []
    if valid_refs:
        for ref in refs:
            try:
                number = int(ref)
            except (TypeError, ValueError):
                valid_refs = False
                break
            if isinstance(ref, bool) or str(ref).strip() != str(number) or number not in page_map:
                valid_refs = False
                break
            parsed_refs.append(number)
    metric_fields = (
        "revenue_billion", "parent_profit_billion", "adjusted_profit_billion",
        "revenue_yoy_pct", "parent_profit_yoy_pct", "adjusted_profit_yoy_pct",
        "npm_pct", "asset_turnover", "equity_multiplier",
    )
    if not valid_refs:
        for field in metric_fields:
            cleaned[field] = None
        issues.append("港股指标提取未提供有效候选PDF页码，数值不予采用")
        return cleaned, issues
    cited_text = "\n".join(page_map[number] for number in parsed_refs)
    declared = str(payload.get("currency") or payload.get("original_currency") or "")
    note = str(payload.get("unit_note") or "")
    currencies = _currencies(declared + " " + note)
    supplied_currencies = _currencies("\n".join(page_map.values()))
    amount_fields = metric_fields[:3]
    has_amount = any(payload.get(field) is not None for field in amount_fields)
    has_unit = any(_amount_scale(unit) is not None for unit in (str(payload.get("amount_unit") or ""), note))
    if has_amount and (len(currencies) != 1 or not has_unit or not currencies.issubset(supplied_currencies)):
        for field in amount_fields:
            cleaned[field] = None
        issues.append("港股金额币种/单位未明确或与候选原文不一致，金额不予采用")
    evidence = payload.get("metric_evidence") or {}
    if not isinstance(evidence, dict):
        evidence = {}
    for field in amount_fields:
        if cleaned.get(field) is None:
            continue
        if field not in evidence:
            cleaned[field] = None
            issues.append(f"{field}缺少逐项原始取证记录，金额不予采用")
            continue
        item = evidence[field]
        if not isinstance(item, dict):
            cleaned[field] = None
            issues.append(f"{field}原始取证记录格式不正确")
            continue
        try:
            page_number = int(item.get("page"))
        except (ValueError, TypeError):
            page_number = -1
        raw = _raw_number(item.get("raw_value"))
        scale = _amount_scale(str(item.get("unit") or ""))
        currency = _currencies(str(item.get("currency") or ""))
        try:
            amount = float(cleaned[field])
        except (ValueError, TypeError):
            amount = float("nan")
        original = str(item.get("raw_value") if item.get("raw_value") is not None else "")
        original_key = re.sub(r"[\s,，]", "", original).replace("−", "-")
        page_key = re.sub(r"[,，]", "", page_map.get(page_number, "")).replace("−", "-")
        # Check exact numeric token rather than finding '123' inside '91234'.
        number_present = bool(original_key and re.search(r"(?<![\d.])" + re.escape(original_key) + r"(?![\d.])", page_key))
        if (page_number not in parsed_refs or raw is None or scale is None or
                not math.isfinite(amount) or not number_present or
                currency != currencies or not item.get("period") or not item.get("label") or
                not math.isclose(raw * scale, amount, rel_tol=0.0001, abs_tol=0.00001)):
            cleaned[field] = None
            issues.append(f"{field}原始金额、期间、币种、页码或单位换算未通过核验")
    for field in metric_fields:
        value = cleaned.get(field)
        if value is not None:
            try:
                finite = math.isfinite(float(value))
            except (TypeError, ValueError):
                finite = False
            if not finite:
                cleaned[field] = None
                issues.append(f"{field}不是有效有限数值")
    return cleaned, issues
