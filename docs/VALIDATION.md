# Validation of the public snapshot

[简体中文](VALIDATION.zh-CN.md) · [Project home](../README.md)

The public-source preparation was checked on 25 October 2026 (Asia/Shanghai), using Python 3.12.2 and the dependency environment matching the pinned Streamlit and OpenAI client versions.

## Regression result

**296 tests passed, plus 8 unittest subtests, in 35.91 seconds.**

The completed run used:

```text
python -m pytest tests -q
```

The test workspace and JUnit report were directed to a temporary folder outside the publishable project. Streamlit AppTest required execution outside the restricted sandbox because its asyncio socketpair could not initialize inside that sandbox. The completed run included the UI workflow tests rather than skipping them.

Coverage includes:

- PDF/evidence selection and financial-statement continuity.
- Accounting scope and restricted-cash evidence regressions.
- Report structure, malformed responses, citation-page checks and retry states.
- Risk findings that remain separate from insufficient evidence.
- Protected figures/references, English exports and unchanged source artifacts.
- Background-job deduplication, credential-free saved requests and failed-stage recovery.
- Bilingual Streamlit login, input, company cards and saved-report workflows.
- Public-release authentication with environment-configured accounts, invalid-configuration rejection and no enabled account when configuration is absent.

## Boundaries

This run did not call a paid model provider, re-download the official filings, independently verify all financial claims in the saved examples, or benchmark end-to-end generation latency. The model-facing regression cases use controlled responses. Test success is evidence of those specified behaviors, not of audited financial accuracy or production deployment readiness.

The interface images in the README are historical QA captures included with the source materials. They were visually inspected for personal names and visible credentials; they are not presented as screenshots from this regression run. The public account configuration differs from the original deployment.
