"""Bounded, document-wide evidence selection and publication checks.

Coverage is a retrieval diagnostic, never proof that a financial claim is true.
"""
from __future__ import annotations

import re
import unicodedata

from statement_scope import statement_segments

TOPICS = {
    "highlights": ("主要会计数据", "主要會計數據", "主要財務數據", "財務摘要", "財務概要", "经营概览", "經營亮點", "会计数据和财务指标摘要", "financial highlights", "financial summary", "key financial results"),
    "business": ("主营业务", "主營業務", "业务回顾", "業務回顧", "業務綜述", "經營情況", "management discussion", "business review", "operating review", "management commentary"),
    "balance_sheet": ("合并资产负债表", "合併資產負債表", "合併財務狀況表", "綜合財務狀況表", "consolidated statement of financial position", "consolidated balance sheet", "condensed consolidated statement of financial position", "consolidated balance sheets"),
    "income": ("合并利润表", "合併利潤表", "合併損益", "綜合損益表", "綜合收益表", "consolidated income statement", "consolidated statement of profit", "consolidated statement of comprehensive income", "consolidated income statements"),
    "cashflow": ("合并现金流量表", "合併現金流量表", "綜合現金流量表", "consolidated statement of cash flows", "consolidated cash flow", "consolidated statements of cash flows"),
    "audit_policy": ("审计意见", "審計意見", "独立核数师", "獨立核數師", "编制基础", "編製基準", "basis of preparation", "independent auditor", "significant accounting policies", "basis of accounting", "review report"),
    "segments": ("分部信息", "分部資料", "分部业绩", "分部業績", "分行业", "分行業", "segment information", "segment results", "operating segments", "segmental analysis", "business segments"),
    "debt": ("到期分析", "到期日", "流动性风险", "流動性風險", "受限资金", "受限制", "maturity analysis", "liquidity risk", "borrowings", "debt maturity", "restricted cash", "capital adequacy", "liquidity coverage"),
    "restricted_cash": ("不属于现金及现金等价物", "不屬於現金及現金等價物", "不属于现金和现金等价物", "不屬於現金及等同現金", "受限货币资金", "受限貨幣資金", "所有权或使用权受到限制的资产", "所有權或使用權受到限制的資產", "资产权利受限情况", "資產權利受限情況", "使用受限", "不可随时支取", "不可隨時支取", "保证金", "保證金", "质押定期存款", "質押定期存款", "restricted cash", "restricted bank balances", "cash not available for use", "excluded from cash and cash equivalents"),
    "related_contingent": ("关联方", "關聯方", "關連方", "或有负债", "或有負債", "related party", "contingent liabilities", "related parties", "contingencies", "capital commitments"),
    "quality": ("账龄", "賬齡", "减值", "減值", "aging", "ageing", "impairment", "expected credit losses", "credit quality", "non-performing", "contract assets"),
}

# Continuations often omit statement titles. Require multiple line labels.
STATEMENT_LINES = {
    "balance_sheet": ("total assets", "total liabilities", "total equity", "current assets", "資產總額", "負債總額", "资产总计", "负债合计", "所有者权益合计"),
    "income": ("profit before tax", "income tax expense", "profit attributable", "revenue", "除稅前溢利", "股東應佔", "营业收入", "利润总额", "所得税费用"),
    "cashflow": ("net cash from operating", "net cash used in investing", "financing activities", "cash and cash equivalents", "經營活動所得", "投資活動", "融资活动", "经营活动产生", "筹资活动产生"),
}


def _normalise(value):
    value = unicodedata.normalize("NFKC", value)
    return re.sub(r"\s+", "", value.lower()).replace("併", "并").replace("合并及公司", "合并")


def _is_contents(text):
    return len(re.findall(r"\.{3,}|…{2,}", text)) >= 4


