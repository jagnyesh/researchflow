---
sprint: 8.4
date: 2026-05-14
status: shipped
supersedes: []
superseded_by: null
related:
  - 0022-sprint-8-2-close-corrected-baseline.md
---

# Sprint 8.4 — Aggregator over-count root cause: `_run_cost_usd` double-charges `cache_read` tokens

### Setup

Sprint 8.2's close (2026-05-14) surfaced that `CostTelemetryService.get_formal_portal_cost_p50` reported $0.022865 against a manual per-thread sum of $0.007754 — a 2.95× inflation factor — and filed Sprint 8.4 as BLOCKING for any further ceiling-re-derivation work. The Sprint 8.2 CLOSE ADR hypothesized parent-trace `usage_metadata` was being double-counted alongside LLM-child counts via tag inheritance. **That hypothesis was wrong.**

### Diagnostic-first methodology (Sprint 8.2 structural lesson applied)

Sprint 8.4 Task 1 was static-analysis-confidence. The Sprint 8.2 close ADR's structural lesson — "for fixes whose correctness depends on third-party library behavior, the test must assert the third-party API contract" — applied. Task 1 pulled one real production trace (`trace_id=62ef0f8c-8920-42a7-bd34-e77edaf65d11` from 2026-05-14 19:56) via the langsmith SDK and walked its tree before writing any fix.

The wire-level pull contradicted the static-analysis hypothesis. The full corrected diagnostic (with trace tree dump + pricing math) is on issue [#46](https://github.com/jagnyesh/researchflow/issues/46#issuecomment-4454629786). Summary:

**(1) Parent+child double-counting did NOT happen.** The 6 `execute_task` `@traceable` chain spans carry `portal:formal` but have `metadata.thread_id == None`. `_extract_thread_id()` returns None and `_summarize_threaded` filters them out (the `if thread_id is not None:` check). Only the 2 LLM leaves per thread get bucketed. The aggregator was summing exactly the same runs the manual walk used.

**(2) The real bug: LangSmith's `Run.input_tokens` already INCLUDES `cache_read_input_tokens`.** Empirical verification on the trace: every LLM leaf satisfied `total_tokens == input_tokens + output_tokens` (cache_read is INSIDE input_tokens, not added on top). But `_run_cost_usd` charged `input_tokens * prices["input"] + cache_read * prices["cache_read"]` — double-billing the cache_read portion at both rates.

**(3) The bug fires only when `cache_read > 0`.** Sprint 8.1's 2026-05-12 traffic had `cache_hit_rate = 0.0%` everywhere; with `cache_read = 0`, the buggy formula reduces to the correct formula (the second term is zero). **Sprint 8.1's $0.009026 baseline is therefore CORRECT, not inflated.** The Sprint 8.2 CLOSE ADR's claim that "Sprint 8.1's baseline came from the same aggregator and is therefore likely also inflated" is **wrong** — corrected here.

### Fixes shipped

**(1) `_run_cost_usd` subtracts `cache_read` from `input_tokens` before pricing.** New helper `_get_non_cached_input_tokens(run) = max(0, input_tokens - cache_read)` consolidates the subtraction in one place.

**(2) `cache_hit_rate` calculation corrected via the same helper.** `_summarize_threaded` and `_summarize_per_root` previously summed raw `input_tokens` as "non_cached" — same underlying mistake. Post-fix the dashboard reports cache_hit_rate = 0.9488 on Sprint 8.2's 30-thread sample (was 0.4869 pre-fix, under-reporting by ~2×).

**(3) Wire-level fixture test.** `TestCostTelemetryService.test_cache_read_not_double_charged_against_wire_shape` uses the exact numbers from the real production trace (Sonnet `input=3362, cr=3087`; Haiku `input=5927, cr=5850`) and asserts the corrected cost. Verified to FAIL on the pre-fix formula ($0.022074) and PASS on the corrected formula ($0.006963). Future maintainers cannot revert the fix without breaking this test.

**(4) Schema contract test.** `test_langsmith_schema_contract_input_includes_cache_read` asserts `total_tokens == input_tokens + output_tokens` for the same fixture. Documents the LangSmith accounting assumption (`input_tokens` includes `cache_read`); if LangSmith ever changes accounting, the test breaks and forces revisiting `_run_cost_usd`.

**(5) `_get_input_tokens` docstring rewrite.** Previously said "Non-cached input tokens. Anthropic returns cache_read separately." That was true for Anthropic's API but wrong for LangSmith's storage. Corrected.

### Pre-committed gate (empirically verified)

| Gate | Target | Measured | Delta | Status |
|---|---:|---:|---:|:---:|
| Sprint 8.2 30-thread re-aggregate | $0.007754 | $0.007754 | 0.01% | ✅ |
| Sprint 8.1 2026-05-12 re-aggregate | $0.009026 | $0.008997 | 0.32% | ✅ |

Both within the pre-committed ±1% tolerance. The Sprint 8.1 cross-check empirically confirms the "bug only fires with caching" claim — cache_hit_rate on Sprint 8.1 traffic measured 0.0000, so the median was unaffected.

### Dashboard banner

`app/web_ui/admin_dashboard.py:show_cost_telemetry` now renders an `st.info` banner above the Sprint 8.1 verification panels: "Numbers corrected 2026-05-14 (Sprint 8.4) — pre-fix display inflated ~3× by `cache_read` double-charge bug. Sprint 8.1's $0.009026 baseline was unaffected." Future-me opening the dashboard six months from now sees the discontinuity context without digging through git history.

### Discipline notes

**(a) Diagnostic-first scoping paid for itself again.** Static analysis predicted parent+child double-count via tag inheritance. Wire-level pull (~10 min effort) revealed the real cause was a single-leaf cache_read double-charge. Without the wire-level step, Sprint 8.4 would have shipped a fix that didn't change aggregator output — or worse, attempted a `run_type == "llm"` filter that broke the existing thread-id-bucketing logic. Cost: 10 minutes. Value: avoiding a wrong-fix-shipped sprint.

**(b) Append-only revision pattern continued.** Sprint 8.2 CLOSE ADR's "Sprint 8.1 baseline suspect" claim is wrong. Per the append-only DECISIONS.md discipline (preserved from D1 of the Sprint 8.4 grill), this ADR appends the correction rather than editing the prior entry in place. Future readers see the original wrong claim AND the correction — that's how audit trails stay honest.

**(c) Empirical gates were two-part by design.** Verifying only the "fix output matches manual" leg would have left "Sprint 8.1 baseline correctness" as an inferred claim. The Sprint 8.1 cross-check turned it into measured evidence. Both gates were pre-committed before code work; both fired at sprint close. The pattern works because the prediction ("cache_hit=0% protected Sprint 8.1") was risky — falsifiable by the second gate's result.

### Sprint 8.4 closes

Issues closed by this PR's merge:
- `#46` Sprint 8.4 — Cost telemetry aggregator audit complete; fix shipped + empirically verified

### Sprint 8.3 unblocked

With the aggregator corrected, Sprint 8.3 (#47) can now re-derive the cost-per-request ceiling against measured per-call costs. The structural redesign question can be evaluated against trustworthy numbers. **Updated Sprint 8.3 framing:** the corrected Sprint 8.2 baseline of $0.007754 against the (still-valid) Sprint 8.1 baseline of $0.009026 means Sprint 8.2 delivered a real 14.1% reduction. Whether that clears a defensible ceiling for the formal portal — and what the right ceiling actually is — is Sprint 8.3's call to make against post-fix data.
