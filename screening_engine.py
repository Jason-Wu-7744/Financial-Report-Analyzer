from __future__ import annotations

import json
import math
import re
import sys
import unicodedata
from datetime import date, datetime
from html import escape
from pathlib import Path
from urllib.parse import urlsplit

from openai import OpenAI
from hk_quality import HK_EXTRACTION_RULES, compact_risk_evidence


SCREENING_DIR = Path(__file__).resolve().parent / "screening"
CHECK_NAMES = {
    "H1": "行业需求不可逆萎缩",
    "H2": "行业面临政策致命风险",
    "C1": "财务真实性存疑",
    "C2": "资金链断裂风险",
    "C3": "政策一招致命",
    "C4": "管理层诚信缺陷",
    "C5": "极度高估",
    "C6": "短期暴涨",
    "C7": "价值陷阱",
    "C8": "次新股",
    "C9": "资本黑洞",
    "C10": "纯概念蹭风口",
    "C11": "流动性与退市风险",
    "Q1": "资产负债率红线",
    "Q2": "现金流红线",
    "Q3": "利润质量红线",
    "Q4": "商誉暴雷风险",
    "Q5": "应收账款恶化",
    "Q6": "大股东减持信号",
}
CHECK_ORDER = list(CHECK_NAMES)
ALLOWED_OUTCOMES = {"通过", "高风险", "通过（不适用）", "证据不足"}
EVIDENCE_STATES = {
    "通过": "已核验未触发", "高风险": "已核验触发",
    "通过（不适用）": "不适用", "证据不足": "证据不足",
}
INSUFFICIENT_RE = re.compile(
    r"未(?:取得|获取|提供|披露|提取|核验|覆盖|查到)|无法(?:确认|核验|判断|计算)|"
    r"证据不足|资料不足|数据不足|待补证|暂按通过|未见.{0,16}(?:硬阈值|硬证据)|"
    r"not (?:available|disclosed|verified)|insufficient evidence|not assessed", re.I
)


def _quote_key(text: str) -> str:
    return re.sub(r"[\s,，\"'“”‘’]", "", unicodedata.normalize("NFKC", str(text or ""))).lower()


AND_CHECK_IDS = {"H1", "C5", "C6", "C9", "C10", "Q1", "Q2", "Q4", "Q5", "Q6"}
NUMERIC_AND_THRESHOLDS = {"Q1": 80.0, "Q4": 50.0, "Q5": 40.0}


def _number_in_quote(value: float, quote: str) -> bool:
    normalized = unicodedata.normalize("NFKC", str(quote or "")).replace(",", "").replace("，", "").replace("−", "-")
    numbers = re.findall(r"(?<![\d.])-?\d+(?:\.\d+)?(?![\d.])", normalized)
    return any(math.isclose(float(number), value, rel_tol=1e-8, abs_tol=1e-8) for number in numbers)


def _valid_and_disproof(check: dict) -> bool:
    """Accept a disproved necessary condition without demanding unknown siblings.

    Numeric red lines have a small deterministic check. Other AND conditions
    retain a traceable statement of which necessary condition was disproved.
    This does not allow a disproved single branch to clear an OR check.
    """
    cid = str(check.get("id") or "")
    if cid not in AND_CHECK_IDS or check.get("proof_type") != "and_condition_disproved":
        return False
    if len(str(check.get("disproven_condition") or "").strip()) < 4:
        return False
    if cid not in NUMERIC_AND_THRESHOLDS:
        return bool(check.get("evidence_quote") or check.get("evidence_quotes"))
    disproof = check.get("disproof")
    if not isinstance(disproof, dict):
        return False
    try:
        numerator = float(disproof["numerator"])
        denominator = float(disproof["denominator"])
        ratio = float(disproof["ratio_pct"])
        threshold = float(disproof["threshold_pct"])
    except (KeyError, TypeError, ValueError):
        return False
    if not all(math.isfinite(value) for value in (numerator, denominator, ratio, threshold)) or denominator <= 0:
        return False
    if threshold != NUMERIC_AND_THRESHOLDS[cid] or ratio > threshold or numerator < 0:
        return False
    if not math.isclose(numerator / denominator * 100, ratio, abs_tol=0.05):
        return False
    return bool(disproof.get("period") and disproof.get("unit") and
                _number_in_quote(numerator, disproof.get("numerator_quote") or "") and
                _number_in_quote(denominator, disproof.get("denominator_quote") or ""))


def _evidence_quotes(check: dict) -> list[str]:
    quotes = check.get("evidence_quotes") or []
    quotes = [str(quote) for quote in quotes if isinstance(quote, str)] if isinstance(quotes, list) else []
    if check.get("evidence_quote"):
        quotes.append(str(check["evidence_quote"]))
    disproof = check.get("disproof")
    if isinstance(disproof, dict):
        quotes.extend(str(disproof[key]) for key in ("numerator_quote", "denominator_quote") if disproof.get(key))
    return list(dict.fromkeys(quote for quote in quotes if quote.strip()))


def validate_check_evidence(check: dict, evidence_text: str) -> dict:
    """Reject a positive evidence state when its quoted source was not supplied."""
    result = dict(check)
    state = str(result.get("evidence_state") or "证据不足")
    if state in {"已核验未触发", "已核验触发"}:
        quotes = [_quote_key(quote) for quote in _evidence_quotes(result)]
        valid_quote = bool(quotes) and all(len(quote) >= 8 and quote in _quote_key(evidence_text) for quote in quotes)
        # A report title proves issuer identity, not its IPO/listing date.
        if str(result.get("id")) == "C8":
            listing_quote = " ".join(quotes)
            valid_quote = valid_quote and bool(re.search(r"(?:上市|掛牌|挂牌|listed|listing|ipo)", listing_quote, re.I)) and bool(re.search(r"(?:18|19|20)\d{2}|(?:\d+|二十|三十|十)年", listing_quote))
        if not valid_quote:
            result["evidence_state"] = "证据不足"
            result["outcome"] = "证据不足"
            result["basis"] = "未取得可在所给原文复核的直接引文，须补证后判断。[S1]"
        elif state == "已核验未触发" and result.get("proof_type") == "and_condition_disproved" and not _valid_and_disproof(result):
            result["evidence_state"] = "证据不足"
            result["outcome"] = "证据不足"
            result["basis"] = "所称AND必要条件反证未通过数值/条件核验，须补证后判断。[S1]"
    return result
