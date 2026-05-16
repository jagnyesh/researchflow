---
sprint: 6.1
date: 2026-05-04
status: shipped
supersedes: []
superseded_by: null
related: []
---

# Sprint 6.1 Phase 2.3 — Input validation framework: PHI-safe error responses, hardening with HIPAA-scoped priority, hard-break migration

Three coupled decisions for the input validation framework. **(1) Framework + hardening with HIPAA-scoped priority:** ship reusable typed primitives (`ShortText`/`MediumText`/`LongText`/`BoundedDict`/`IRBNumber`) and a `PHIInputModel` base class in `app/schemas/`, then migrate the 12 highest-priority request models (Tier 1 PHI/LLM-touching: `sql_on_fhir`, `research`, `approvals`, `analytics`, `mcp`; Tier 2 credentials: `auth`, `users`, `a2a`). Response models stay loose (we emit, don't receive). `Dict[str, Any]` fields get a `BoundedDict(max_keys=100, max_depth=5)` validator now; explicit shape work deferred to Phase 2.3.1. Permissive `IRBNumber` regex `^IRB[-/_]?[A-Z0-9-]+$` supports IRB-format variation across deployment environments. `SQLQueryRequest.sql` gets length cap only — keyword filtering is HIPAA security theater that an external compliance reviewer spots and loses confidence over; DB-level least-privilege user is the right control layer. **(2) PHI-safe 422 response:** central `RequestValidationError` handler returns `{loc, msg, type}` per error only — `input`, `url`, `ctx` stripped to close the Sentry/Datadog leak vector by construction. No separate `VALIDATION_FAILURE` audit event — Phase 2.2's pre+post pair already records `status_code=422`. **(3) Hard-break migration:** no `HARDEN_INPUTS` env var (same HIPAA-gun trap as Phase 2.2's no-AUDIT_ENABLED rule); breaking constraint changes ship with test-fixture fixes in the same PR. Per-router layout in `app/schemas/` matches existing codebase organizational style; per-domain DDD layout would be the only directory in the codebase using that pattern.
