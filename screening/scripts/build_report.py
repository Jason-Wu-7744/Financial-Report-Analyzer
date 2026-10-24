#!/usr/bin/env python3
"""Build a validated Chinese listed-company red-flag screening DOCX from JSON."""

from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_ALIGN_VERTICAL, WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Pt, RGBColor


CHECK_NAMES = {
    "H1": "行业需求不可逆萎缩", "H2": "行业面临政策致命风险",
    "C1": "财务真实性存疑", "C2": "资金链断裂风险", "C3": "政策一招致命",
    "C4": "管理层诚信缺陷", "C5": "极度高估", "C6": "短期暴涨",
    "C7": "价值陷阱", "C8": "次新股", "C9": "资本黑洞",
    "C10": "纯概念蹭风口", "C11": "流动性与退市风险",
    "Q1": "资产负债率红线", "Q2": "现金流红线", "Q3": "利润质量红线",
    "Q4": "商誉暴雷风险", "Q5": "应收账款恶化", "Q6": "大股东减持信号",
}
CHECK_ORDER = list(CHECK_NAMES)
ALLOWED_OUTCOMES = {"通过", "高风险", "通过（不适用）", "证据不足"}

NAVY = "103E59"
BLUE = "1B6585"
LIGHT_BLUE = "E8F1F5"
GREEN = "147A4B"
LIGHT_GREEN = "E7F4EC"
RED = "C5281C"
LIGHT_RED = "FCE9E7"
AMBER = "B85C00"
LIGHT_AMBER = "FFF1DE"
GRAY = "667085"
LIGHT_GRAY = "F4F6F8"
WHITE = "FFFFFF"
BLACK = "1F2933"
FONT_CN = "Microsoft YaHei"
FONT_LATIN = "Aptos"
USABLE_DXA = 9835  # A4 with 1.8 cm margins


def fail(message: str) -> None:
    raise ValueError(message)