THRESHOLDS = {
    "H1": "行业整体需求连续下滑、无周期复苏信号，且技术替代不可逆。",
    "H2": "行业商业模式合法性存疑；核心收入依赖单一政策容忍度，一纸文件可归零。",
    "C1": "资金与负债结构异常、关联交易、非标审计、经营现金流/净利润过低，或造假立案前科。",
    "C2": "短债覆盖不足且经营现金流为负，或质押/占用/违规担保实锤。",
    "C3": "核心业务合法性完全依赖单一政策，政策转向业务归零。",
    "C4": "实控人/高管诚信缺陷、损害小股东实锤，或核心团队一年内集体离职。",
    "C5": "估值处于自身历史90%分位以上且无足够业绩增长支撑。",
    "C6": "近6个月涨幅>80%，或近3个月>100%，或近1个月>50%，且无基本面重大变化。",
    "C7": "主营连续2年营收、归母净利双下滑且行业需求不可逆萎缩等价值陷阱条件。",
    "C8": "上市不满2-3年，财务包装期、解禁减持和完整周期检验尚未结束。",
    "C9": "收入利润多年无增长，同时资本开支/折旧比长期>1.5，且自由现金流常年为负。",
    "C10": "热点业务真实收入占比<20%，且依靠公告蹭概念，缺乏落地证据。",
    "C11": "ST/*ST或明确退市风险，或日均成交额<5000万元，或商誉/净资产>50%且承诺集中到期。",
    "Q1": "资产负债率>80%，且连续2年持续上升。",
    "Q2": "连续3年经营现金流净额为负，且主业无周期反转逻辑。",
    "Q3": "近3年累计经营现金流净额/累计净利润<50%。净利润≤0时为通过（不适用）。",
    "Q4": "商誉/净资产>50%，且标的公司业绩承诺期集中到期。",
    "Q5": "应收账款/营收>40%，且1年以上账龄占比>30%。",
    "Q6": "近1年大股东/实控人减持>总股本5%，且估值处于历史中高分位。",
}


def ticker_of(stock_code: str) -> str:
    text = str(stock_code or "").strip().upper()
    if text.endswith(".HK") or text.startswith("HK") or re.fullmatch(r"\d{3,5}(?:\.0)?", text):
        digits = re.sub(r"\D", "", text)
        return f"{int(digits):05d}.HK" if digits else text
    digits = re.search(r"(?<!\d)(\d{6})(?!\d)", str(stock_code or ""))
    code = digits.group(1) if digits else re.sub(r"\D", "", str(stock_code or ""))[:6]
    if code.startswith(("5", "6")):
        return f"{code}.SH"
    if code.startswith(("4", "8", "9")):
        return f"{code}.BJ"
    return f"{code}.SZ"


def cninfo_search_url(stock_code: str) -> str:
    text = str(stock_code or "").strip().upper()
    if text.endswith(".HK") or text.startswith("HK") or re.fullmatch(r"\d{3,5}(?:\.0)?", text):
        digits = re.sub(r"\D", "", text)
        code = f"{int(digits):05d}" if digits else ""
        return f"https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=zh&market=SEHK&title={code}"
    digits = re.search(r"(?<!\d)(\d{6})(?!\d)", str(stock_code or ""))
    code = digits.group(1) if digits else "000000"
    return f"https://www.cninfo.com.cn/new/commonUrl/pageOfSearch?keyWord={code}"


def derive_conclusion(hits: list[str], unchecked: list[str] | None = None) -> str:
    if hits:
        return "淘汰"
    return "待补证" if unchecked else "通过"


def derive_fast_conclusion(hits: list[str], unchecked: list[str] | None = None) -> str:
    return "暂定淘汰" if hits else ("暂定待补证" if unchecked else "暂定通过")


