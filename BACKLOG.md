# Backlog

Forward plan only. Active work lives in `CONTEXT.md`. History lives in `DECISIONS.md`.

## Phase 2 — Clinical Intelligence & Optimization (in progress)

- [x] Sprint 6.1 — Security Baseline (COMPLETE 2026-05-07, ready for PR)
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

## Sprint 6.1 follow-ons (defer until production usage informs priority)

- [ ] **Phase 2.2.1** — `idempotency_key` column on `AuditLog` for exactly-once semantics; current Phase 2.2 accepts dupes (acceptable per design — auditors care about presence). Ship if/when query-time dedup proves operationally annoying.
- [ ] **Phase 2.3.1** — Discriminated unions for `Dict[str, Any]` fields in request schemas (`structured_requirements`, `requested_changes`, `modifications`, `search_params`, `view_definition`). Phase 2.3 wraps these in `BoundedDict` for size guards; explicit shape work requires per-dict investigation (2-3 weeks per dict). Defer until Sprint 11+ when domain stability allows.
- [ ] **Phase 3b.1** — Researcher-PII encryption (`*.researcher_email`, `User.email`, `User.full_name`, `User.department`). Phase 3b ships ePHI-only encryption (HIPAA §164.312 floor); PII encryption is a defense-in-depth follow-on. Blocked by `User.email`'s unique-index login lookup — needs deterministic encryption or a separate hashed-email index column. Defer until Sprint 11 (multi-tenant architecture) when the index strategy gets revisited anyway.

## Out-of-band tooling debt (this reorg's own follow-on)

- [ ] **Phase 2 of doc reorg**: hooks (PreToolUse/PostToolUse/SessionStart) wired into `.claude/settings.json` — alongside Sprint 6.1 Phase 2.2
- [ ] **Phase 3 of doc reorg**: distill `docs/SQL_ON_FHIR_V2.md`, `docs/MATERIALIZED_VIEWS_ARCHITECTURE.md`, etc. into `.claude/skills/{fhir-query,hipaa-review,agent-design,sprint-workflow}/SKILL.md` — post Sprint 6.1
- [ ] **Phase 4 of doc reorg**: subagents + plugin manifest — deferred until second contributor or clear pain
- [x] LangSmith API key rotation — DONE 2026-05-10. Final state: PAT `lsv2_pt_fe4404cd…` in `.env` (works for both `/runs/batch` write and `/sessions` read). Old keys (`lsv2_pt_34040ddb…`, `lsv2_pt_1df0c329…`, `lsv2_sk_2581c7ca…`) still need manual revocation in LangSmith UI. `~/.zshrc:259-265` forwards from `.env` (single source of truth).
- [ ] **MCP LangSmith server picks up stale key at Claude Code launch.** `.mcp.json` substitutes `${LANGSMITH_API_KEY}` at MCP server spawn time, so rotating the key in `.env` mid-session leaves the MCP server holding the old key until Claude Code is fully restarted. Mild ergonomic issue — affects `mcp__langsmith__*` tools only, not app tracing. Document the gotcha or wire MCP startup to read from `.env` directly.
- [ ] Write `LANGSMITH_KEY_ROTATION_GUIDE.md` (referenced from BACKLOG but doesn't exist) — capture today's rotation flow as a runbook (3 keys generated before finding one with right scopes; LangSmith UI permission selectors are unobvious).
- [ ] **Audit drain noisy on idle queue** (`app/security/audit_drain.py:107`) — `redis.blmove(...)` blocks longer than the socket read timeout, so empty-queue idle states crash with `TimeoutError` and exponentially back off. Non-fatal, but spammy in stderr. Fix: pass `block_timeout` < socket read timeout, or switch to non-blocking poll with short sleep.
- [ ] **`ENCRYPTION_KEY_PRIMARY` startup gate doesn't cover streamlit/scripts** (memory note flagged this earlier). Phase 3b lifespan-only assertion lets streamlit submit a form, get all the way to encrypted INSERT, and then KeyError at SQLAlchemy. Fix: duplicate the assertion in each streamlit's startup, or move the gate to a module-import-time check shared by all entry points.
- [ ] **Makefile `run` target hardcodes bare `uvicorn`** — relies on PATH activation; broke today when terminal didn't have `.venv` activated even after `source .venv/bin/activate && make run` (suspected pyenv shim). Change to `./.venv/bin/uvicorn` or add `which uvicorn` debug output.

## Sprint 6.2 observability follow-ons (from 2026-05-10 E2E session)

- [ ] **`@traceable` coverage gap on extraction/qa/delivery agents.** Phase 1 of this work added decorators to `phenotype_agent.execute_task`, `feasibility_service.execute_feasibility_check`, `hybrid_runner.execute_count`, `materialized_view_runner.execute_count`. The agent fan-out for extraction/qa/delivery still doesn't appear in LangSmith traces — when those nodes execute, they do real work but show as 5-7ms no-op spans. Add `@traceable` to `extraction_agent.execute_task`, `qa_agent.execute_task`, `delivery_agent.execute_task` to close the visibility gap.
- [ ] **`AUTO_APPROVE_FOR_DEV` flag** — `langgraph_workflow.py` now skips `interrupt_after` and short-circuits the 4 `_route_after_*_review` functions to the approved path when `AUTO_APPROVE_FOR_DEV=true`. HARD-FAIL guarded against `ENVIRONMENT=production`. Useful for E2E tracing runs. Document in `docs/HIPAA_POSTURE.md` as an explicit dev-only carve-out so external reviewers don't get spooked.
- [ ] **`ApprovalBridge` unknown approval_type "qa"** — log line: `[ApprovalBridge] Unknown approval_type: qa. Valid types: ['requirements', 'phenotype_sql', 'extraction', 'delivery', 'preview_qa', 'scope_change']`. The `qa_review` node tries to create an approval with type "qa" but the bridge enum has no match. Either add "qa" to the enum or rename the call site to `qa_review`. One-line code bug surfaced during AUTO_APPROVE end-to-end run.
- [ ] **Phenotype agent generates SQL missing demographic predicates.** Today's input: "all diagnoses of male patients above the age of 18 who have diabetes." Structured criteria correctly extracted `Age > 18`, `Gender: Male`, `Diagnosis: diabetes`. But generated SQL only has the diagnosis filter — no `WHERE p.gender = 'male'`, no age comparison. Same SQL shape on 3 separate test inputs (`hypertension`, `diabetes`, etc.). Real correctness regression in phenotype_agent's SQL generation, separate from the runner question. File a dedicated issue.
- [ ] **HAPI Postgres + HAPI FHIR containers don't auto-restart.** Both containers from `config/docker-compose.yml` died sometime today (last seen 21h-up at session start). No `restart: unless-stopped` policy in compose? Add restart policy to compose, document recovery in README under Quick Start.
