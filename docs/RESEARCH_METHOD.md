# Financial Report Screening and Analysis System · v8.1

**财报筛选与分析系统**

A bilingual research workbench for Mainland China A-share and Hong Kong listed companies. It connects official filing discovery, concise operating summaries, evidence-based research briefs and structured risk review in one workflow.

The interface preserves the existing visual style. Company cards remain on the left while reports and generation progress appear on the right. The cover uses a compressed local image; the cards' original business-substance writing style is retained and DuPont metrics have been removed from the cards.

## Research method

1. **Find and verify the filing.** Retrieve formal periodic reports from CNINFO or HKEX, distinguish full reports from summaries/results announcements, and check issuer and report type before generating the brief.
2. **Retrieve evidence across the document.** Normalize PDF text, locate the statements, business segments and important notes, and retain physical PDF page numbers. Preserve complete primary-statement pages and continuations before allocating the remaining text budget. Topic coverage is a retrieval diagnostic, not proof of a financial fact.
3. **Explain the economically important changes.** The versioned application skill in [analyzer/SKILL.md](../analyzer/SKILL.md) produces a seven-section Markdown memo: research conclusions; operating drivers and earnings quality; assets, cash and debt; risks and counterevidence; scenarios and follow-up; key figures and accounting checks; evidence and limitations. The target is a concise memo rather than a line-by-line transcription.
4. **Keep accounting boundaries explicit.** Preserve reporting currency, units, period, consolidation scope and reported/constant-currency/adjusted bases. Hong Kong non-GAAP profit is distinct from the Mainland disclosure of net profit excluding non-recurring items. Banks and insurers use sector-specific evidence rather than industrial-company cash-cycle rules.
5. **Review risks without treating missing evidence as clearance.** Each independent risk check distinguishes verified/not triggered, verified/triggered, insufficient evidence and not applicable. The research brief describes observed risk facts and future risks requiring validation; these are distinct from the nineteen hard-rule trigger results. A disclosed impairment charge does not automatically trigger a hard-risk rule.

## Reliability and English

Missing or interrupted sections receive bounded, targeted repair. References are checked against pages actually supplied to the model. A supplied cash-flow bridge cannot be described as missing without triggering a targeted correction or an explicit retryable result. Incomplete generation, test mode, absent credentials and failed language checks are not completed research.

English is produced from the source-language analysis with checks on numerical literals, protected references, accounting terminology and conclusion strength. Original and English artifacts are stored separately. Translated excerpts are labeled as translations, not verbatim English source quotations. In the English company table, Chinese issuer names appear beside their English names to help identify the correct security.

**These checks do not establish an audited accuracy rate.** Page existence does not prove that a page supports the inference; a complete report does not prove that every figure or conclusion is correct. Extraction can miss layouts or notes, and a model can misread a fact, a comparison basis or a causal relationship. Important figures, ratios, citations and conclusions require review against the original filing. The system does not claim manual review unless it actually occurred.

Cash-bridge formulas remain model calculations requiring analyst review. v8.1 now independently checks explicit displayed addition/subtraction equations using Decimal; it does not validate undisplayed calculations, source semantics, cash-flow classification or currency/unit conversions. A failed equation or detected parent-only profit presented as consolidated results makes the report retryable for review. Sections, table completeness and reference-page availability are checked separately. A source-table rounding discrepancy must be disclosed without changing the original amounts.

The report states its period, analysis date and evidence limits. Historical filings are not current investment views. Missing consensus, prices or forecasts must not be replaced by invented expectations, targets or valuation inputs.

## Saved work and examples

Report generation runs in a background process with saved progress and per-company checkpoints. Users can return through Research History; a failed stage can resume without repeating completed stages. Chinese and English research artifacts remain separate.

[samples/manifest.json](../samples/manifest.json) indexes read-only, pre-generated examples. Each available sample records the issuer, period, language, generation time and the scope of the actual validation. Samples are historical outputs, not live calculations. Only validated final QA artifacts are added; an empty or pending manifest does not represent completed examples.

## Run locally

Create a compatible Python environment and install the pinned dependencies:

~~~powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py --server.port 8581
~~~

Open `http://127.0.0.1:8581/`; `?lang=en` selects English and `?lang=zh` selects Chinese. Configure the model endpoint and key through Settings or a private `.env` based on `.env.example`. Keep keys outside source control. A working model connection is required for newly generated analysis and dynamic English translation. Explicit test/demo outputs do not provide research conclusions or risk clearance.

## Validation

Run deterministic regression tests from the project directory:

~~~powershell
.\.venv\Scripts\python.exe -m pip install pytest
.\.venv\Scripts\python.exe -m pytest tests -q
~~~

The suite covers extraction safeguards, report repair, source references, risk evidence states, English validation, background-job recovery and the bilingual workspace. Real model/API tests and browser checks are separate from deterministic tests. A regression pass alone does not establish financial accuracy or general performance.

Release-specific real-run evidence is recorded with the final QA artifacts and example manifest. Timing depends on filing download/cache state, model latency, repairs and translation; saved examples should not be presented as fresh-generation timing.

## 中文说明

系统用于研究辅助：先取得正式财报，再围绕关键经营变化、盈利兑现、现金与资金约束形成可追溯简报，并独立进行风险核验。缺证据会明确标注，不能把“没有查到”写成“核验通过”。

v8.1 保留原有界面风格及业务实质卡片写法，采用左侧卡片、右侧报告工作区，改用七章 Markdown 深度简报，并加强港股原币、利润归属、现金桥和行业口径处理。英文检查包含数字及表达强度，但不能替代原文财务核验。模型输出、程序校核、真实人工审阅三者分别说明。

本项目不构成投资建议，也不替代专业研究者对原版财报的复核。
