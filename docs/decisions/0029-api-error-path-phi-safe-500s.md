---
date: 2026-10-21
status: accepted
supersedes: []
superseded_by: null
related: [0007-sprint-6-1-hipaa-security-baseline.md, 0028-sprint-6-7-exploratory-llm-sql-synthesis.md]
---

# API error paths: PHI-safe 500s through a per-site helper (#175)

**Context.** Thirty `except Exception` blocks in `app/api/{research,approvals,analytics,materialized_views}.py` ran `raise HTTPException(500, detail=str(e))` and `logger.error(f"...{e}")`. A SQLAlchemy `StatementError` string includes the failed statement's bound parameters. A failed `POST /research/submit` therefore returned the INSERT's `researcher_name`, `researcher_email` and `irb_number` in the response body, and wrote them to the log. `initial_request`, a PHI column, is part of that same parameter list. The Phase 2.3 PHI-safe 422 handler (`app/schemas/_errors.py`) closed this vector for validation errors, but nothing closed it for 500s.

**Decision.** Add one helper, `internal_error(logger, context, exc)`, in `app/schemas/_errors.py`. Each 5xx site raises what it returns:

- **Response:** `HTTPException(500, detail="Internal server error (ref: <ref>)")`. `<ref>` is a per-error `uuid4().hex[:12]`. `detail` stays a string; status stays 500.
- **Log:** one ERROR line with `context`, `ref`, the chain of exception *type names* (`exc`, `__cause__`, `__context__`, `.orig`), and the traceback *frames*. It **never** includes an exception message (`str(exc)`, `args`, SQL parameters).
- **Guard:** an AST test over `app/api/**` fails in either of two cases. First, a bound exception name (any `except <T> as e`) is used for anything other than an argument to the helpers. The only exception is the ValueError→4xx carve-out below. Second, `traceback.format_exc`/`print_exc`/`format_exception`, `sys.exc_info`, `logger.exception`, or an `exc_info=` keyword appears anywhere in `app/api/**`. The guard is syntactic: a message routed through an unrelated variable can still evade it. The wire tests are the backstop.
- **Subprocess output** (`POST /analytics/materialized-views/create-all`) is never returned or logged. The script's stdout echoes `HAPI_DB_URL` (credentials) and asyncpg error text, and a non-zero exit code becomes `internal_error`.

## Considered options

- **Global `Exception` handler, with the per-site blocks deleted.** Rejected. Starlette runs `Exception` handlers in `ServerErrorMiddleware`, which sits *outside* the audit middleware. `audit_middleware.py` awaits `call_next` with no `try`, so an exception passing through it emits `PHI_ACCESS_REQUESTED` with no `PHI_ACCESS_COMPLETED`. Fixing the response leak this way would open an audit-integrity gap on every 500. The per-site helper keeps the 500 a *response* inside the stack, so the audit pair stays intact.
- **Global handler plus an audit-middleware `try` backstop.** The backstop half shipped in #180. The audit middleware converts any exception raised **before the response starts** into the same PHI-safe 500 response (`_call_next_or_500`). `PHI_ACCESS_COMPLETED(500)` is still emitted, and the server never sees, or logs, the message. A global `Exception` handler remains unneeded. Exceptions raised *after* the response starts are out of reach, because `call_next` has already returned. That covers a failing `StreamingResponse` body (which also records COMPLETED(200)) and a `BackgroundTasks` task, and the server logs their messages. Today the only such paths are the two `FileResponse` downloads, where a failure would be an `OSError` about a file path, and no route calls `add_task`. This is tracked as a follow-up. Before #180, unhandled exceptions skipped `COMPLETED` entirely.
- **Log `str(exc)` and keep only the response generic** (the `feasibility_service` #39 precedent). Rejected. asyncpg and SQLAlchemy messages carry row values (#39's `'Alice Smith'` example), and logs are a PHI sink too. The type chain, frames and `ref` are enough to locate a failure. The message is reproducible from those in a dev environment.
- **A structured `detail` object (`{"error":..., "ref":...}`).** Rejected. No consumer parses 500 bodies, and changing `detail`'s type affects every client for no gain.
- **Request-ID middleware for correlation.** Rejected as speculative. A per-error ref correlates response to log, which is all #175 needs.

## Consequences

- **The two `ValueError → 400` sites keep `detail=str(e)`** (`approvals.py` process-approval, `analytics.py` create-ViewDefinition). Every direct `ValueError` source behind them writes its own message from internal IDs, status values or ViewDefinition structure. `decision` is a `Literal`, so `"Invalid decision: …"` can't be reached. Workflow continuation (`request_facade._resume_workflow_after_approval`) catches every exception, so nothing raised there reaches the 400. Bind-time DB errors arrive wrapped as `StatementError`, not `ValueError`. The residual risk is a future `ValueError` written to include data; the guard's carve-out covers the shape of the code, not the message content.
- **Sites that don't re-raise `HTTPException`** before `except Exception` (for example `research.py` submit) still turn an inner 404 into a 500, as they do today. Status behavior is unchanged; only the body and the log line change.
- **Line breaks in `context` are escaped** because contexts interpolate path params (`request_id`, `view_name`). This blocks log-line forging. The public `/health` cache probe logs at WARNING, not ERROR.
- **Debugging a 500 now starts from `ref`.** Find the log line, read the type chain and frames, and reproduce locally.