def _parse_json(content: str) -> dict:
    cleaned = (content or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    if start < 0:
        raise ValueError("模型未返回 JSON 对象。")
    cleaned = cleaned[start:]
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        # Models occasionally hit the output limit in the middle of a string.
        # Close that string and every open container. normalize_report will
        # supply any omitted check IDs, while screen_full also performs a retry.
        stack: list[str] = []
        in_string = False
        escaped = False
        for char in cleaned:
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char in "[{":
                stack.append(char)
            elif char == "]" and stack and stack[-1] == "[":
                stack.pop()
            elif char == "}" and stack and stack[-1] == "{":
                stack.pop()
        repaired = cleaned.rstrip()
        if in_string:
            if escaped:
                repaired = repaired[:-1]
            repaired += '"'
        repaired = re.sub(r",\s*$", "", repaired)
        repaired += "".join("]" if token == "[" else "}" for token in reversed(stack))
        payload = json.loads(repaired)
    if not isinstance(payload, dict):
        raise ValueError("模型返回的不是 JSON 对象。")
    return payload


def _complete_check_objects(content: str) -> tuple[dict[str, dict], dict]:
    """Recover only independently closed JSON check objects, never close one.

    Unlike _parse_json's legacy display repair, this decoder does not append a
    quote or brace. A cut-off finding/basis/proof therefore cannot be adopted.
    Duplicate IDs in one response are all discarded, including identical copies.
    """
    match = re.search(r'"checks"\s*:\s*\[', str(content or ""))
    parsed = []
    if match:
        decoder = json.JSONDecoder(strict=False)
        position = match.end()
        while position < len(content):
            position = re.compile(r"\s*").match(content, position).end()
            if position >= len(content) or content[position] == "]":
                break
            try:
                item, end = decoder.raw_decode(content, position)
            except json.JSONDecodeError:
                break
            if not isinstance(item, dict):
                break
            parsed.append(item)
            position = re.compile(r"\s*").match(content, end).end()
            if position < len(content) and content[position] == ",":
                position += 1
            elif position < len(content) and content[position] == "]":
                break
            else:
                break
    counts = {}
    for item in parsed:
        cid = str(item.get("id") or "")
        counts[cid] = counts.get(cid, 0) + 1
    adopted = {}
    for item in parsed:
        cid = str(item.get("id") or "")
        if cid not in CHECK_NAMES or counts[cid] != 1:
            continue
        state = item.get("evidence_state")
        if state not in EVIDENCE_STATES.values():
            continue
        if not all(isinstance(item.get(key), str) and item[key].strip() for key in ("finding", "basis")):
            continue
        ids = item.get("source_ids")
        if not isinstance(ids, list) or not ids or not all(isinstance(sid, str) and sid.strip() for sid in ids):
            continue
        adopted[cid] = item
    return adopted, {"closed_object_count": len(parsed), "complete_ids": [cid for cid in CHECK_ORDER if cid in adopted],
                     "duplicate_ids": sorted(cid for cid, count in counts.items() if count > 1),
                     "unknown_ids": sorted(cid for cid in counts if cid not in CHECK_NAMES)}


def _generate_complete_review(client, *, model: str, system_prompt: str, user_prompt: str, diagnostics: list[dict]) -> dict:
    """At most two full calls plus four repairs of at most five missing IDs.

    Every adopted check still passes source/proof validation in screen_full.
    A failure to obtain all 19 unique, closed objects remains retryable failure.
    """
    complete: dict[str, dict] = {}
    base: dict = {}
    last_error: Exception | None = None
    for attempt, budget in enumerate((6000, 7500), start=1):
        retry_note = "" if attempt == 1 else (
            "\n上次检查不完整。只保留19项checks和必要meta/sources，省略可选长表和重复标题；"
            "每项finding/basis各不超过45字。仅AND数值反证项输出disproof，不给其他项复制空对象。"
            "checks每项必须含id,evidence_state,finding,basis,source_ids；有证据的直接引文必须保留。"
        )
        try:
            response = client.chat.completions.create(
                model=model, messages=[{"role": "system", "content": system_prompt + retry_note},
                                       {"role": "user", "content": user_prompt}],
                response_format={"type": "json_object"}, max_tokens=budget, temperature=0,
                extra_body={"thinking": {"type": "disabled"}},
            )
            choice = response.choices[0]
            content = choice.message.content or ""
            items, info = _complete_check_objects(content)
            diagnostics.append({"phase": "full", "attempt": attempt, "max_tokens": budget,
                                "finish_reason": str(getattr(choice, "finish_reason", "") or "unknown"), **info})
            complete.update(items)
            # Optional metadata is retained only from a fully valid whole JSON.
            try:
                parsed = json.loads(content.strip().removeprefix("```json").removesuffix("```").strip(), strict=False)
                if isinstance(parsed, dict):
                    base = parsed
            except (ValueError, TypeError):
                pass
            if set(complete) == set(CHECK_ORDER):
                base["checks"] = [complete[cid] for cid in CHECK_ORDER]
                return base
            last_error = ValueError("模型返回的19项检查不完整；缺失ID：" + ",".join(cid for cid in CHECK_ORDER if cid not in complete))
        except Exception as error:
            last_error = error
            diagnostics.append({"phase": "full", "attempt": attempt, "error_type": type(error).__name__})
    if not complete:
        raise last_error or ValueError("模型未返回完整排雷 JSON")
    missing = [cid for cid in CHECK_ORDER if cid not in complete]
    for batch_number, start in enumerate(range(0, len(missing), 5), start=1):
        wanted = missing[start:start + 5]
        repair_prompt = (
            "\n仅补全以下缺失ID：" + ",".join(wanted) + "。其他ID已经完成，不得重复输出。"
            "只输出JSON {checks:[...]}，每项保留id,evidence_state,finding,basis,source_ids及必要直接引文/反证。"
            "每项finding/basis各不超过60字，不重复完整阈值或报告元数据。不要为填满项目编造证据，确实不足则明确证据不足。"
        )
        response = client.chat.completions.create(
            model=model, messages=[{"role": "system", "content": system_prompt + repair_prompt},
                                   {"role": "user", "content": user_prompt}],
            response_format={"type": "json_object"}, max_tokens=3200, temperature=0,
            extra_body={"thinking": {"type": "disabled"}},
        )
        choice = response.choices[0]
        items, info = _complete_check_objects(choice.message.content or "")
        diagnostics.append({"phase": "missing_check_repair", "batch": batch_number, "requested_ids": wanted,
                            "finish_reason": str(getattr(choice, "finish_reason", "") or "unknown"), **info})
        if set(items) != set(wanted) or info["duplicate_ids"] or info["unknown_ids"] or info["closed_object_count"] != len(wanted):
            raise ValueError("缺项补写仍不完整或ID不匹配：" + ",".join(wanted))
        complete.update(items)
    if set(complete) != set(CHECK_ORDER):
        raise ValueError("排雷补写后19项检查仍不完整")
    base["checks"] = [complete[cid] for cid in CHECK_ORDER]
    return base


def _framework_text() -> str:
    path = SCREENING_DIR / "references" / "framework.md"
    if path.is_file():
        return path.read_text(encoding="utf-8")[:6000]
    lines = [f"{cid} {name}：{THRESHOLDS[cid]}" for cid, name in CHECK_NAMES.items()]
    return "\n".join(lines)


def empty_fast_result(note: str, unchecked: list[str] | None = None) -> dict:
    return {
        "screening_conclusion": "未完成",
        "screening_hits": [],
        "screening_unchecked": list(unchecked) if unchecked is not None else CHECK_ORDER.copy(),
        "screening_note": note[:80],
        "screening_evidence_states": {cid: "证据不足" for cid in CHECK_ORDER},
    }


def screen_fast(
    *,
    company_name: str,
    stock_code: str,
    report_type: str,
    report_year: int,
    metrics: dict[str, str],
    evidence_text: str,
    api_key: str,
    model: str,
    base_url: str,
    test_mode: bool,
) -> dict:
    if test_mode or not api_key.strip():
        return empty_fast_result("测试模式或未填密钥，19项均未核验" if test_mode else "未填写 API Key，19项均未核验")
    if not (evidence_text or "").strip():
        return empty_fast_result("没有可用原文，无法快速排雷")
    metric_lines = "\n".join(f"- {key}: {value}" for key, value in (metrics or {}).items()) or "- 无结构化财务数据"
    user_prompt = f"""公司：{company_name}（{stock_code}）
报告：{report_year}年{report_type}

结构化财务数据：
{metric_lines}

候选原文：
{compact_risk_evidence(evidence_text, max_chars=8000)}
"""
    system_prompt = (
        "你是开题前致命风险排雷助手，只做极速筛查。"
        "严格按 H1-H2、C1-C11、Q1-Q6 共19项硬线判定，一票否决，不打分、不评星、不用A/B/C。"
        "每项evidence_state只能是：已核验未触发 / 已核验触发 / 证据不足 / 不适用。"
        "只有原文或财务数据足以证明命中硬阈值时才写入 hits。"
        "AND红线：全部必要条件为真才触发；任一必要条件有直接证据为假即可已核验未触发，其余条件缺资料不改变该反证。"
        "OR红线：任一子条件已证明为真即可触发；要判未触发必须排除全部子条件，不能用一个子条件为假代替全项通过。"
        "AND反证时proof_type=and_condition_disproved，disproven_condition写被否定的必要条件，保留直接原文。"
        "Q1/Q4/Q5反证须加disproof{numerator,denominator,ratio_pct,threshold_pct,period,unit,numerator_quote,denominator_quote}，阈值分别80/50/40。"
        "估值、涨跌幅、质押、减持若原文没有标记证据不足，不能把未查到视为通过。"
        "不适用须说明具体行业或数学原因；缺数据不是不适用。"
        "只输出 JSON："
        '{"checks":[{"id":"H1","evidence_state":"证据不足","finding":"事实及期间",'
        '"basis":"对应的直接原文或缺口","evidence_quote":"8-60字直接原文；不足则空",'
        '"proof_type":"all_conditions_verified/and_condition_disproved/or_all_conditions_disproved/insufficient/not_applicable",'
        '"disproven_condition":"AND被否定的必要条件；无则空"}],"note":"不超过40字"}。19项ID须齐全。'
    )
    try:
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=60.0, max_retries=1)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt + "\n\n框架：\n" + _framework_text()[:3500]},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            max_tokens=2400,
            temperature=0,
            extra_body={"thinking": {"type": "disabled"}},
        )
        payload = _parse_json(response.choices[0].message.content or "")
    except Exception as error:
        return empty_fast_result(f"快速排雷失败：{error}")
    raw_checks = {str(item.get("id") or "").upper(): item for item in (payload.get("checks") or []) if isinstance(item, dict)}
    states = {}
    for cid in CHECK_ORDER:
        item = validate_check_evidence(raw_checks.get(cid) or {}, evidence_text)
        state = str(item.get("evidence_state") or "证据不足")
        detail = str(item.get("finding") or "") + " " + str(item.get("basis") or "")
        if state not in EVIDENCE_STATES.values() or not item.get("finding") or not item.get("basis"):
            state = "证据不足"
        if state != "不适用" and INSUFFICIENT_RE.search(detail) and not (state == "已核验未触发" and _valid_and_disproof(item)):
            state = "证据不足"
        states[cid] = state
    hits = [cid for cid in CHECK_ORDER if states[cid] == "已核验触发"]
    unchecked = [cid for cid in CHECK_ORDER if states[cid] == "证据不足"]
    note = f"已核验{19-len(unchecked)}项；{len(unchecked)}项证据不足"
    if hits:
        note = f"命中 {'、'.join(hits)}；{len(unchecked)}项仍待核验"
    return {
        "screening_conclusion": derive_fast_conclusion(hits, unchecked),
        "screening_hits": hits,
        "screening_unchecked": unchecked,
        "screening_note": note,
        "screening_evidence_states": states,
    }


