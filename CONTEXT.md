# ResearchFlow — Current State

**Sprint:** 6.1 (Security Baseline)
**Phase:** 3b complete — moving to 4 next
**Branch:** `feature/sprint6-security-baseline` (22 commits unmerged: 8 audit + 8 schema + 3 TLS + 3 encryption)
**Overall progress:** ~95% of Sprint 6.1 complete; ~10/22 sprints overall
**Last updated:** 2026-05-07

## Active sprint goal

Establish HIPAA-compliant security baseline so ResearchFlow can host institutional pilot conversations: JWT auth wired to PHI endpoints, audit middleware writing to a durable Redis-backed queue, input validation framework, TLS, encryption-at-rest design.

## In progress

- [ ] Phase 1.5 — Wire `Depends(get_current_user)` + `@limiter.limit` onto PHI routes (`sql_on_fhir`, `research`, `analytics`, `materialized_views`, `approvals`); separate service-token auth for agent routes (`mcp`, `a2a`). **Note:** Phase 2.2 middleware now enforces auth on ALL non-allowlisted routes by default; the per-route `Depends` work in this phase is now defense-in-depth rather than primary gating.
- [x] Phase 2.2 — Audit pipeline shipped via 3 issues + CSO review.
- [x] Phase 2.3 — Input validation framework shipped via 3 issues + CSO review.
- [x] Phase 3a — TLS enforcement (HTTPS redirect + HSTS) shipped via 1 issue. See "What just shipped" below.
- [x] Phase 3b — Encryption-at-rest shipped via 3 issues (#8 tracer + #9 remaining columns + #10 docs). Tier 1 scope: 4 columns total (`ResearchRequest.initial_request`, `RequirementsData.inclusion_criteria`/`exclusion_criteria`, `FeasibilityReport.phenotype_sql`). Spike outcome: `EncryptedType(JSON)` doesn't round-trip cleanly; fallback to `_EncryptedJSONImpl` TypeDecorator that wraps `StringEncryptedType(Text)` with explicit `json.dumps`/`loads`. Researcher PII deferred to Phase 3b.1.
- [ ] Phase 4 — E2E test (login → SQL query → audit row visible) + `docs/HIPAA_POSTURE.md` end-to-end HIPAA narrative (Phase 2.2 + 2.3 + 3a + 3b sections already drafted)

**Estimated remaining:** 2-4 working days = 0.5-1 calendar week (Phases 3a and 3b done in ~half a day each vs original 1-day estimates; Phase 4 narrative + E2E remain)

## Blockers / decisions needed

- Encryption-at-rest spike: `sqlalchemy-utils.StringEncryptedType` works at the column level on both SQLite and Postgres (it's transparent serialization, not a DB feature). The asyncpg-specific risk is the JSON-column composition (`StringEncryptedType` wrapping a JSON serializer round-trip) — that's the half-day spike. SQLite test path stays; production-on-Postgres remains the deployment requirement for other reasons.
- No external pilot user identified. Sprint 6.1 finish-line decision was "ship sales-grade HIPAA posture" — not "wait for users." Outreach is parallel work, not a blocker.

## What just shipped

Sprint 6.1 Phase 3b — encryption-at-rest (3 commits, 12 encryption tests, ready for merge):

- `1946ac5` (2026-05-07) — Issue #9: encrypt remaining 3 Tier 1 columns (inclusion_criteria, exclusion_criteria, phenotype_sql); spike outcome → `_EncryptedJSONImpl` TypeDecorator workaround for `EncryptedType(JSON)` round-trip bug
- `a7e7da7` (2026-05-07) — Issue #8: tracer bullet — `ResearchRequest.initial_request` encrypted at rest; pluggable `get_encryption_key` callable + lifespan startup gate (RuntimeError on missing/malformed key in production)
- (commit 3 = Issue #10 docs commit)

Sprint 6.1 Phase 3a — TLS enforcement (3 commits, 22 TLS tests, ready for merge):

- `d067068` (2026-05-07) — Issue #7: wire TLS middleware in lifespan + Dockerfile proxy-headers config
- `82a02ca` (2026-05-07) — Issue #7: HTTPS-redirect + HSTS middleware with ENVIRONMENT=production gate
- (commit 3 = this docs commit)

Sprint 6.1 Phase 2.3 — input validation framework (6 commits, 163 schema tests + integration test, ready for merge):

- `d65f1d2` (2026-05-04) — Issue #6: migrate Tier 2 credential models (auth, users, a2a) + framework integration test
- `e07f3f2` (2026-05-04) — Issue #5: migrate Tier 1 PHI models (research, approvals, analytics, mcp)
- `706c6b9` (2026-05-04) — Issue #5: migrate sql_on_fhir to PHIInputModel — tracer bullet
- `12bf6ff` (2026-05-04) — Issue #4: wire PHI-safe RequestValidationError handler in lifespan
- `eec5d6c` (2026-05-04) — Issue #4: framework primitives — PHIInputModel, typed primitives, bounded dict validator

Sprint 6.1 Phase 2.2 — audit pipeline (8 commits on `feature/sprint6-security-baseline`, 74 audit tests):

- `e5a094b` (2026-05-03) — wire E2E test for Issue #2 auth + explicit SQLite to bypass stale .env Postgres
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
