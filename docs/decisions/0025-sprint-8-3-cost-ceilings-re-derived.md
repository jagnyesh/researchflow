---
sprint: 8.3
date: 2026-05-14
status: shipped
supersedes: []
superseded_by: null
related: []
---

# Sprint 8.3 — Cost-per-request ceilings re-derived against measured baselines; Sprint 8 series closes

Sprint 8.3 closes 2026-05-14 with corrected ceilings shipped. Scope-split per pre-committed grilling (D1=A): Sprint 8.3 is ceiling re-derivation only; the broader "structural redesign question" is decoupled into a separate sprint if and when the corrected ceilings show a genuine gap.

### Empirical inputs (2026-05-14, post-Sprint-8.4 aggregator)

Re-aggregated against trustworthy numbers, with manual trace-tree walks verifying aggregator output within ±0.01%:

| Portal | Median | n | Cache hit rate | Aggregator-vs-manual delta |
|---|---:|---:|---:|---:|
| Formal | $0.007754 | 30/30 threads | 94.88% | 0.01% |
| Exploratory | $0.003540 | 30/30 root traces | **0.0000%** | 0.000% |

### Derived ceilings (formula: `measured_median × 1.3`, per D2=A)

| Portal | Sprint 8.1 ceiling (projection × 1.3) | Sprint 8.3 ceiling (median × 1.3) | Direction |
|---|---:|---:|:---:|
| Formal | $0.0039 | **$0.010080** | +158% — old ceiling was projection-aspirational, new ceiling is measurement-grounded |
| Exploratory | $0.00091 | **$0.004602** | +406% — same shift |

### THREE framing notes (mandatory per pre-committed grilling)

**(1) Semantic shift, NOT goalpost-moving.** Sprint 8.1's ceilings were `projection × 1.3` — a tolerance band around an aspirational cost target ("we projected $0.003/request post-optimization; allow 30% tolerance"). Sprint 8.3's ceilings are `measured_median × 1.3` — a tolerance band around the current operating point ("we measure $0.007754/request at steady state; alarm at 30% above that"). The math is identical. **The meaning shifts from "cost target with tolerance" to "regression alarm against current baseline."** This is honest framing: the Sprint 8 series projections were structurally falsified by Sprint 8.2 Task 3 (3× call-count overestimate + 9× per-call cost underestimate). Setting the ceiling at measured-median × 1.3 calibrates the gate to catch regressions, not to enforce the projection that didn't match reality. Future readers who notice the ~2.5× upward ceiling shift should land on this framing first, not "they moved the goalposts."

**(2) Bursty-traffic calibration.** The medians come from `scripts/drive_qa_traffic.py` which fires 30 requests in 6-7 minutes — entirely within Anthropic's 5-min cache TTL. Steady-state caching applies to runs 2-30 (with run 1 paying cache_create). Sparse real-world traffic (gaps > 5 min between requests) would shift the median toward the worst-case cache_create cost. **The Sprint 8.3 ceilings are calibrated for bursty patterns; sparse-traffic measurement is a known gap.** Filed as Sprint 8.5 candidate (#TBD) in BACKLOG.md so the open question stays visible. Until that fires, the dashboard's gate-status reflects bursty-pattern truth; in sparse real-world traffic the median can plausibly drift into the new ceiling without indicating a code regression.

**(3) Exploratory cache_hit_rate is 0.0000%, which is a real finding.** Formal portal post-Sprint-8.2 fires cache at 94.88% (Sonnet + Haiku both cleared their thresholds). Exploratory portal QueryInterpreter shows zero cache hits on 30 root traces. This is the SAME structural class of below-threshold issue Sprint 8.2 fixed for the formal portal's `_REQUIREMENTS_SYSTEM_PROMPT` and `_MEDICAL_CONCEPTS_SYSTEM_PROMPT`. **The corrected exploratory baseline of $0.003540 is therefore the pre-caching baseline.** If QueryInterpreter were to clear Anthropic's caching threshold (likely requires bulking the system prompt past 1024 tokens for Sonnet fallback or 4096 for Haiku primary, plus the langchain content-block-array form from PR #45), the exploratory median would drop further and the $0.004602 ceiling would become trivially generous. Filed as Sprint 8.6 candidate in BACKLOG.md. This finding is OUT OF SCOPE for Sprint 8.3 (which is ceiling derivation only per D1=A) but the ceiling derivation is honest about the assumption it bakes in.

### What shipped

- `app/services/cost_telemetry_service.py:82-110` — `FORMAL_BAND_CEILING_USD` and `EXPLORATORY_BAND_CEILING_USD` updated with multi-line provenance comments explaining the semantic shift, traffic-pattern assumption, and exploratory caching finding.
- All 16 existing `test_cost_telemetry_service.py` tests pass against the new ceilings (the tests assert against the constants by name, not by value, so changing the numbers doesn't break them).

### Gate verification (informational — ships against new ceilings)

| Portal | Median | New ceiling | Gate |
|---|---:|---:|:---:|
| Formal | $0.007754 | $0.010080 | 🟢 GREEN |
| Exploratory | $0.003540 | $0.004602 | 🟢 GREEN |

**Both portals now GREEN against the corrected ceilings.** This is the predictable consequence of calibrating the ceiling to the current operating point — the gate's job becomes regression-alarm, not target-pursuit. The structural redesign question (does ResearchFlow's current model strategy clear a defensible ceiling?) collapses to "yes, against a measurement-grounded ceiling." If the user wants a TIGHTER ceiling (e.g., "we won't accept current cost as the floor — get it under $0.005/request"), that's the structural redesign sprint, not Sprint 8.3.

### Sprint 8 series closes

| Sprint | Verdict | Outcome |
|---|---|---|
| 8 (original, 2025) | SHIPPED — implementation projected 73% reduction | Reality: projection falsified by Sprint 8.2 |
| 8.1 (verification, 2026-05-12) | CLOSED RED | Correct at $0.009026 (cache_hit=0% protected baseline from aggregator bug) |
| 8.2 (cache-hit investigation, 2026-05-14) | CLOSED — three failure modes diagnosed | Cache_control wire fix shipped; manual baseline $0.007754 established |
| 8.4 (aggregator audit, 2026-05-14) | SHIPPED | `cache_read` double-charge fixed; aggregator now matches manual ±0.01% |
| 8.3 (this sprint, 2026-05-14) | SHIPPED | Ceilings re-derived against measured medians; both portals GREEN at new ceilings |

The arc: ship → measure → falsify projection → diagnose three concurrent failure modes → fix transmission bug → fix aggregator bug → re-derive ceilings against trustworthy data. Took 5 sprints. The structural lesson — "for fixes whose correctness depends on third-party library behavior, the test must assert the third-party API contract" — was named in Sprint 8.2 and applied recursively in Sprint 8.4. Sprint 8.3 closes by codifying the corrected ceilings in code with provenance preserved in this ADR.

### Sprint 8.3 closes

Issues closed by this PR's merge:
- `#47` Sprint 8.3 — Cost-per-request ceilings re-derived against measured baselines

Filed by this PR:
- Sprint 8.5 candidate — sparse-traffic median measurement (calibrate against gaps > 5 min between requests; verify Sprint 8.3 ceilings still defensible OR re-derive for sparse case)
- Sprint 8.6 candidate — exploratory portal caching (QueryInterpreter shows cache_hit=0%; same class as Sprint 8.2's formal-prompt issue)