def _add_months(iso_date: str, months: int) -> str:
    y, m, d = map(int, iso_date.split("-"))
    total = y * 12 + (m - 1) + months
    ny, nm = divmod(total, 12)
    nm += 1
    month_days = [31, 29 if ny % 4 == 0 and (ny % 100 != 0 or ny % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return date(ny, nm, min(d, month_days[nm - 1])).isoformat()


def _normalize_outcome(raw: str) -> str:
    text = str(raw or "").strip()
    if text in ALLOWED_OUTCOMES:
        return text
    if "高风险" in text or text in {"淘汰", "暂定淘汰"}:
        return "高风险"
    if "不适用" in text:
        return "通过（不适用）"
    if text == "已核验未触发":
        return "通过"
    if text == "已核验触发":
        return "高风险"
    return "证据不足"


def _blank_check(cid: str, source_id: str = "S1") -> dict:
    return {
        "id": cid,
        "name": CHECK_NAMES[cid],
        "outcome": "证据不足",
        "evidence_state": "证据不足",
        "threshold": THRESHOLDS[cid],
        "finding": "现有材料不足以完成该项阈值核验。",
        "basis": f"须补齐适用期间、口径及该项直接证据后判断。[{source_id}]",
        "source_ids": [source_id],
    }


def _ensure_citation(text: str, source_id: str) -> str:
    body = str(text or "").strip() or "现有材料不足以完成阈值核验。"
    if re.search(r"\[S\d+\]", body):
        return body
    return f"{body}[{source_id}]"


def _clean_snapshot(raw, conclusion: str, one_line: str) -> list[dict]:
    items = []
    if isinstance(raw, list):
        for item in raw[:6]:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or "").strip()
            value = str(item.get("value") or "").strip()
            if not label or not value:
                continue
            items.append({"label": label, "value": value, "note": str(item.get("note") or "—").strip() or "—"})
    if not items:
        items = [{"label": "排雷结论", "value": conclusion, "note": (one_line or "—")[:40]}]
    return items


def _clean_tables(raw) -> list[dict]:
    tables = []
    if not isinstance(raw, list):
        return tables
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        cols = item.get("columns")
        rows = item.get("rows")
        if not title or not isinstance(cols, list) or not isinstance(rows, list):
            continue
        columns = [str(col).strip() or "—" for col in cols][:6]
        if not (2 <= len(columns) <= 6):
            continue
        clean_rows = []
        for row in rows:
            if not isinstance(row, list) or len(row) != len(columns):
                continue
            clean_rows.append([str(cell if cell is not None else "—") for cell in row])
        if clean_rows:
            tables.append({"title": title, "columns": columns, "rows": clean_rows})
    return tables


def _clean_observations(raw) -> list[dict]:
    items = []
    if not isinstance(raw, list):
        return items
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        detail = str(item.get("detail") or "").strip()
        if not title or not detail:
            continue
        monitor = str(item.get("monitor") or "").strip() or "后续定期报告与公告复核。"
        items.append({"title": title, "detail": detail, "monitor": monitor})
    return items


def _clean_formulas(raw) -> list[dict]:
    items = []
    if not isinstance(raw, list):
        return items
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        formula = str(item.get("formula") or "").strip()
        if name and formula:
            items.append({"name": name, "formula": formula})
    return items


def _clean_strings(raw) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def _cell(text: str) -> str:
    return str(text or "").replace("|", "、").replace("\n", " ").strip()


def source_publication_date(url: str, supplied_date: str = "") -> str:
    """Keep a filing's publication date separate from the date of analysis.

    HKEX/CNINFO dated filing paths identify the specific published document,
    not the board approval date of the results within it. Other URLs require
    an explicitly supplied date; a screening date is never a default.
    """
    parsed = urlsplit(str(url or ""))
    host = (parsed.hostname or "").lower()
    candidate = ""
    if host in {"hkexnews.hk", "www.hkexnews.hk", "www1.hkexnews.hk"}:
        match = re.search(r"/listedco/listconews/sehk/(\d{4})/(\d{4})/(\d{8})", parsed.path, re.I)
        if match and match[1] + match[2] == match[3]:
            candidate = f"{match[3][:4]}-{match[3][4:6]}-{match[3][6:8]}"
    elif host == "static.cninfo.com.cn":
        match = re.search(r"/finalpage/(\d{4}-\d{2}-\d{2})/", parsed.path, re.I)
        if match:
            candidate = match[1]
    candidate = candidate or str(supplied_date or "").strip()[:10]
    try:
        return date.fromisoformat(candidate).isoformat()
    except ValueError:
        return "未核实"


def align_listing_gap(checks: list[dict], limitations: list[str]) -> list[str]:
    """Do not let stale C8 prose contradict a downgraded evidence state."""
    listing = next((item for item in checks if item.get("id") == "C8"), None)
    if not listing or listing.get("evidence_state") != "证据不足":
        return limitations
    listing["finding"] = "候选页未提供可复核的上市/IPO日期或已上市年限直接证据，须补证后判断。"
    source_id = (listing.get("source_ids") or ["S1"])[0]
    listing["basis"] = f"未取得可在所给原文复核的上市年限直接引文，不能凭报告标题、证券代码或长期上市常识判定未触发。[{source_id}]"
    listing["evidence_quote"] = ""
    listing["evidence_quotes"] = []
    listing["proof_type"] = ""
    listing["disproven_condition"] = ""
    listing["disproof"] = {}
    kept = [item for item in limitations if not re.search(r"(?i)(?<![A-Za-z0-9])C8(?!\d)|次新股", item)]
    kept.append("C8次新股项：候选页未提供可复核上市/IPO日期或年限直接证据，保留证据不足，须补证后判断。")
    return kept


def normalize_report(data: dict, *, company_name: str, stock_code: str, industry: str, screening_date: str) -> dict:
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    ticker = ticker_of(stock_code)
    meta = {
        "company_name": str(meta.get("company_name") or company_name),
        "full_name": str(meta.get("full_name") or company_name),
        "ticker": str(meta.get("ticker") or ticker),
        "industry": str(meta.get("industry") or industry or "未标注"),
        "screening_date": screening_date,
        "data_cutoff": str(meta.get("data_cutoff") or f"{screening_date}（以本期定期报告及已提取财务数据为准）"),
        "executor": str(meta.get("executor") or "财报经营分析助手"),
        "reviewer": str(meta.get("reviewer") or "待复核"),
    }
    sources = data.get("sources") if isinstance(data.get("sources"), list) else []
    clean_sources = []
    for item in sources:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("id") or "").strip()
        url = str(item.get("url") or "").strip()
        if not re.fullmatch(r"S\d+", sid) or not url.startswith(("http://", "https://")):
            continue
        clean_sources.append(
            {
                "id": sid,
                "title": str(item.get("title") or "来源").strip() or "来源",
                "url": url,
                "published_at": source_publication_date(url, item.get("published_at") or ""),
                "used_for": str(item.get("used_for") or "定期报告与财务数据").strip() or "定期报告",
            }
        )
    if not clean_sources:
        clean_sources = [
            {
                "id": "S1",
                "title": f"{company_name}定期报告检索（检索入口非直接证据）",
                "url": cninfo_search_url(stock_code),
                "published_at": "未核实",
                "used_for": "本期定期报告全文与公告检索",
            }
        ]
    source_ids = {item["id"] for item in clean_sources}
    default_sid = clean_sources[0]["id"]
    raw_checks = {str(item.get("id")): item for item in data.get("checks") or [] if isinstance(item, dict)}
    checks = []
    for cid in CHECK_ORDER:
        item = raw_checks.get(cid) or {}
        supplied_ids = [sid for sid in (item.get("source_ids") or []) if sid in source_ids]
        ids = supplied_ids or [default_sid]
        finding = str(item.get("finding") or "").strip()
        basis = str(item.get("basis") or "").strip()
        outcome = _normalize_outcome(item.get("evidence_state") or item.get("outcome"))
        # A source link alone is not evidence; missing checks and vague defaults
        # must never become a positive finding through JSON repair/normalization.
        if not finding or not basis or not supplied_ids:
            outcome = "证据不足"
        if outcome != "通过（不适用）" and INSUFFICIENT_RE.search(finding + " " + basis) and not (outcome == "通过" and _valid_and_disproof(item)):
            outcome = "证据不足"
        if not finding:
            finding = "现有材料不足以完成该项阈值核验。"
        checks.append(
            {
                "id": cid,
                "name": CHECK_NAMES[cid],
                "outcome": outcome,
                "evidence_state": EVIDENCE_STATES[outcome],
                "threshold": str(item.get("threshold") or THRESHOLDS[cid]).strip() or THRESHOLDS[cid],
                "finding": finding,
                "basis": _ensure_citation(basis, ids[0]),
                "source_ids": ids,
                "evidence_quote": str(item.get("evidence_quote") or "").strip(),
                "evidence_quotes": _evidence_quotes(item),
                "proof_type": str(item.get("proof_type") or ""),
                "disproven_condition": str(item.get("disproven_condition") or ""),
                "disproof": item.get("disproof") if isinstance(item.get("disproof"), dict) else {},
            }
        )
    hits = [item["id"] for item in checks if item["outcome"] == "高风险"]
    unchecked = [item["id"] for item in checks if item["outcome"] == "证据不足"]
    conclusion = derive_conclusion(hits, unchecked)
    if hits:
        one_line = f"淘汰：命中 {'、'.join(hits)}，一票否决；另有{len(unchecked)}项证据不足。"
    elif unchecked:
        one_line = f"待补证：{len(unchecked)}项证据不足；在已核验范围内未触发致命红线，不能据此判定整体通过。"
    else:
        one_line = "已完成19项适用性与阈值核验，未触发致命红线；排雷通过不代表值得投资。"
    limitations = _clean_strings(data.get("limitations")) or [
        "批量排雷依据本期定期报告候选页，不等于人工逐项联网核验。",
        "估值分位、涨跌幅、质押、减持、日均成交若材料未出现，不因此判高风险。",
        "排雷通过只表示未发现框架定义的致命风险，不构成投资建议。",
    ]
    limitations = align_listing_gap(checks, limitations)
    return {
        "meta": meta,
        "review_schema": "evidence-review-v8.1",
        "one_line_conclusion": one_line,
        "scope": str(data.get("scope") or "以本期定期报告全文、已提取财务指标为主；行情、质押、减持、估值分位未做全网核验。").strip(),
        "snapshot": _clean_snapshot(data.get("snapshot"), conclusion, one_line),
        "checks": checks,
        "financial_tables": _clean_tables(data.get("financial_tables")),
        "observations": _clean_observations(data.get("observations")),
        "recommendations": _clean_strings(data.get("recommendations")),
        "formulas": _clean_formulas(data.get("formulas")),
        "sources": clean_sources,
        "limitations": limitations,
        "conclusion": conclusion,
        "hits": hits,
        "unchecked": unchecked,
        "evidence_counts": {state: sum(item["evidence_state"] == state for item in checks) for state in EVIDENCE_STATES.values()},
        "generation_error": str(data.get("generation_error") or ""),
        "generation_diagnostics": data.get("generation_diagnostics") if isinstance(data.get("generation_diagnostics"), list) else [],
    }


