# Backlog

Forward plan only. Active work lives in `CONTEXT.md`. History lives in `DECISIONS.md`.

## Phase 2 — Clinical Intelligence & Optimization (in progress)

- [x] Sprint 6.1 — Security Baseline (~40% complete, see CONTEXT.md)
- [ ] Sprint 8 — Prompt Optimization (analysis done; 73% projected cost reduction)
  - Implement prompt cache for stable agent system prompts
  - Token-budget tracking per agent
  - A/B test against baseline before rollout
- [ ] Sprint 9 — Temporal Reasoning Engine (3 weeks)
  - Express clinical time windows ("HbA1c >7 within 6mo before diabetes dx")
  - Lookback/lookahead operators in phenotype query language
- [ ] Sprint 10 — Complex Cohort Logic (2 weeks)
  - Nested AND/OR/NOT criteria, cohort intersections, exclusion subqueries
  - Phenotype-as-code (versioned cohort definitions in repo)

**Decision Gate 3 — after Sprint 10:** Clinical validation complete? Are cohorts correct against gold-standard chart review? If no, pause Phase 3 and iterate Sprints 9-10.

## Phase 3 — Production Readiness

- [ ] Sprint 11 — Multi-Tenant Architecture (3 weeks)
  - Institution-scoped data, per-tenant audit logs, isolation testing
- [ ] Sprint 12 — Performance Optimization (3 weeks)
  - Query plan profiling, materialized view refresh tuning, agent parallelization

**Decision Gate 4 — after Sprint 12:** Production-ready for first paying institution? Latency, concurrency, audit completeness, security pen-test all passing.

## Phase 4 — Differentiation

- [ ] Sprint 13 — Conversational Memory (2 weeks) — researcher dialogue history influences subsequent agent runs
- [ ] Sprint 14 — Real-Time Cohort Discovery (3 weeks) — FHIR Subscription listener wired to speed layer
- [ ] Sprint 15 — Federated Query Engine (3 weeks) — cross-institution queries without raw data exchange

## Sprint 6.1 follow-ons (defer until pilot user feedback)

- [ ] **Phase 2.2.1** — `idempotency_key` column on `AuditLog` for exactly-once semantics; current Phase 2.2 accepts dupes (acceptable per design — auditors care about presence). Ship if/when query-time dedup proves operationally annoying.
- [ ] **Phase 2.3.1** — Discriminated unions for `Dict[str, Any]` fields in request schemas (`structured_requirements`, `requested_changes`, `modifications`, `search_params`, `view_definition`). Phase 2.3 wraps these in `BoundedDict` for size guards; explicit shape work requires per-dict investigation (2-3 weeks per dict). Defer until Sprint 11+ when domain stability allows.

## Out-of-band tooling debt (this reorg's own follow-on)

- [ ] **Phase 2 of doc reorg**: hooks (PreToolUse/PostToolUse/SessionStart) wired into `.claude/settings.json` — alongside Sprint 6.1 Phase 2.2
- [ ] **Phase 3 of doc reorg**: distill `docs/SQL_ON_FHIR_V2.md`, `docs/MATERIALIZED_VIEWS_ARCHITECTURE.md`, etc. into `.claude/skills/{fhir-query,hipaa-review,agent-design,sprint-workflow}/SKILL.md` — post Sprint 6.1
- [ ] **Phase 4 of doc reorg**: subagents + plugin manifest — deferred until second contributor or clear pain
- [ ] LangSmith API key rotation per `LANGSMITH_KEY_ROTATION_GUIDE.md` (was exposed in `.claude/settings.local.json`)

## Persistent open question

No external pilot user. Sprint 6.1 ships sales-grade HIPAA posture as the asset for institutional outreach, but outreach itself is unscheduled. **Treat any sprint that defers this question without addressing it as suspect.**