def require_text(obj: dict, key: str, where: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        fail(f"{where}.{key} must be a non-empty string")
    return value.strip()


def add_months(iso_date: str, months: int) -> str:
    y, m, d = map(int, iso_date.split("-"))
    total = y * 12 + (m - 1) + months
    ny, nm = divmod(total, 12)
    nm += 1
    month_days = [31, 29 if ny % 4 == 0 and (ny % 100 != 0 or ny % 400 == 0) else 28,
                  31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return date(ny, nm, min(d, month_days[nm - 1])).isoformat()


def validate(data: dict) -> dict:
    if not isinstance(data, dict):
        fail("root must be an object")
    meta = data.get("meta")
    if not isinstance(meta, dict):
        fail("meta must be an object")
    for key in ("company_name", "full_name", "ticker", "industry", "screening_date",
                "data_cutoff", "executor", "reviewer"):
        require_text(meta, key, "meta")
    try:
        date.fromisoformat(meta["screening_date"])
    except Exception as exc:
        fail(f"meta.screening_date must be YYYY-MM-DD: {exc}")

    require_text(data, "one_line_conclusion", "root")
    require_text(data, "scope", "root")
    checks = data.get("checks")
    if not isinstance(checks, list) or len(checks) != 19:
        fail("checks must contain exactly 19 items")
    by_id = {}
    for idx, check in enumerate(checks):
        where = f"checks[{idx}]"
        if not isinstance(check, dict):
            fail(f"{where} must be an object")
        cid = require_text(check, "id", where)
        if cid not in CHECK_NAMES or cid in by_id:
            fail(f"{where}.id is unknown or duplicated: {cid}")
        name = require_text(check, "name", where)
        if name != CHECK_NAMES[cid]:
            fail(f"{cid} name must be {CHECK_NAMES[cid]}")
        outcome = require_text(check, "outcome", where)
        if outcome not in ALLOWED_OUTCOMES:
            fail(f"{cid} outcome must be one of {sorted(ALLOWED_OUTCOMES)}")
        for key in ("threshold", "finding", "basis"):
            require_text(check, key, where)
        source_ids = check.get("source_ids")
        if not isinstance(source_ids, list) or not source_ids or not all(isinstance(v, str) and v for v in source_ids):
            fail(f"{cid}.source_ids must be a non-empty string array")
        by_id[cid] = check
    missing = [cid for cid in CHECK_ORDER if cid not in by_id]
    if missing:
        fail(f"missing checks: {', '.join(missing)}")

    sources = data.get("sources")
    if not isinstance(sources, list) or not sources:
        fail("sources must be a non-empty array")
    source_ids = set()
    for idx, source in enumerate(sources):
        where = f"sources[{idx}]"
        if not isinstance(source, dict):
            fail(f"{where} must be an object")
        sid = require_text(source, "id", where)
        if not re.fullmatch(r"S\d+", sid) or sid in source_ids:
            fail(f"{where}.id must be unique and match S<number>")
        source_ids.add(sid)
        for key in ("title", "url", "published_at", "used_for"):
            require_text(source, key, where)
        if urlparse(source["url"]).scheme not in {"http", "https"}:
            fail(f"{sid}.url must be http(s)")
    for cid, check in by_id.items():
        unknown = set(check["source_ids"]) - source_ids
        if unknown:
            fail(f"{cid} refers to unknown sources: {sorted(unknown)}")

    snapshot = data.get("snapshot", [])
    if not isinstance(snapshot, list):
        fail("snapshot must be an array")
    for idx, item in enumerate(snapshot):
        if not isinstance(item, dict):
            fail(f"snapshot[{idx}] must be an object")
        for key in ("label", "value", "note"):
            require_text(item, key, f"snapshot[{idx}]")

    for group in ("observations", "recommendations", "formulas", "limitations", "financial_tables"):
        if group in data and not isinstance(data[group], list):
            fail(f"{group} must be an array")
    for idx, table in enumerate(data.get("financial_tables", [])):
        if not isinstance(table, dict):
            fail(f"financial_tables[{idx}] must be an object")
        require_text(table, "title", f"financial_tables[{idx}]")
        cols, rows = table.get("columns"), table.get("rows")
        if not isinstance(cols, list) or not 2 <= len(cols) <= 6 or not all(isinstance(x, str) for x in cols):
            fail(f"financial_tables[{idx}].columns must contain 2-6 strings")
        if not isinstance(rows, list) or not rows or any(not isinstance(r, list) or len(r) != len(cols) for r in rows):
            fail(f"financial_tables[{idx}].rows must match column count")

    fatal_ids = [cid for cid in CHECK_ORDER if by_id[cid]["outcome"] == "高风险"]
    unchecked = [cid for cid in CHECK_ORDER if by_id[cid]["outcome"] == "证据不足"]
    conclusion = "淘汰" if fatal_ids else ("待补证" if unchecked else "通过")
    symbol = re.sub(r"[^A-Za-z0-9]", "", meta["ticker"].split(".")[0]) or "COMPANY"
    ymd = meta["screening_date"].replace("-", "")
    archive_code = f"{symbol}-F-{ymd}-{'-'.join(fatal_ids)}" if fatal_ids else "无需归档"
    return {
        "meta": meta, "by_id": by_id, "fatal_ids": fatal_ids, "conclusion": conclusion,
        "unchecked": unchecked,
        "archive_code": archive_code,
        "review_date": add_months(meta["screening_date"], 6) if fatal_ids else "不适用",
    }


def set_run_font(run, size=10.5, bold=False, color=BLACK, latin=FONT_LATIN, cn=FONT_CN):
    run.font.name = latin
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = RGBColor.from_string(color)
    rpr = run._element.get_or_add_rPr()
    fonts = rpr.rFonts
    if fonts is None:
        fonts = OxmlElement("w:rFonts")
        rpr.insert(0, fonts)
    fonts.set(qn("w:ascii"), latin)
    fonts.set(qn("w:hAnsi"), latin)
    fonts.set(qn("w:eastAsia"), cn)
    return run


def set_cell_shading(cell, color):
    tcpr = cell._tc.get_or_add_tcPr()
    shd = tcpr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tcpr.append(shd)
    shd.set(qn("w:fill"), color)


def set_cell_margins(cell, top=100, start=120, bottom=100, end=120):
    tcpr = cell._tc.get_or_add_tcPr()
    tc_mar = tcpr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tcpr.append(tc_mar)
    for tag, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = tc_mar.find(qn(f"w:{tag}"))
        if node is None:
            node = OxmlElement(f"w:{tag}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def set_table_geometry(table, widths):
    if abs(sum(widths) - USABLE_DXA) > 2:
        fail(f"table widths must sum to {USABLE_DXA}, got {sum(widths)}")
    table.autofit = False
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    tblpr = table._tbl.tblPr
    tblw = tblpr.first_child_found_in("w:tblW")
    tblw.set(qn("w:w"), str(USABLE_DXA)); tblw.set(qn("w:type"), "dxa")
    tblind = tblpr.first_child_found_in("w:tblInd")
    if tblind is None:
        tblind = OxmlElement("w:tblInd"); tblpr.append(tblind)
    tblind.set(qn("w:w"), "120"); tblind.set(qn("w:type"), "dxa")
    grid = table._tbl.tblGrid
    for child in list(grid):
        grid.remove(child)
    for width in widths:
        col = OxmlElement("w:gridCol"); col.set(qn("w:w"), str(width)); grid.append(col)
    for row in table.rows:
        for cell, width in zip(row.cells, widths):
            tcw = cell._tc.get_or_add_tcPr().first_child_found_in("w:tcW")
            tcw.set(qn("w:w"), str(width)); tcw.set(qn("w:type"), "dxa")
            cell.width = Inches(width / 1440)
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            set_cell_margins(cell)


def repeat_header(row):
    trpr = row._tr.get_or_add_trPr()
    tbl_header = OxmlElement("w:tblHeader")
    tbl_header.set(qn("w:val"), "true")
    trpr.append(tbl_header)


def no_split(row):
    trpr = row._tr.get_or_add_trPr()
    cant = OxmlElement("w:cantSplit")
    trpr.append(cant)


def add_cell_text(cell, text, *, bold=False, color=BLACK, size=9.3, align=WD_ALIGN_PARAGRAPH.LEFT):
    cell.text = ""
    p = cell.paragraphs[0]
    p.alignment = align
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = 1.12
    set_run_font(p.add_run(str(text)), size=size, bold=bold, color=color)


def add_table(doc, headers, rows, widths, outcome_col=None):
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    for i, header in enumerate(headers):
        cell = table.rows[0].cells[i]
        set_cell_shading(cell, NAVY)
        add_cell_text(cell, header, bold=True, color=WHITE, size=9.3, align=WD_ALIGN_PARAGRAPH.CENTER)
    repeat_header(table.rows[0])
    for row_data in rows:
        row = table.add_row()
        no_split(row)
        for i, value in enumerate(row_data):
            cell = row.cells[i]
            if i == 0:
                set_cell_shading(cell, LIGHT_BLUE)
            if outcome_col == i:
                value_text = str(value)
                if value_text in {"高风险", "已核验触发"}:
                    set_cell_shading(cell, LIGHT_RED); color = RED
                elif value_text in {"待补证", "证据不足"}:
                    set_cell_shading(cell, LIGHT_AMBER); color = AMBER
                elif value_text.startswith("通过") or value_text in {"已核验未触发", "不适用"}:
                    set_cell_shading(cell, LIGHT_GREEN); color = GREEN
                else:
                    color = BLACK
                add_cell_text(cell, value_text, bold=True, color=color, align=WD_ALIGN_PARAGRAPH.CENTER)
            else:
                align = WD_ALIGN_PARAGRAPH.CENTER if i == 0 else WD_ALIGN_PARAGRAPH.LEFT
                add_cell_text(cell, value, bold=(i == 0), color=BLUE if i == 0 else BLACK, align=align)
    set_table_geometry(table, widths)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)
    return table


def add_heading(doc, text, level=1, page_break=False):
    p = doc.add_paragraph(style=f"Heading {level}")
    p.paragraph_format.page_break_before = page_break
    # Do not bind a level-1 heading to an entire following table. LibreOffice can
    # otherwise pull a heading above the printable top when the table spans pages.
    p.paragraph_format.keep_with_next = level > 1
    p.paragraph_format.space_before = Pt(10 if level == 1 else 7)
    p.paragraph_format.space_after = Pt(5)
    size = 23 if level == 1 else 15
    set_run_font(p.add_run(text), size=size, bold=True, color=NAVY)
    return p


def add_body(doc, text, *, bold_prefix=None, color=BLACK, size=10.5):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(5)
    p.paragraph_format.line_spacing = 1.25
    if bold_prefix and str(text).startswith(bold_prefix):
        set_run_font(p.add_run(bold_prefix), size=size, bold=True, color=color)
        set_run_font(p.add_run(str(text)[len(bold_prefix):]), size=size, color=color)
    else:
        set_run_font(p.add_run(str(text)), size=size, color=color)
    return p


def add_bullet(doc, text):
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.line_spacing = 1.2
    set_run_font(p.add_run(str(text)), size=10.2)
    return p


def add_callout(doc, title, text, kind="info"):
    palette = {
        "danger": (LIGHT_RED, RED), "warning": (LIGHT_AMBER, AMBER),
        "success": (LIGHT_GREEN, GREEN), "info": (LIGHT_BLUE, BLUE),
    }
    fill, color = palette[kind]
    table = doc.add_table(rows=1, cols=1)
    cell = table.cell(0, 0); set_cell_shading(cell, fill); set_cell_margins(cell, 150, 180, 150, 180)
    cell.text = ""
    p = cell.paragraphs[0]; p.paragraph_format.space_after = Pt(2)
    set_run_font(p.add_run(title), size=11.5, bold=True, color=color)
    p2 = cell.add_paragraph(); p2.paragraph_format.space_after = Pt(0); p2.paragraph_format.line_spacing = 1.2
    set_run_font(p2.add_run(text), size=10.2)
    set_table_geometry(table, [USABLE_DXA])
    doc.add_paragraph().paragraph_format.space_after = Pt(0)
    return table


def add_hyperlink(paragraph, text, url):
    part = paragraph.part
    rid = part.relate_to(url, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink", is_external=True)
    link = OxmlElement("w:hyperlink"); link.set(qn("r:id"), rid)
    run = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    color = OxmlElement("w:color"); color.set(qn("w:val"), BLUE)
    underline = OxmlElement("w:u"); underline.set(qn("w:val"), "single")
    rfonts = OxmlElement("w:rFonts"); rfonts.set(qn("w:ascii"), FONT_LATIN); rfonts.set(qn("w:hAnsi"), FONT_LATIN); rfonts.set(qn("w:eastAsia"), FONT_CN)
    sz = OxmlElement("w:sz"); sz.set(qn("w:val"), "20")
    rpr.extend([rfonts, color, underline, sz])
    text_node = OxmlElement("w:t"); text_node.text = text
    run.extend([rpr, text_node]); link.append(run); paragraph._p.append(link)


def add_page_field(paragraph):
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = paragraph.add_run()
    fld_begin = OxmlElement("w:fldChar"); fld_begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText"); instr.set(qn("xml:space"), "preserve"); instr.text = " PAGE "
    fld_end = OxmlElement("w:fldChar"); fld_end.set(qn("w:fldCharType"), "end")
    run._r.extend([fld_begin, instr, fld_end])
    set_run_font(run, size=8.5, color=GRAY)


def configure_document(doc, meta):
    sec = doc.sections[0]
    sec.page_width = Cm(21); sec.page_height = Cm(29.7)
    sec.top_margin = Cm(1.8); sec.bottom_margin = Cm(1.7)
    sec.left_margin = Cm(1.8); sec.right_margin = Cm(1.8)
    sec.header_distance = Cm(0.8); sec.footer_distance = Cm(0.8)
    normal = doc.styles["Normal"]
    normal.font.name = FONT_LATIN; normal.font.size = Pt(10.5)
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), FONT_CN)
    for style_name in ("Title", "Subtitle", "Heading 1", "Heading 2", "Heading 3"):
        style = doc.styles[style_name]
        style.font.name = FONT_LATIN
        style._element.rPr.rFonts.set(qn("w:eastAsia"), FONT_CN)
    header = sec.header.paragraphs[0]
    header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    set_run_font(header.add_run(f"{meta['ticker']} | 致命风险排雷 | {meta['screening_date']}"), size=8.5, bold=True, color=GRAY)
    footer = sec.footer.paragraphs[0]
    set_run_font(footer.add_run(f"仅供研究立项筛选 | 数据截止 {meta['data_cutoff']}    "), size=8.2, color=GRAY)
    add_page_field(footer)


def build(data: dict, derived: dict, output: Path):
    meta, by_id = derived["meta"], derived["by_id"]
    fatal_ids, conclusion = derived["fatal_ids"], derived["conclusion"]
    unchecked = derived.get("unchecked") or []
    high_count = len(fatal_ids); pass_count = 19 - high_count - len(unchecked)
    doc = Document(); configure_document(doc, meta)

    p = doc.add_paragraph(); p.paragraph_format.space_before = Pt(28); p.paragraph_format.space_after = Pt(3)
    set_run_font(p.add_run("目标公司致命风险排雷报告"), size=28, bold=True, color=NAVY)
    p = doc.add_paragraph(); p.paragraph_format.space_after = Pt(30)
    set_run_font(p.add_run("V3.0 精简版框架｜开题前快速过滤"), size=13, bold=True, color=BLUE)
    p = doc.add_paragraph(); p.paragraph_format.space_after = Pt(2)
    set_run_font(p.add_run(meta["company_name"]), size=31, bold=True, color=BLACK)
    p = doc.add_paragraph(); p.paragraph_format.space_after = Pt(20)
    set_run_font(p.add_run(f"{meta['ticker']}｜{meta['full_name']}｜{meta['industry']}"), size=13, color=GRAY)
    tone = "danger" if fatal_ids else ("warning" if unchecked else "success")
    decisive = (
        f"触发 {', '.join(fatal_ids)}｜严格执行一票否决" if fatal_ids
        else (f"{len(unchecked)}项证据不足｜补证后再作整体判断" if unchecked else "19项已核验｜未触发致命红线")
    )
    add_callout(doc, f"最终结论：{conclusion}", decisive, tone)
    cards = [
        ("19项", "硬性排雷项"), (f"{high_count}项", "高风险命中"),
        (f"{pass_count}项", "已核验未触发/不适用"), (f"{len(unchecked)}项", "证据不足"),
    ]
    add_table(doc, [x[0] for x in cards], [[x[1] for x in cards]], [2459, 2459, 2459, 2458])
    add_callout(doc, "一句话结论", data["one_line_conclusion"], tone)
    add_body(doc, f"档案编号：{derived['archive_code']}", bold_prefix="档案编号：")
    add_body(doc, f"筛查日期：{meta['screening_date']}", bold_prefix="筛查日期：")
    add_body(doc, f"建议复核日：{derived['review_date']}", bold_prefix="建议复核日：")

    add_heading(doc, "01｜执行摘要", page_break=True)
    decision_rows = []
    for label, ids in (("行业层", ["H1", "H2"]), ("公司层", [f"C{i}" for i in range(1, 12)]), ("量化层", [f"Q{i}" for i in range(1, 7)])):
        hits = [cid for cid in ids if by_id[cid]["outcome"] == "高风险"]
        gaps = [cid for cid in ids if by_id[cid]["outcome"] == "证据不足"]
        result = "高风险" if hits else ("证据不足" if gaps else "已核验未触发")
        basis = "命中 " + ", ".join(hits) if hits else ("待补证 " + ", ".join(gaps) if gaps else "适用项完成核验，未触发致命红线")
        decision_rows.append([label, result, basis])
    decision_rows.append(["最终处置", conclusion, "一票否决并冻结6个月" if fatal_ids else ("补齐证据后复核" if unchecked else "可进入深度研究阶段")])
    add_table(doc, ["维度", "结论", "核心依据"], decision_rows, [2100, 2100, 5635], outcome_col=1)
    add_heading(doc, "研究范围", level=2)
    add_body(doc, data["scope"])
    add_heading(doc, "公司快照", level=2)
    snapshot = data.get("snapshot", [])
    if snapshot:
        rows = [[item["label"], item["value"], item["note"]] for item in snapshot]
        add_table(doc, ["项目", "数据", "判断/口径"], rows, [2500, 3000, 4335])
    else:
        add_body(doc, "未提供快照；核心数据见逐项检查与财务表。", color=GRAY)

    layers = [
        ("02｜第一层：行业致命风险", ["H1", "H2"]),
        ("03｜第二层：公司致命风险红线", [f"C{i}" for i in range(1, 12)]),
        ("04｜第三层：关键定量底线", [f"Q{i}" for i in range(1, 7)]),
    ]
    for title, ids in layers:
        add_heading(doc, title, page_break=True)
        rows = []
        for cid in ids:
            check = by_id[cid]
            rows.append([cid, check["name"], check.get("evidence_state", check["outcome"]), f"{check['finding']}\n{check['basis']}"])
        add_table(doc, ["编号", "检查项", "结果", "阈值核验与依据"], rows, [900, 2300, 1800, 4835], outcome_col=2)
        for cid in ids:
            check = by_id[cid]
            add_heading(doc, f"{cid}｜{check['name']}", level=2)
            add_body(doc, f"红线：{check['threshold']}", bold_prefix="红线：", color=GRAY, size=9.8)
            kind = "danger" if check["outcome"] == "高风险" else ("warning" if check["outcome"] == "证据不足" else "success")
            add_callout(doc, f"结论：{check.get('evidence_state', check['outcome'])}", f"{check['finding']} {check['basis']}", kind)

    financial_tables = data.get("financial_tables", [])
    if financial_tables:
        add_heading(doc, "05｜财务与经营质量", page_break=True)
        for item in financial_tables:
            add_heading(doc, item["title"], level=2)
            count = len(item["columns"])
            base = USABLE_DXA // count
            widths = [base] * count; widths[-1] += USABLE_DXA - sum(widths)
            add_table(doc, item["columns"], item["rows"], widths)

    add_heading(doc, "06｜补充黄灯与后续验证", page_break=True)
    observations = data.get("observations", [])
    if observations:
        for item in observations:
            if not isinstance(item, dict):
                fail("each observation must be an object")
            title = require_text(item, "title", "observation")
            detail = require_text(item, "detail", "observation")
            monitor = require_text(item, "monitor", "observation")
            add_callout(doc, title, f"{detail}\n监控/验证：{monitor}", "warning")
    else:
        add_body(doc, "未列示额外黄灯；不代表公司不存在一般风险。", color=GRAY)
    add_heading(doc, "处置建议", level=2)
    for item in data.get("recommendations", []):
        add_bullet(doc, item)
    if fatal_ids:
        add_callout(doc, "冻结规则", f"归档编号 {derived['archive_code']}；常规冻结至 {derived['review_date']}。冻结期内仅做低成本事件跟踪。", "danger")
    elif unchecked:
        add_callout(doc, "补证优先", "当前排雷尚未完成全部核验。优先补齐证据不足项目的期间、口径与官方原始来源，证据不足不代表低风险。", "warning")
    else:
        add_callout(doc, "进入深度研究", "排雷通过不代表值得投资；下一阶段仍须验证商业质量、竞争优势、治理、估值与收益风险比。", "info")

    add_heading(doc, "07｜最终排雷结论卡", page_break=True)
    add_callout(doc, f"最终结论：{conclusion}",
                f"19项硬性检查中命中{high_count}项高风险。" +
                ("按一票否决原则，其他通过项不能抵销。" if fatal_ids else (f"另有{len(unchecked)}项证据不足，暂不能整体判定通过。" if unchecked else "适用项已核验，未触发致命红线。")),
                tone)
    final_rows = [[cid, CHECK_NAMES[cid], by_id[cid].get("evidence_state", by_id[cid]["outcome"]), by_id[cid]["finding"]] for cid in CHECK_ORDER]
    add_table(doc, ["编号", "检查项", "结果", "依据摘要"], final_rows, [900, 2300, 1800, 4835], outcome_col=2)

    add_heading(doc, "08｜来源、公式与限制", page_break=True)
    add_heading(doc, "主要来源", level=2)
    source_sort = lambda s: int(s["id"][1:])
    for source in sorted(data["sources"], key=source_sort):
        p = doc.add_paragraph(); p.paragraph_format.space_after = Pt(4)
        set_run_font(p.add_run(f"[{source['id']}] "), size=10, bold=True, color=NAVY)
        add_hyperlink(p, source["title"], source["url"])
        set_run_font(p.add_run(f"（发布/报告期：{source['published_at']}；用于：{source['used_for']}）"), size=9.5, color=GRAY)
    formulas = data.get("formulas", [])
    if formulas:
        add_heading(doc, "核心公式", level=2)
        rows = []
        for item in formulas:
            if not isinstance(item, dict):
                fail("each formula must be an object")
            rows.append([require_text(item, "name", "formula"), require_text(item, "formula", "formula")])
        add_table(doc, ["指标", "公式/口径"], rows, [2600, 7235])
    add_heading(doc, "限制与免责声明", level=2)
    for item in data.get("limitations", []):
        add_bullet(doc, item)
    add_bullet(doc, "本报告用于研究立项前快速排雷，不构成证券投资建议、估值结论或买卖依据。")
    end_text = f"END｜严格框架结论：{conclusion}"
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER; p.paragraph_format.space_before = Pt(14)
    set_run_font(p.add_run(end_text), size=12, bold=True, color=RED if fatal_ids else GREEN)

    output.parent.mkdir(parents=True, exist_ok=True)
    doc.core_properties.title = f"{meta['company_name']}致命风险排雷报告"
    doc.core_properties.subject = "V3.0 精简版开题前快速过滤"
    doc.core_properties.author = meta["executor"]
    doc.save(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="UTF-8 report JSON")
    parser.add_argument("--output", required=True, type=Path, help="output DOCX")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    with args.input.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    derived = validate(data)
    if args.validate_only:
        print(json.dumps({k: v for k, v in derived.items() if k not in {"meta", "by_id"}}, ensure_ascii=False, indent=2))
        return
    build(data, derived, args.output)
    print(f"Created {args.output}")


if __name__ == "__main__":
    main()
