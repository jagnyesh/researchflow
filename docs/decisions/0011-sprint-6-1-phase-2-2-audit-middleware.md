---
sprint: 6.1
date: 2026-05-03
status: shipped
supersedes: []
superseded_by: null
related: []
---

# Sprint 6.1 Phase 2.2 — Audit middleware: fail-closed default-deny, at-least-once queue, accept dupes

Three coupled decisions for the Redis-queue audit pipeline. **(1) Failure semantics:** fail-closed on PHI routes (5xx if Redis enqueue fails), fail-open on a small non-PHI allowlist (`/health*`, `/auth/login|refresh|logout`, `/`, `/docs*`, `/openapi.json`). Silently dropping PHI-access events is the OCR-finding pattern; 5xx-ing `/health` breaks liveness checks. **(2) Route classification:** default-deny — every route is treated as PHI unless explicitly allowlisted. New PHI-touching routes get audited by inertia rather than by developer discipline; `/a2a`, `/mcp`, `/users` are correctly captured because agent flows and admin actions touch PHI. Blast radius accepted: a Redis outage 5xxs the entire app minus the allowlist. **(3) Queue pattern:** at-least-once via processing list (`RPUSH audit:queue` on write; `BRPOPLPUSH audit:queue audit:processing` on drain; `LREM audit:processing` after Postgres INSERT; lifespan startup recovery sweep moves orphaned `audit:processing` entries back to `audit:queue`). **AuditLog accepts dupes — dedup at query time; idempotency-key deferred to Phase 2.2.1.** Append-only forensic log; auditors care about presence, not exactly-once.
