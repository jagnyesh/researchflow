<!--
Evidence-first PR template (docs/DAILY_DEV_WORKFLOW.md §5.4).
At throughput, reviewers read EVIDENCE, not diffs. Fill every section from
actual command output — green unit tests alone don't clear the bar.
-->

## What & why
<!-- One or two lines: what this changes and the outcome it buys. -->

Closes #<issue>

## Testing evidence
- **Commands run:** `pytest tests/... -x` → <N passed, M failed>
- **E2E exercised:** <what was driven end-to-end; expected vs. observed>
- **Artifacts:** <output paste / screenshot / LangSmith trace link>
- **Not covered:** <gaps and why they're acceptable>

## Review discipline (§5.2)
- [ ] Reviewed in a **fresh context**, not the authoring session
- [ ] Behavior-changing findings escalated to the author; mechanical fixes applied in-lane
- [ ] Wire-level confirmation where the change crosses an interface boundary (wrapper / third-party API / async / cache), if applicable

## Security (only if touched)
- [ ] No hardcoded secrets or keys
- [ ] User input stays parameterized — no f-string / `.format()` SQL
- [ ] PHI/PII handling unchanged, or the change is explicitly justified here