def _archive_fields(data: dict) -> tuple[str, str, int]:
    hits = data.get("hits") or []
    meta = data["meta"]
    symbol = re.sub(r"[^A-Za-z0-9]", "", str(meta.get("ticker") or "").split(".")[0]) or "COMPANY"
    ymd = str(meta.get("screening_date") or "").replace("-", "")
    archive = f"{symbol}-F-{ymd}-{'-'.join(hits)}" if hits else "无需归档"
    review = _add_months(meta["screening_date"], 6) if hits else "不适用"
    return archive, review, len(hits)


def report_to_markdown(data: dict) -> str:
    meta = data["meta"]
    conclusion = data["conclusion"]
    by_id = {item["id"]: item for item in data["checks"]}
    hits = data.get("hits") or []
    unchecked = data.get("unchecked") or []
    high_count = len(hits)
    pass_count = sum(item["outcome"] in {"通过", "通过（不适用）"} for item in data["checks"])
    archive, review, _ = _archive_fields(data)
    decisive = (
        f"触发 {'、'.join(hits)}｜严格执行一票否决"
        if hits
        else (f"{len(unchecked)}项证据不足｜补证后再做整体判断" if unchecked else "19项已核验｜未触发致命红线")
    )
    lines = [
        "# 目标公司致命风险排雷报告",
        "",
        "**V3.0 精简版框架｜开题前快速过滤**",
        "",
        f"## {meta['company_name']}",
        "",
        f"{meta['ticker']}｜{meta['full_name']}｜{meta['industry']}",
        "",
        f"> **最终结论：{conclusion}**  ",
        f"> {decisive}",
        "",
        "| 检查总数 | 已核验触发 | 已核验未触发/不适用 | 证据不足 |",
        "|---|---|---|---|",
        f"| 19项 | {high_count}项 | {pass_count}项 | {len(unchecked)}项 |",
        "",
        f"**一句话结论：** {data['one_line_conclusion']}",
        "",
        f"- 档案编号：{archive}",
        f"- 筛查日期：{meta['screening_date']}",
        f"- 建议复核日：{review}",
        f"- 数据截止：{meta['data_cutoff']}",
        "",
        "## 01｜执行摘要",
        "",
        "### 决策卡",
        "",
        "| 维度 | 结论 | 核心依据 |",
        "|---|---|---|",
    ]
    for label, ids in (("行业层", ["H1", "H2"]), ("公司层", [f"C{i}" for i in range(1, 12)]), ("量化层", [f"Q{i}" for i in range(1, 7)])):
        layer_hits = [cid for cid in ids if by_id[cid]["outcome"] == "高风险"]
        gaps = [cid for cid in ids if by_id[cid]["outcome"] == "证据不足"]
        result = "高风险" if layer_hits else ("证据不足" if gaps else "已核验未触发")
        basis = "命中 " + "、".join(layer_hits) if layer_hits else ("待补证 " + "、".join(gaps) if gaps else "适用项完成核验，未触发致命红线")
        lines.append(f"| {label} | {result} | {_cell(basis)} |")
    lines.append(f"| 最终处置 | {conclusion} | {'一票否决并冻结6个月' if hits else ('补齐证据后复核' if unchecked else '可进入深度研究阶段')} |")
    lines.extend(["", "### 研究范围", "", str(data.get("scope") or ""), "", "### 公司快照", ""])
    snapshot = data.get("snapshot") or []
    if snapshot:
        lines.extend(["| 项目 | 数据 | 判断/口径 |", "|---|---|---|"])
        for item in snapshot:
            lines.append(f"| {_cell(item['label'])} | {_cell(item['value'])} | {_cell(item['note'])} |")
        lines.append("")
    else:
        lines.extend(["未提供快照；核心数据见逐项检查与财务表。", ""])

    layers = [
        ("02｜第一层：行业致命风险", ["H1", "H2"]),
        ("03｜第二层：公司致命风险红线", [f"C{i}" for i in range(1, 12)]),
        ("04｜第三层：关键定量底线", [f"Q{i}" for i in range(1, 7)]),
    ]
    for title, ids in layers:
        lines.extend([f"## {title}", "", "| 编号 | 检查项 | 结果 | 阈值核验与依据 |", "|---|---|---|---|"])
        for cid in ids:
            check = by_id[cid]
            lines.append(
                f"| {cid} | {check['name']} | {check.get('evidence_state', EVIDENCE_STATES.get(check['outcome'], '证据不足'))} | {_cell(check['finding'])} {_cell(check['basis'])} |"
            )
        lines.append("")
        for cid in ids:
            check = by_id[cid]
            lines.append(f"### {cid}｜{check['name']}")
            lines.append("")
            lines.append(f"**结论：{check.get('evidence_state', EVIDENCE_STATES.get(check['outcome'], '证据不足'))}**")
            lines.append("")
            lines.append(f"- 红线：{check['threshold']}")
            lines.append(f"- 实测：{check['finding']}")
            lines.append(f"- 依据：{check['basis']}")
            lines.append("")

    tables = data.get("financial_tables") or []
    if tables:
        lines.extend(["## 05｜财务与经营质量", ""])
        for table in tables:
            lines.append(f"### {table['title']}")
            lines.append("")
            cols = table["columns"]
            lines.append("| " + " | ".join(_cell(col) for col in cols) + " |")
            lines.append("|" + "|".join(["---"] * len(cols)) + "|")
            for row in table["rows"]:
                lines.append("| " + " | ".join(_cell(cell) for cell in row) + " |")
            lines.append("")

    lines.extend(["## 06｜补充黄灯与后续验证", ""])
    observations = data.get("observations") or []
    if observations:
        for item in observations:
            lines.append(f"**{item['title']}**")
            lines.append("")
            lines.append(item["detail"])
            lines.append("")
            lines.append(f"- 监控/验证：{item['monitor']}")
            lines.append("")
    else:
        lines.extend(["未列示额外黄灯；不代表公司不存在一般风险。", ""])
    lines.append("### 处置建议")
    lines.append("")
    recs = data.get("recommendations") or []
    if recs:
        for item in recs:
            lines.append(f"- {item}")
    elif hits:
        lines.append("- 归档冻结 6 个月，期内仅做低成本事件跟踪。")
    elif unchecked:
        lines.append("- 优先补齐证据不足项目的适用期间、原始数据及官方来源，再作整体风险判断。")
    else:
        lines.append("- 可进入深度研究；仍须验证商业质量、竞争优势、治理、估值与收益风险比。")
    lines.append("")
    if hits:
        lines.append(f"> **冻结规则：** 归档编号 {archive}；常规冻结至 {review}。冻结期内仅做低成本事件跟踪。")
    elif unchecked:
        lines.append("> **补证优先：** 当前排雷尚未完成全部核验，证据不足不代表低风险。")
    else:
        lines.append("> **进入深度研究：** 排雷通过不代表值得投资；下一阶段仍须验证商业质量、竞争优势、治理、估值与收益风险比。")
    lines.extend(
        [
            "",
            "## 07｜最终排雷结论卡",
            "",
            f"> **最终结论：{conclusion}**  ",
            f"> 19项硬性检查中命中{high_count}项高风险。"
            + ("按一票否决原则，其他通过项不能抵销。" if hits else (f"另有{len(unchecked)}项证据不足，暂不能整体判定通过。" if unchecked else "适用项已核验，未触发致命红线。")),
            "",
            "| 编号 | 检查项 | 结果 | 依据摘要 |",
            "|---|---|---|---|",
        ]
    )
    for cid in CHECK_ORDER:
        check = by_id[cid]
        lines.append(f"| {cid} | {check['name']} | {check.get('evidence_state', EVIDENCE_STATES.get(check['outcome'], '证据不足'))} | {_cell(check['finding'])} |")
    lines.extend(["", "## 08｜来源、公式与限制", "", "### 主要来源", ""])
    for source in sorted(data.get("sources") or [], key=lambda item: int(str(item.get("id") or "S0")[1:] or 0)):
        lines.append(
            f"- **[{source['id']}] [{source['title']}]({source['url']})**"
            f"（发布/报告期：{source['published_at']}；用于：{source['used_for']}）"
        )
    formulas = data.get("formulas") or []
    if formulas:
        lines.extend(["", "### 核心公式", "", "| 指标 | 公式/口径 |", "|---|---|"])
        for item in formulas:
            lines.append(f"| {_cell(item['name'])} | {_cell(item['formula'])} |")
    lines.extend(["", "### 限制与免责声明", ""])
    for item in data.get("limitations") or []:
        lines.append(f"- {item}")
    lines.append("- 本报告用于研究立项前快速排雷，不构成证券投资建议、估值结论或买卖依据。")
    lines.extend(["", f"**END｜严格框架结论：{conclusion}**"])
    return "\n".join(lines)


