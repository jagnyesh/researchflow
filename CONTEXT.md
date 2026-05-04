# ResearchFlow — Current State

**Sprint:** 6.1 (Security Baseline)
**Phase:** 2.2 complete — moving to 2.3 / 3 next
**Branch:** `feature/sprint6-security-baseline` (6 audit-pipeline commits unmerged)
**Overall progress:** ~55% of Sprint 6.1 complete; ~10/22 sprints overall
**Last updated:** 2026-05-03

## Active sprint goal

Establish HIPAA-compliant security baseline so ResearchFlow can host institutional pilot conversations: JWT auth wired to PHI endpoints, audit middleware writing to a durable Redis-backed queue, input validation framework, TLS, encryption-at-rest design.

## In progress

- [ ] Phase 1.5 — Wire `Depends(get_current_user)` + `@limiter.limit` onto PHI routes (`sql_on_fhir`, `research`, `analytics`, `materialized_views`, `approvals`); separate service-token auth for agent routes (`mcp`, `a2a`). **Note:** Phase 2.2 middleware now enforces auth on ALL non-allowlisted routes by default; the per-route `Depends` work in this phase is now defense-in-depth rather than primary gating.
- [x] Phase 2.2 — Audit pipeline shipped via 3 issues + CSO review. See "What just shipped" below.
- [ ] Phase 2.3 — Input validation framework via per-domain Pydantic schemas in `app/schemas/`
- [ ] Phase 3a — TLS via `HTTPSRedirectMiddleware` gated by `ENVIRONMENT=production`; uvicorn `--proxy-headers --forwarded-allow-ips="*"`
- [ ] Phase 3b — Encryption-at-rest: `sqlalchemy-utils.EncryptedType` on PHI columns (User.SSN/MRN/DOB/etc.); half-day spike to verify asyncpg compatibility
- [ ] Phase 4 — E2E test (login → SQL query → audit row visible) + remaining `docs/HIPAA_POSTURE.md` sections (Phase 2.2 section already drafted)

**Estimated remaining:** 12-18 working days = 2.5-4 calendar weeks (Phase 2.2 done; ~5 days saved vs original estimate)

## Blockers / decisions needed

- Encryption-at-rest spike must run against Postgres (asyncpg) — SQLite mode doesn't support `EncryptedType`. Production must be Postgres; documented as deployment requirement.
- No external pilot user identified. Sprint 6.1 finish-line decision was "ship sales-grade HIPAA posture" — not "wait for users." Outreach is parallel work, not a blocker.

## What just shipped

Sprint 6.1 Phase 2.2 — audit pipeline (6 commits on `feature/sprint6-security-baseline`, 74 audit tests, ready for merge):

- `d277723` (2026-05-03) — Finding 2 fix: gate detailed health payload behind auth (two-tier `/health/ready` + `/health/ready/detailed`)
- `a7840fa` (2026-05-03) — Finding 3 fix: correct schema versioning claim in HIPAA doc
- `1b30e5c` (2026-05-03) — Finding 1 fix: allow `/a2a/token` through middleware (bootstrap deadlock)
- `d9a595c` (2026-05-03) — Issue #3: at-least-once durability + drain supervision + `/health/ready` + `docs/HIPAA_POSTURE.md` Phase 2.2 section
- `2183ed5` (2026-05-03) — Issue #2: default-deny classifier + fail-closed pre/post pair + middleware-side JWT decode
- `744b328` (2026-05-03) — Issue #1: tracer bullet — audit one PHI route end-to-end

Earlier in Sprint 6.1:

- `c3e0280` (2026-05-02) — admin dashboard graceful handling when DB unreachable
- `803152b` (Phase 2.1) — HIPAA-compliant audit logging *schema* (table only; middleware shipped in Phase 2.2)
- `5476255` (Phase 1.4) — API rate limiting via SlowAPI
- `3e8e877` (Phase 1.3) — bcrypt password hashing
- `db8b406` (Phase 1.2) — user management CRUD endpoints
- `36062af` (Phase 1.1) — JWT authentication

## Key numbers

- Tests: LangGraph migration suite covers `test_agent_adapter.py` (24), `test_approval_bridge.py` (26), `test_langgraph_persistence.py` (14), `test_langgraph_workflow.py` (20), plus E2E. Phase 2.2 audit pipeline adds 74 tests across 8 new test files (classifier, principal, middleware, drain, drain_v2, main_wiring, resource_map, health).
- Agents: 6 production agents (Requirements, Phenotype, Calendar, Extraction, QA, Delivery)
- Workflow nodes: 15 in custom FSM (`app/orchestrator/`, production) + 17 in LangGraph FSM (`app/langchain_orchestrator/langgraph_workflow.py`, behind `USE_LANGGRAPH_WORKFLOW` flag)
- Performance: 10-100x query speedup from materialized views; <10ms Redis speed-layer latency
- SQL injection: 30 vulnerabilities fixed in Sprint 6 (parameterized queries everywhere)
- Staleness flagged: CLAUDE.md previously claimed "23-state" (actual: 17 nodes) and "12 LangSmith integration tests" (actual: 1 in `test_langsmith_integration.py`). Treat any unverified count from archived sprint reports the same way.

## Reference artifacts

- Strategic design doc: `~/.gstack/projects/jagnyesh-researchflow/jagnyesh-feature-sprint6-security-baseline-design-20260502-233911.md`
- Phase 2.2 implementation design (10 grilled decisions): `~/.gstack/projects/jagnyesh-researchflow/jagnyesh-feature-sprint6-security-baseline-phase-2-2-audit-middleware-design-20260503-180000.md`
- Test plan: `~/.gstack/projects/jagnyesh-researchflow/jagnyesh-feature-sprint6-security-baseline-eng-review-test-plan-20260503-001500.md`
- Active sprint detail: `docs/sprints/SPRINT_06_IMPLEMENTATION.md`
- HIPAA posture: `docs/HIPAA_POSTURE.md` (Phase 2.2 section drafted; Phase 3a/3b/4 sections pending)
- Open GitHub issues for Phase 2.2: #1, #2, #3 (all complete, awaiting merge)
