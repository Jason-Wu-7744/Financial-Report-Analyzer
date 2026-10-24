# Project motivation and development

## Motivation

The project grew from exposure to investment research and the repetitive work of reviewing company financial reports. Its goal is to help a researcher find official filings, compare operating changes and produce an initial evidence-linked brief while keeping uncertainty visible.

## Development approach

This is a personal project developed with AI-assisted coding tools, including Codex and Cursor. The project owner's work includes framing the financial-research workflow, defining the desired summaries and review rules, and iterating on the tool through trial use and feedback. AI-assisted code generation and subsequent revisions are part of the development process; this repository does not imply that every line was written without assistance.

For technical evaluation, the most useful evidence is the implementation and its regression cases: evidence selection, reported-versus-adjusted profit distinctions, missing-evidence states, bounded repair, resumable background work and bilingual export checks. Readers can inspect the source and rerun the tests rather than rely on a broad claim of programming proficiency.

## Public release scope

This release is prepared from the v8.1 source snapshot. It contains source code, application instructions, selected deterministic fixtures and four pre-generated examples. It excludes historical deployment accounts, personal thesis documents, server administration scripts, caches, run logs, downloaded full-text filing corpora and broker-report PDFs.

The public account configuration is different from the original hosted snapshot: accounts are supplied through `RESEARCH_ACCOUNTS_JSON`, with no active password bundled in the source. Existing application behavior is covered by the retained regression suite plus account-configuration tests.

## What is not claimed

- Test passes are not an audited financial-accuracy rate.
- Historical samples are not fresh model runs or evidence of current investment merit.
- The repository does not claim a uniform generation time or a measured time-saving result.
- Automated source checks are distinct from human financial review.

## Next engineering improvements

- Split orchestration and provider integration into smaller modules.
- Expand provider contract tests and sector-specific extraction coverage.
- Improve job isolation and deployment authentication before any multi-user service.
- Add repeatable benchmarks with explicit filing, cache, model and translation conditions.