def try_build_docx(data: dict, output: Path) -> tuple[Path | None, str]:
    script_dir = SCREENING_DIR / "scripts"
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    try:
        import build_report
    except Exception as error:
        return None, f"无法加载 Word 模板脚本：{error}"
    try:
        derived = build_report.validate(data)
        build_report.build(data, derived, output)
        if output.is_file():
            return output, ""
        return None, "Word 文件未写出。"
    except Exception as error:
        log_path = output.with_suffix(".docx.error.txt")
        log_path.write_text(f"{type(error).__name__}: {error}", encoding="utf-8")
        return None, str(error)


def screen_full(
    *,
    company_name: str,
    stock_code: str,
    report_type: str,
    report_year: int,
    metrics: dict[str, str],
    evidence_text: str,
    source_url: str,
    output_dir: Path,
    api_key: str,
    model: str,
    base_url: str,
    test_mode: bool,
    industry: str = "",
    disclosure_date: str = "",
) -> dict:
    screening_date = date.today().isoformat()
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r'[\\/:*?"<>|]', "_", f"{stock_code}_{company_name}_致命风险排雷报告_{screening_date.replace('-', '')}")[:110]
    json_path = output_dir / f"{stem}.json"
    md_path = output_dir / f"{stem}.md"
    docx_path = output_dir / f"{stem}.docx"
    source = {
        "id": "S1",
        "title": f"{company_name}{report_year}年{report_type}",
        "url": source_url if str(source_url).startswith("http") else cninfo_search_url(stock_code),
        "published_at": source_publication_date(source_url, disclosure_date),
        "used_for": "本期定期报告全文",
    }
    if test_mode or not api_key.strip() or not (evidence_text or "").strip():
        note = "测试模式未调用模型" if test_mode else ("未填写 API Key" if not api_key.strip() else "没有可用原文")
        data = normalize_report(
            {
                "generation_error": note,
                "sources": [source],
                "checks": [_blank_check(cid) for cid in CHECK_ORDER],
                "limitations": [note, "批量排雷未做全网核验。"],
            },
            company_name=company_name,
            stock_code=stock_code,
            industry=industry,
            screening_date=screening_date,
        )
    else:
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=120.0, max_retries=1)
        metric_lines = "\n".join(f"- {key}: {value}" for key, value in (metrics or {}).items()) or "- 无结构化财务数据"
        system_prompt = (
            "你按上市公司致命风险排雷 V3.0 精简版框架输出 JSON，供 Word 构建脚本使用。"
            "报告版式对齐「目标公司致命风险排雷报告」：封面结论卡、01执行摘要决策卡、02行业层、03公司层、04量化层、05财务表、06黄灯、07结论卡、08来源。"
            "19项 ID 必须齐全：H1,H2,C1-C11,Q1-Q6。每项evidence_state只能是已核验未触发、已核验触发、证据不足、不适用。"
            "outcome对应为通过、高风险、证据不足、通过（不适用），用于兼容输出。"
            "一票否决：已核验触发不得被其他优点抵销。AND条件全部成立才触发；任一必要条件有可复查证据为假即可已核验未触发，其他条件缺资料不妨碍该反证。"
            "OR条件任一成立即可触发；判未触发必须排除全部子条件。不能因OR其中一支为假而整体通过。"
            "已核验必须有适用期间、口径和直接原文。AND反证用proof_type=and_condition_disproved，并写disproven_condition；全部核验用all_conditions_verified，OR全部排除用or_all_conditions_disproved。"
            "Q1资产负债率、Q4商誉/净资产、Q5应收/收入的AND反证须给disproof对象：numerator,denominator,ratio_pct,threshold_pct,period,unit,numerator_quote,denominator_quote；阈值分别80/50/40。分子分母原文可跨页分开引用。"
            "例如Q1本期资产负债率40%已足以否定>80%，不必再要求连续两年趋势；Q5应收/收入14%已否定>40%，不必再要求一年以上账龄。其他未取得数据只写限制，不将该已反证AND降为不足。"
            "无法完成全部触发条件或必要条件反证时才标证据不足，说明需补哪份来源。"
            "未查到、未提取、未见硬阈值命中绝不等同已核验未触发；不能把搜索入口当直接来源。"
            "Q3 在累计净利润≤0时用 通过（不适用）。C8 上市已满2-3年写通过。"
            "C8通过引文必须实际记载IPO/上市日期或已上市年限，报告标题、证券代码、持续披露报告均不能证明上市年限，不得靠常识填入。"
            "各节finding、limitations和结论卡必须与最终evidence_state一致；C8无直接上市证据时不得在说明中改称长期上市、已通过或已排除风险。"
            "来源published_at表示所引用文件的实际公开披露日，不是董事会批准日、报告期末或screening_date；未知写未核实。"
            "银行保险的工业企业杠杆、应收收入及经营现金流指标须按行业判适用性，不适用必须具体说明。"
            "引用仅用提供的S1及其中的PDF页码，不能创造来源、页码、行情、政策、减持或审计事实。"
            "已核验项必须提供8-60字的evidence_quote，逐字来自所给原文；finding说明期间、口径与计算。证据不足项quote为空。"
            "黄灯只能进 observations，且每项必须有 title、detail、monitor，不能改变硬结论。"
            "sources 至少含 S1，url 必须是 http(s)。financial_tables 列数 2-6，rows 必须与 columns 对齐。"
        )
        if ticker_of(stock_code).endswith(".HK"):
            system_prompt += "\n" + HK_EXTRACTION_RULES
        user_prompt = f"""公司：{company_name}（{stock_code}）
报告：{report_year}年{report_type}
披露日：{disclosure_date or "未知"}
S1 URL：{source["url"]}

结构化财务数据：
{metric_lines}

候选原文：
{compact_risk_evidence(evidence_text, max_chars=32000)}

框架：
{_framework_text()}

输出 JSON，字段：meta(company_name,full_name,ticker,industry,screening_date,data_cutoff,executor,reviewer),
one_line_conclusion, scope, snapshot[{{label,value,note}}],
checks[{{id,name,outcome,evidence_state,threshold,finding,basis,source_ids,evidence_quote,evidence_quotes,proof_type,disproven_condition,disproof}}],
observations[{{title,detail,monitor}}], recommendations, formulas[{{name,formula}}], sources, limitations。
financial_tables[{{title,columns,rows}}]，列数2-6。
screening_date 用 {screening_date}。
"""
        generation_diagnostics = []
        try:
            raw = _generate_complete_review(client, model=model, system_prompt=system_prompt,
                                            user_prompt=user_prompt, diagnostics=generation_diagnostics)
            raw["generation_diagnostics"] = generation_diagnostics
            # The model cannot add external evidence that this pipeline never
            # retrieved. Unknown source IDs are subsequently marked insufficient.
            raw["sources"] = [source]
            raw["checks"] = [validate_check_evidence(check, evidence_text) for check in raw["checks"]]
            data = normalize_report(
                raw,
                company_name=company_name,
                stock_code=stock_code,
                industry=industry,
                screening_date=screening_date,
            )
        except Exception as error:
            data = normalize_report(
                {
                    "generation_error": f"排雷生成失败：{error}",
                    "generation_diagnostics": generation_diagnostics,
                    "sources": [source],
                    "checks": [_blank_check(cid) for cid in CHECK_ORDER],
                    "limitations": [str(error)],
                },
                company_name=company_name,
                stock_code=stock_code,
                industry=industry,
                screening_date=screening_date,
            )
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown = report_to_markdown(data)
    md_path.write_text(markdown, encoding="utf-8")
    built, docx_error = try_build_docx(data, docx_path)
    failed = bool(data.get("generation_error"))
    return {
        "stock_code": stock_code,
        "review_schema": "evidence-review-v8.1",
        "company_name": company_name,
        "report_type": report_type,
        "report_year": report_year,
        "conclusion": data["conclusion"],
        "hits": data.get("hits") or [],
        "unchecked": data.get("unchecked") or [],
        "evidence_counts": data.get("evidence_counts") or {},
        "generation_diagnostics": data.get("generation_diagnostics") or [],
        "note": data["one_line_conclusion"],
        "json_path": str(json_path),
        "path": str(md_path),
        "docx_path": str(built) if built else "",
        "docx_error": docx_error,
        "status": "失败" if failed else "完成",
        "retryable": failed,
        "message": (data.get("generation_error") or data["one_line_conclusion"])[:160],
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def risk_tag_class(conclusion: str) -> str:
    if conclusion in {"淘汰", "暂定淘汰"}:
        return "risk-kill"
    if conclusion in {"通过", "暂定通过"}:
        return "risk-pass"
    return "risk-gap"


def risk_label_html(conclusion: str, hits: list[str], note: str) -> str:
    klass = risk_tag_class(conclusion)
    hit_html = ""
    if hits:
        hit_html = (
            "<span class='pick-tag "
            + klass
            + "'>命中 "
            + escape("、".join(str(x) for x in hits))
            + "</span>"
        )
    body = escape((note or "").strip() or "—")
    return (
        "<div class='pick-row'><div class='pick-label'>排雷意见</div>"
        "<div class='pick-tags'><span class='pick-tag "
        + klass
        + "'>"
        + escape(conclusion or "未完成")
        + "</span>"
        + hit_html
        + "</div><div class='pick-body'>"
        + body
        + "</div></div>"
    )
