# Architecture Decision Record

Append-only. One entry per sprint capturing the decision and the *why* — not the implementation.

---

## Sprint 4 — Keep custom FSM in production; LangGraph as parallel migration target

Benchmarked LangGraph against the existing custom orchestrator (71/71 tests passed both sides). LangGraph won on observability, durability, and maintainability; custom won on incumbency and zero-risk path. **Chose: keep custom in production, build LangGraph migration in parallel behind feature flag.** Migration uses adapter pattern over rewrite to preserve 1,500+ lines of agent business logic.

## Sprint 4.5 — Lambda batch layer via materialized views

Need cohort-count latency under 50ms. Two options: query optimization (incremental, capped) vs precomputed views (10-100x speedup, refresh complexity). **Chose: PostgreSQL materialized views in `sqlonfhir` schema, refreshed nightly.** Synchronizes with 24hr Redis TTL on the speed layer (Sprint 5.5) so the merge window is bounded.

## Sprint 5 — LangSmith for observability over custom logging

Custom structured logging vs LangSmith with `@traceable`. Custom gives full control; LangSmith gives trace replay, cost tracking, and prompt versioning out of the box. **Chose: LangSmith** at <5ms overhead per call. Trade: vendor dependency, but key rotation runbook documented and traces are exportable.

## Sprint 5.5 — Redis as Lambda speed layer

Need <1 minute data freshness. Options: Kafka + stream processor (heavyweight, ops cost) vs Redis with TTL (24hr) + HybridRunner merge. **Chose: Redis.** Reuses existing Redis deployment, fits the 24hr-Redis / nightly-MV synchronization model, and HybridRunner deduplicates on the merge.

## Sprint 6 — Parameterized SQL via SQLAlchemy `text()` + bound params

30 SQL injection vulnerabilities found via Bandit. Two remediation patterns: ORM-only (rewrite all dynamic SQL) vs `text()` with named bind params (preserves SQL clarity). **Chose: `text()` + bound params** returning `(sql, params)` tuples from generators. Easier to audit and keeps the SQL-on-FHIR query strings readable.

## Sprint 7 — LangGraph migration finalized via singleton checkpointer + LangSmith tracing

Bug #11 surfaced: AsyncSqliteSaver was being recreated per workflow invocation, causing event-loop conflicts and 100% async failure. **Chose: singleton checkpointer pattern with `threading.Lock` for atomic recreation on event-loop ID change.** All 6 production agents instrumented with `@traceable`. Gradual rollout via `LANGGRAPH_ROLLOUT_PCT` percentage flag rather than binary toggle.

## Sprint 6.1 — Sales-grade HIPAA posture over feature work, before any pilot user

Diagnostic via /office-hours surfaced no external pilot user despite 22 sprints shipped. Two paths: pivot to feedback-loop infrastructure vs finish security hardening. **Chose: finish security hardening (Phases 1.5, 2.2, 2.3, 3a, 3b, 4)** because institutional sales conversations require HIPAA documentation and the alternative defers the demand question without resolving it. Outreach is parallel work, not a blocker.

## Sprint 6.1 — Durable audit pipeline via Redis queue, not BackgroundTasks

Initial design used FastAPI `BackgroundTasks` for audit writes. Codex review flagged: data loss on uvicorn worker crash, deploy, or OOM. **Chose: sync write to Redis `audit:queue` list inside request middleware, asyncio background drain task in `app/main.py` lifespan flushes to `audit_logs` table.** If Redis dies, audit writes fail loudly — correct posture for HIPAA. Reuses existing Redis deployment.

## Sprint 6.1 — Split human/agent auth, not unified JWT

Agent traffic (`mcp`, `a2a` routes) authenticating with the same JWT issuance flow as humans would 401-itself on every internal call. **Chose: separate `verify_service_token()` helper reusing existing `app/a2a/auth.py` JWT issuance for agent routes;** human routes use `Depends(get_current_user)`. Two auth models, one issuer.

## Sprint 6.1 — Documentation reorg: split CLAUDE.md, create CONTEXT/DECISIONS/BACKLOG, install mattpocock/skills

CLAUDE.md grew to 978 lines, claiming Sprint 7 was "ready for production rollout" while Sprint 6.1 was the actual active work. ~16K tokens auto-loaded per session of stale prose. **Chose: slim CLAUDE.md to ~80 lines with `@`-imports; create CONTEXT.md (current state), DECISIONS.md (this file), BACKLOG.md (forward plan); install mattpocock/skills globally for `/caveman` and `/grill-with-docs`.** Hooks added in Phase 2 for HIPAA path enforcement and SQL validation.

## Sprint 6.1 Phase 2.2 — Audit middleware: fail-closed default-deny, at-least-once queue, accept dupes

Three coupled decisions for the Redis-queue audit pipeline. **(1) Failure semantics:** fail-closed on PHI routes (5xx if Redis enqueue fails), fail-open on a small non-PHI allowlist (`/health*`, `/auth/login|refresh|logout`, `/`, `/docs*`, `/openapi.json`). Silently dropping PHI-access events is the OCR-finding pattern; 5xx-ing `/health` breaks liveness checks. **(2) Route classification:** default-deny — every route is treated as PHI unless explicitly allowlisted. New PHI-touching routes get audited by inertia rather than by developer discipline; `/a2a`, `/mcp`, `/users` are correctly captured because agent flows and admin actions touch PHI. Blast radius accepted: a Redis outage 5xxs the entire app minus the allowlist. **(3) Queue pattern:** at-least-once via processing list (`RPUSH audit:queue` on write; `BRPOPLPUSH audit:queue audit:processing` on drain; `LREM audit:processing` after Postgres INSERT; lifespan startup recovery sweep moves orphaned `audit:processing` entries back to `audit:queue`). **AuditLog accepts dupes — dedup at query time; idempotency-key deferred to Phase 2.2.1.** Append-only forensic log; auditors care about presence, not exactly-once.
