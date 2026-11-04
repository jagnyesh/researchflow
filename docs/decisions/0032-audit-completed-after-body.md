---
sprint: null
date: 2026-11-04
status: accepted
supersedes: []
superseded_by: null
related: [0011-sprint-6-1-phase-2-2-audit-middleware.md, 0029-api-error-path-phi-safe-500s.md]
---

# Audit COMPLETED is written after the response body, with its real outcome (#224)

**Amends** ADR 0011 decision (1) for the post-event, and **resolves** the "out of reach" follow-up in ADR 0029. Both are left unedited under the append-only convention.

**Problem.** The audit middleware wrote `PHI_ACCESS_COMPLETED` as soon as `call_next` returned, before any of the body was sent. A body that failed mid-stream therefore produced three bad outcomes:
- the client received a truncated 200;
- the audit trail recorded `COMPLETED(200)` for a failed delivery;
- the server logged the exception message.

Starlette's `call_next` hides that failure from a `BaseHTTPMiddleware`. The body just ends, and the original exception is re-raised only after the middleware has returned.

**Decision (owner, 2026-11-04).** Record the honest outcome, at the cost of the post-event's fail-closed 503.
- **When COMPLETED is written.** For every response that streams through `call_next`, `COMPLETED` is enqueued after the body has been fully sent, with the real status: 500 if the body failed.
- **Failed post-write.** If that enqueue fails, the middleware logs `PHI_ACCESS_COMPLETED not recorded …` and the response stands. It cannot become a 503, because the headers are already gone. This changes ADR 0011's "5xx if Redis enqueue fails" for the post-event only.
- **What still fails closed.**
  - The pre-event `PHI_ACCESS_REQUESTED` still returns a 503 when its enqueue fails, before any PHI is read.
  - The middleware's own #180 500 response (`_call_next_or_500`) has no body to stream, so its `COMPLETED` keeps the 503.
- **`AuditBodyGuard`.** A pure-ASGI guard installed just inside the audit middleware (`install_audit_middleware`). It catches an exception raised after the response started:
  - it logs only the type and ref (`log_internal_error`);
  - it marks the request so the audit records a 500;
  - it re-raises `RuntimeError("response body failed (ref: …)")` with its context suppressed.

  The server's "Exception in ASGI application" line therefore carries only the type and ref. Checked under real uvicorn: the PHI needle was absent from its log, and the audit recorded `COMPLETED(500)`.
- **`BackgroundTasks`.** These run after the response, outside the audited body. No route used them. The one unused `BackgroundTasks` parameter (`/analytics/materialized-views/refresh-all`) is removed, and a test now fails if `app/` uses `BackgroundTasks` or `.add_task(`. A future background task needs this same treatment first.

**Known limits ("real outcome" means a body that raised).**
- **Client disconnect mid-stream** is recorded as COMPLETED with the response status. Starlette ends the inner stream cleanly, so a truncated delivery the client abandoned reads as a success. That is unchanged from before this ADR.
- **A yield-dependency teardown that raises after the body was fully sent** is logged with a ref (no PHI), but the request is audited with the response status.
- **Middleware order.** `AuditBodyGuard` must be the innermost middleware. A `BaseHTTPMiddleware` inside it would end the body before the guard flags the failure. The wiring test pins this.

**Consequences.**
- A dropped Redis post-write after the body leaves a `REQUESTED` with no `COMPLETED`. That gap is visible in the log line and in the audit trail. Before this change it was a 503 the client saw.
- A `REQUESTED` with no `COMPLETED` now means "post-write lost". It no longer means "unhandled exception", which #180 already closed.
- Tests: `tests/test_audit_after_body.py`.
