# Word 报告数据合同

将研究结果保存为 UTF-8 JSON，再交给 `scripts/build_report.py`。金额统一在文本中标明单位，避免脚本猜测。

## 必填结构

```json
{
  "meta": {
    "company_name": "万华化学",
    "full_name": "万华化学集团股份有限公司",
    "ticker": "600309.SH",
    "industry": "基础化工",
    "screening_date": "2026-07-26",
    "data_cutoff": "2026-07-26（行情取前一交易日收盘）",
    "executor": "AI投研助理",
    "reviewer": "待复核"
  },
  "one_line_conclusion": "一句话说明最终结论及决定性依据。",
  "scope": "财务、经营、行情和事件的覆盖范围。",
  "snapshot": [
    {"label": "2025营收", "value": "...亿元", "note": "同比..."}
  ],
  "checks": [
    {
      "id": "H1",
      "name": "行业需求不可逆萎缩",
      "outcome": "通过",
      "evidence_state": "已核验未触发",
      "evidence_quote": "从已取得原文逐字引用的8-60字片段",
      "threshold": "行业整体需求连续下滑...",
      "finding": "实测事实或数值",
      "basis": "为何满足或不满足阈值 [S1]",
      "source_ids": ["S1"]
    }
  ],
  "financial_tables": [
    {
      "title": "近三年核心财务",
      "columns": ["指标（亿元）", "2023", "2024", "2025", "趋势"],
      "rows": [["营业收入", "...", "...", "...", "..."]]
    }
  ],
  "observations": [
    {"title": "补充黄灯标题", "detail": "未触发硬线但需深研的事实", "monitor": "后续验证或升级条件"}
  ],
  "recommendations": ["通过后深度研究问题，或淘汰后的低成本跟踪项"],
  "formulas": [{"name": "自由现金流", "formula": "FCF = OCF - Capex"}],
  "sources": [
    {"id": "S1", "title": "来源标题", "url": "https://...", "published_at": "2026-04-01", "used_for": "年报与审计数据"}
  ],
  "limitations": ["未经审计数据、数据库时点或未披露项目的限制"]
}
```

## 校验规则

- `checks` 必须恰含 H1-H2、C1-C11、Q1-Q6，共19项，无重复。
- `outcome` 只能是 `通过`、`高风险`、`证据不足`、`通过（不适用）`；`evidence_state` 分别为 `已核验未触发`、`已核验触发`、`证据不足`、`不适用`。
- 已核验项必须给出可定位的 `evidence_quote`，不得伪造引文。行业/数学不适用须说明具体原因，不能用缺数据解释不适用。
- 脚本推导最终结论：有高风险则淘汰；无高风险但有证据不足则待补证；全部完成适用性与阈值核验才通过。缺项默认证据不足。
- 每项 `threshold`、`finding`、`basis` 和 `source_ids` 必填；每个来源编号必须存在于 `sources`。
- 关键事实的 `basis` 应带 `[Sx]`，且与 `source_ids` 一致。
- `snapshot` 建议4项；`financial_tables` 可包含3-5年财务、资产负债、资本开支或应收账龄，表格列数不得超过6。
- `observations` 是黄灯，不得出现“高风险/淘汰”式结论；硬性命中必须回到对应检查项。
- `recommendations`：通过时列3-5个深度研究问题；淘汰时列冻结期内低成本跟踪与复核条件。