def topic_score(text, terms):
    if _is_contents(text):
        return 0
    value = _normalise(text)
    score = sum(1 for term in terms if _normalise(term) in value)
    topic = next((name for name, values in TOPICS.items() if values == terms), "")
    if topic == "restricted_cash" and score:
        # Detailed cash-equivalent exclusions outrank a generic pledged-assets
        # overview. The breakdown often starts at the foot of a cash note and
        # continues on the following page (CATL 2025H1, PDF147–148).
        detailed = ("不属于现金及现金等价物", "不屬於現金及現金等價物", "不属于现金和现金等价物", "不屬於現金及等同現金", "excluded from cash and cash equivalents")
        score += 10 * sum(_normalise(term) in value for term in detailed)
    if topic in STATEMENT_LINES:
        line_hits = sum(_normalise(term) in value for term in STATEMENT_LINES[topic])
        if not score and line_hits >= 3:
            score = line_hits
        if score:
            numbers = len(re.findall(r"\d[\d,]*\.\d+|\d{1,3}(?:,\d{3})+", text))
            score += min(12, numbers // 4)
            if ("auditor" in text.lower() or "审计范围" in text or "審計範圍" in text) and numbers < 4:
                score = min(score, 1)
    return score


def _copy_page(page, text):
    return type(page)(page=page.page, text=text, score=getattr(page, "score", 0))


def _primary_statement_indexes(pages):
    """Prefer explicit consolidated headings and their bounded continuations.

    Numeric accounting-policy examples can score above a real statement. The
    full-document title boundaries also distinguish a parent-only continuation
    that shares a physical page with the next consolidated statement.
    """
    by_number = {page.page: index for index, page in enumerate(pages)}
    kinds = {"balance": "balance_sheet", "income": "income", "cashflow": "cashflow"}
    anchors, groups = {}, {topic: [] for topic in kinds.values()}
    for segment in statement_segments(pages):
        topic = kinds.get(segment["kind"])
        if not topic or segment["scope"] != "consolidated":
            continue
        anchors.setdefault(topic, segment["title_page"])
        index = by_number[segment["page"]]
        if segment["title_page"] == anchors[topic] and index not in groups[topic] and len(groups[topic]) < 3:
            groups[topic].append(index)
    return groups


def _bounded_pages(pages, order, max_pages, max_chars):
    """Fair budgets preserve late notes and never mutate cached pages."""
    candidates = [pages[i] for i in order[:max_pages]]
    if not candidates:
        return []
    remaining = max_chars
    budgets = [0] * len(candidates)
    active = list(range(len(candidates)))
    # Main statements put cash totals/closing balances at the bottom. Preserve
    # their complete pages and immediate continuations before clipping notes.
    protected = []
    primary = _primary_statement_indexes(pages)
    for topic in ("cashflow", "balance_sheet", "income", "restricted_cash"):
        ranked = sorted(range(len(pages)), key=lambda i: -topic_score(pages[i].text, TOPICS[topic]))
        if primary.get(topic):
            indexes = primary[topic]
        elif ranked and topic_score(pages[ranked[0]].text, TOPICS[topic]) > 0:
            indexes = (ranked[0] - 1, ranked[0], ranked[0] + 1) if topic == "restricted_cash" else (ranked[0], ranked[0] + 1)
        else:
            indexes = ()
        for index in indexes:
            if 0 <= index < len(pages) and pages[index].page not in protected:
                protected.append(pages[index].page)
    protected_budget = int(max_chars * .65)
    for number in protected:
        index = next((i for i, page in enumerate(candidates) if page.page == number), None)
        if index is None or len(candidates[index].text) > min(16000, protected_budget):
            continue
        budgets[index] = len(candidates[index].text)
        protected_budget -= budgets[index]
        remaining -= budgets[index]
        active.remove(index)
    # Water-fill by page length so a short later page does not make an earlier
    # complete statement needlessly truncated while leaving budget unused.
    while active and remaining > 0:
        share = remaining // len(active)
        small = [i for i in active if len(candidates[i].text) <= share]
        if small:
            for i in small:
                budgets[i] = len(candidates[i].text)
                remaining -= budgets[i]
                active.remove(i)
        else:
            for offset, i in enumerate(active):
                budgets[i] = share + (1 if offset < remaining % len(active) else 0)
            break
    selected = []
    suffix = "\n[本页文本截断，必要时回原PDF补取]"
    for index, page in enumerate(candidates):
        budget = budgets[index]
        if budget <= 0:
            continue
        text = page.text
        if len(text) > budget:
            if budget <= len(suffix):
                continue
            text = text[:budget - len(suffix)] + suffix
        selected.append(_copy_page(page, text))
    return sorted(selected, key=lambda p: p.page)


def select_deep_evidence(pages, metrics=None, max_pages=32, max_chars=68000, preferred_pages=None):
    """Scan the whole PDF, reserve topics, then statement/note continuations."""
    if max_pages <= 0 or max_chars <= 0 or not pages:
        return []
    priority = ("balance_sheet", "income", "cashflow", "highlights", "business", "segments", "debt", "restricted_cash", "quality", "related_contingent", "audit_policy")
    ranked = {topic: sorted((i for i in range(len(pages)) if topic_score(pages[i].text, TOPICS[topic]) > 0),
                            key=lambda i: (-topic_score(pages[i].text, TOPICS[topic]), i)) for topic in priority}
    order = []

    def reserve(index):
        if 0 <= index < len(pages) and index not in order:
            order.append(index)

    # HK-specific line-item retrieval complements the generic theme scan. The
    # three primary statements retain priority even under very small budgets.
    primary = _primary_statement_indexes(pages)
    for topic in ("balance_sheet", "income", "cashflow"):
        if primary[topic]:
            reserve(primary[topic][0])
        elif ranked[topic]:
            reserve(ranked[topic][0])
    for topic in ("balance_sheet", "income", "cashflow"):
        for index in primary[topic][1:]:
            reserve(index)
    # Cash availability is a distinct evidence need from debt maturity. Reserve
    # the detailed exclusion note and continuation before generic preferences.
    if ranked["restricted_cash"]:
        reserve(ranked["restricted_cash"][0] - 1)
        reserve(ranked["restricted_cash"][0])
        reserve(ranked["restricted_cash"][0] + 1)
    preferred_numbers = {page.page for page in (preferred_pages or [])}
    for index, page in enumerate(pages):
        if page.page in preferred_numbers:
            reserve(index)
    for rank in (0, 1):
        for topic in priority:
            if len(ranked[topic]) > rank:
                reserve(ranked[topic][rank])
    for topic in priority:
        if ranked[topic]:
            anchor = ranked[topic][0]
            reserve(anchor + 1)
            if topic in STATEMENT_LINES or topic in ("debt", "quality", "segments"):
                reserve(anchor + 2)
    # Heading-free documents retain numeric pages and document-wide samples.
    if not order:
        numeric = sorted(range(len(pages)), key=lambda i: -len(re.findall(r"\d", pages[i].text)))
        for index in numeric[:max(1, max_pages // 2)]:
            reserve(index)
    for slot in range(max_pages):
        reserve(round(slot * (len(pages) - 1) / max(1, max_pages - 1)))
    return _bounded_pages(pages, order, max_pages, max_chars)


def supplement_deep_evidence(pages, selected, max_pages=36, max_chars=76000):
    """Revisit uncovered/truncated topics against local original PDF pages.

    Prefer previously omitted complete candidates and their next page. This
    deterministic second retrieval pass requires no extra model request.
    """
    coverage = evidence_coverage(selected)
    by_number = {page.page: i for i, page in enumerate(pages)}
    selected_numbers = {page.page for page in selected}
    targets = [topic for topic in TOPICS if not coverage[topic] or all(
        "[本页文本截断" in page.text for page in selected if page.page in coverage[topic])]
    extras = []
    # A generic restriction mention cannot stand in for the cash-equivalent
    # breakdown. Supplement its strongest local note even when the topic has
    # already been counted as covered by a brief assets overview.
    restricted = sorted(range(len(pages)), key=lambda i: -topic_score(pages[i].text, TOPICS["restricted_cash"]))
    if restricted and topic_score(pages[restricted[0]].text, TOPICS["restricted_cash"]) > 0:
        for candidate in (restricted[0] - 1, restricted[0], restricted[0] + 1):
            if 0 <= candidate < len(pages) and pages[candidate].page not in selected_numbers:
                extras.append(candidate)
    for topic in targets:
        ranked = sorted(range(len(pages)), key=lambda i: -topic_score(pages[i].text, TOPICS[topic]))
        candidates = [i for i in ranked if topic_score(pages[i].text, TOPICS[topic]) > 0 and pages[i].page not in selected_numbers]
        for index in candidates[:1]:
            for candidate in (index, index + 1):
                if candidate < len(pages) and candidate not in extras:
                    extras.append(candidate)
    # Restore original full text before budgeting; never re-clip clipped copies.
    order = [by_number[page.page] for page in selected if page.page in by_number]
    order = list(dict.fromkeys(order + extras))
    return _bounded_pages(pages, order, max_pages, max_chars)


def evidence_coverage(pages):
    return {topic: [p.page for p in pages if topic_score(p.text, terms)] for topic, terms in TOPICS.items()}


def coverage_note(pages):
    coverage = evidence_coverage(pages)
    return "\n".join(f"- {topic}: 候选PDF页 {numbers}（仍须阅读核验）" if numbers else
                     f"- {topic}: 未命中候选页，证据缺口" for topic, numbers in coverage.items())


CASH_BRIDGE_PATTERNS = {
    "operating": r"(?:(?:營業|營運|經營|经营).{0,20}(?:現金|现金).{0,10}(?:淨額|净额|淨流|净流)|(?:netcash|cashflows?).{0,55}operating|operating.{0,55}(?:netcash|cashflows?))",
    "investing": r"(?:(?:投資|投资).{0,20}(?:現金|现金).{0,10}(?:淨額|净额|淨流|净流)|(?:netcash|cashflows?).{0,55}investing|investing.{0,55}(?:netcash|cashflows?))",
    "financing": r"(?:(?:融資|融资|籌資|筹资).{0,20}(?:現金|现金).{0,10}(?:淨額|净额|淨流|净流)|(?:netcash|cashflows?).{0,55}financing|financing.{0,55}(?:netcash|cashflows?))",
    "opening": r"(?:(?:期初|年初).{0,25}(?:現金|现金)|(?:現金|现金).{0,25}(?:期初|年初)|cashandcashequivalents.{0,35}(?:beginning|start)|(?:beginning|start).{0,35}cashandcashequivalents)",
    "closing": r"(?:(?:期末|年末).{0,25}(?:現金|现金)|(?:現金|现金).{0,25}(?:期末|年末)|cashandcashequivalents.{0,35}(?:attheend|atend|closing)|(?:closing|attheend|atend).{0,35}cashandcashequivalents)",
    "fx": r"(?:(?:現金|现金).{0,25}(?:匯兌|汇兑|匯率|汇率)|(?:匯兌|汇兑|匯率|汇率).{0,25}(?:現金|现金)|(?:effect|effects).{0,30}(?:exchange|currency)|exchange.{0,30}(?:cash|equivalents))",
}


def cash_bridge_rows(pages):
    """Locate original cash-flow rows, retaining raw text and column headings."""
    found = []
    for page in pages:
        if not topic_score(page.text, TOPICS["cashflow"]):
            continue
        lines = page.text.splitlines()
        matches = {}
        for index, line in enumerate(lines):
            normalised = _normalise(line)
            for kind, pattern in CASH_BRIDGE_PATTERNS.items():
                if re.search(pattern, normalised, re.I):
                    matches.setdefault(kind, []).append(index)
        if matches:
            found.append((page, lines, matches))
    return found


def cash_bridge_excerpt(pages, max_chars=9000):
    """Highlight verbatim cash totals so model attention does not skip table tails.

    No amount or arithmetic is synthesized. Raw period/unit headers and both
    comparative columns remain attached to the rows; bank cash is not described
    as freely usable corporate cash.
    """
    output = []
    for page, lines, matches in sorted(cash_bridge_rows(pages), key=lambda item: -len(item[2]))[:3]:
        retained = set(range(min(12, len(lines))))
        for indexes in matches.values():
            for index in indexes:
                retained.update(range(max(0, index - 1), min(len(lines), index + 3)))
        block = f"===== 本期PDF第{page.page}页：现金桥原文定位（保持原列顺序） =====\n"
        block += "\n".join(lines[index] for index in sorted(retained))
        if sum(len(part) for part in output) + len(block) > max_chars:
            continue
        output.append(block)
    return "\n\n".join(output)


def cash_bridge_missing_claim_sections(sections, pages):
    """Flag a claimed absent cash bridge only when all raw rows were supplied."""
    available = set().union(*(set(matches) for _, _, matches in cash_bridge_rows(pages))) if pages else set()
    if not {"operating", "investing", "financing", "opening", "closing"}.issubset(available):
        return []
    missing_claim = re.compile(r"未取得|未提供|未提取|未獲取|未获取|缺少|缺失|无法核验|無法核驗|无法取得|未见|未見|未包含|仅(?:含|有|提供|列示).*调节")
    cash_subject = re.compile(r"(?:经营|營業|營運|經營|投资|投資|筹资|籌資|融资|融資).{0,12}(?:现金|現金)|(?:期末|期初).{0,12}(?:现金|現金)|三[类類].{0,10}(?:现金|現金)|(?:现金|現金).{0,8}(?:勾稽|桥|橋|净额|淨額|期末|期初)")
    affected = []
    for numeral, body in sections.items():
        sentences = re.split(r"[。；\n]", unicodedata.normalize("NFKC", body))
        if any(missing_claim.search(sentence) and cash_subject.search(sentence) for sentence in sentences):
            affected.append(numeral)
    return affected


def _review_label_pattern(pattern):
    variants = {
        "证": "證", "据": "據", "状": "狀", "态": "態", "风": "風", "险": "險",
        "验": "驗", "触": "觸", "发": "發", "对": "對", "检": "檢", "仅": "僅",
        "执": "執", "现": "現", "桥": "橋", "总": "總", "术": "術", "复": "複覆",
        "读": "讀", "项": "項", "应": "應", "进": "進", "没": "沒", "写": "寫",
        "并": "並", "动": "動", "后": "後", "续": "續", "议": "議",
        "无": "無", "声": "聲", "称": "稱", "于": "於",
    }
    return "".join("[" + char + variants[char] + "]" if char in variants else char for char in pattern)


def _review_label_text(source, simplified, traditional):
    return traditional if re.search(r"[證據狀態風險驗觸發對檢僅執現橋總術複覆讀進項沒應寫並動後續議]", source) else simplified


def clarify_deep_review_labels(markdown):
    """Clarify fixed memo labels without rewriting financial conclusions.

    Only explicit risk-status labels and a fixed prefix in a known section-six
    status column are changed. Suffix qualifications/numbers stay untouched.
    Ambiguous prose/cells are retained and reported for review.
    This helper is applied only to deep memos, never independent risk reports.
    """
    risk_label = re.compile(_review_label_pattern(r"(?:\*{0,2})(?:证据状态|风险状态)(?:\*{0,2})\s*[:：]\s*(?:\*{0,2})已核验触发(?:\*{0,2})"))
    text = risk_label.sub(lambda match: _review_label_text(match.group(),
        "研究风险分类：已观察到的风险事实", "研究風險分類：已觀察到的風險事實"), markdown)
    # No deterministic cash-bridge arithmetic is executed by this module.
    # Clarify known fixed claims only; financial formulas and their values stay.
    arithmetic_claims = (
        r"程序检查\s*[:：]\s*(?:现金桥(?:的)?|现金流(?:的)?)?(?:加总核对|加总校验|算术核对|算术校验)",
        r"(?:本次)?程序检查(?:仅)?(?:执行了|进行了)(?:现金桥|现金流)(?:的)?(?:加总核对|加总校验|算术核对|算术校验)",
        r"程序(?:算术|加总)(?:已)?(?:核对|核验|校验|验证)",
        r"程序(?:仅)?执行(?:了)?(?:该)?(?:现金桥(?:的)?)?(?:加总|加法验证|加法核对|减法)",
        r"程序检查覆盖范围\s*[:：]\s*仅对现金桥加总与简化现金结余减法执行了算术核对",
    )
    def clarify_arithmetic(match):
        prefix = re.split(r"[|；;。！？\n]", text[max(0, match.start() - 30):match.start()])[-1]
        if re.search(_review_label_pattern(r"未|无|没有|尚未|不包含|不声称|不等于|不得|不能|建议|后续|待|需|应"), prefix):
            return match.group()
        return _review_label_text(match.group(), "模型计算，待人工复核", "模型計算，待人工複核")

    for pattern in arithmetic_claims:
        text = re.sub(_review_label_pattern(pattern), clarify_arithmetic, text)
    output = []
    section = ""
    header_cells = None
    status_columns = []
    for line in text.splitlines():
        chapter = re.match(r"^##\s+([一二三四五六七八九十]+)、", line)
        if chapter:
            section = chapter.group(1)
            header_cells = None
            status_columns = []
        if section == "六" and line.strip().startswith("|") and line.strip().endswith("|"):
            cells = line.strip()[1:-1].split("|")
            if header_cells is None:
                header_cells = cells
                status_columns = [index for index, cell in enumerate(cells)
                                  if re.search(_review_label_pattern(r"核验状态|核查状态|读取/程序检查|待复核事项"), cell)]
            elif len(cells) == len(header_cells):
                changed = False
                for index in status_columns:
                    label = re.match(_review_label_pattern(r"^(\s*)(?:\*\*|`)?已核对原文(?:\*\*|`)?(?P<tail>\s*(?:[；;，,].*)?)$"), cells[index])
                    if label:
                        prefix = _review_label_text(label.group(),
                            "模型读取及页码定位，待人工复核", "模型讀取及頁碼定位，待人工複核")
                        cells[index] = label.group(1) + prefix + label.group("tail")
                        changed = True
                if changed:
                    line = "|" + "|".join(cells) + "|"
        elif line.strip() and not chapter:
            header_cells = None
            status_columns = []
        output.append(line)
    ending = re.search(r"[\r\n]*$", text).group()
    newline = "\r\n" if "\r\n" in text else "\n"
    text = newline.join(output).rstrip("\r\n") + ending
    issues = []
    for match in re.finditer(_review_label_pattern(r"已核对原文|已核验触发|已核验未触发"), text):
        prefix = text[max(0, match.start() - 15):match.start()]
        if re.search(_review_label_pattern(r"不使用|不写|不声称|不得|不能|不可|不代表|并非|不是|避免|尚未|没有"), prefix):
            continue
        issues.append("深度报告核验标签上下文不明确，需复核：" + match.group())
    arithmetic = re.compile(_review_label_pattern(r"(?:程序|自动).{0,16}(?:加总|算术|现金桥)|(?:加总|算术|现金桥).{0,16}(?:程序校验|程序核对|程序核验|自动程序验证)"))
    for match in arithmetic.finditer(text):
        prefix = re.split(r"[|；;。！？\n]", text[max(0, match.start() - 30):match.start()])[-1]
        if re.search(_review_label_pattern(r"未|无|不包含|不代表|不声称|不等于|不得|不能|没有|尚未|后续|建议|待|需|应"), prefix + match.group()):
            continue
        # This observed wording explicitly describes model reading, not an
        # executed numerical program. The following clause separately denies
        # independent program arithmetic; retain it verbatim.
        line_end = text.find("\n", match.end())
        context = text[max(0, match.start() - 10):line_end if line_end >= 0 else len(text)]
        if re.search(_review_label_pattern(r"程序检查\s*[:：]\s*本次仅执行了页码定位与现金桥等式的模型读取核对"), context):
            continue
        issues.append("深度报告宣称未实际执行的程序算术检查，需复核：" + match.group())
    return text, list(dict.fromkeys(issues))


def section_body_incomplete(body):
    """Catch empty chapters and interrupted Markdown tables, without judging facts."""
    if len(re.sub(r"[\s|#*\-]", "", body)) < 20:
        return True
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        if line.startswith("|"):
            if not line.endswith("|") or line.count("|") < 3:
                return True
            if re.fullmatch(r"[|:\-\s]+", line):
                if index + 1 == len(lines) or not lines[index + 1].startswith("|"):
                    return True
    return False


def source_reference_issues(markdown, current_pages, prior_pages=()):
    """Check physical-page references against evidence actually supplied.

    This establishes provenance only, not semantic support for the inference.
    Tagged v8.1 citations distinguish files; legacy untagged references use the
    union so existing historical reports remain readable.
    """
    current = {int(p.page) for p in current_pages}
    prior = {int(p.page) for p in prior_pages}
    issues = []
    pattern = re.compile(r"(?:(本期|上期)\s*)?PDF\s*第?\s*(\d+)\s*页", re.I)
    for match in pattern.finditer(markdown):
        period, raw = match.groups()
        available = current if period == "本期" else prior if period == "上期" else current | prior
        if int(raw) not in available:
            item = f"引用未包含在实际输入证据中：{match.group()}"
            if item not in issues:
                issues.append(item)
    return issues


def report_quality_issues(markdown):
    """Conservative publication checks, not an automatic factual audit."""
    issues = []
    if any(x in markdown for x in ("当前仅保留完整章节骨架", "模型章节补写未完成", "测试模式未调用模型", "报告尚未生成")):
        issues.append("报告包含兜底或未生成内容")
    if not re.search(r"(?:PDF\s*第?\s*\d+\s*页|\[S\d+[^\]]*\]|\[本期[^\]]*\d+[^\]]*\])", markdown):
        issues.append("未识别到可追溯页码/来源引用")
    matches = list(re.finditer(r"(?m)^##\s+[一二三四五六七八九十]+、[^\n]*", markdown))
    for i, match in enumerate(matches):
        body = markdown[match.end():matches[i+1].start() if i+1 < len(matches) else len(markdown)]
        if section_body_incomplete(body):
            issues.append("章节正文不足或表格截断：" + match.group().removeprefix("## "))
    return issues
