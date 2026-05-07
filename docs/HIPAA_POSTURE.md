# HIPAA Security Posture

ResearchFlow's compliance-relevant controls, organized by HIPAA Security Rule
section. This doc is the artifact for institutional security reviews.

Sprints align as: **Sprint 6** (parameterized SQL, JWT auth, RBAC, rate limiting,
audit log schema), **Sprint 6.1** (audit pipeline + middleware, TLS, encryption-at-rest).

---

## Phase 2.2 — HIPAA-compliant audit pipeline

**Status:** complete (Issues #1, #2, #3 — see `git log --grep "feat(audit)"`).
**Maps to:** §164.312(b) "Audit Controls" — implement hardware, software, and/or
procedural mechanisms that record and examine activity in information systems
that contain or use ePHI.

### Pipeline architecture

```
┌────────────────────────────────────────────────────────────────────┐
│  PHI request                                                       │
│       │                                                            │
│       ▼                                                            │
│  ┌─────────────────────────────────────────┐                       │
│  │ audit_middleware                        │                       │
│  │  1. classify_route(path)                │                       │
│  │  2. resolve_principal (JWT or service)  │                       │
│  │  3. RPUSH audit:queue (PRE event)  ◄────┼── fail-closed gate    │
│  │  4. call_next(request)                  │                       │
│  │  5. RPUSH audit:queue (POST event)      │                       │
│  └─────────────────────────────────────────┘                       │
│       │                                                            │
│       ▼ (async, separate task)                                     │
│  ┌─────────────────────────────────────────┐                       │
│  │ audit_drain_loop                        │                       │
│  │  BLMOVE queue -> processing             │                       │
│  │  bulk INSERT into audit_logs            │                       │
│  │  LREM processing                        │                       │
│  │  poison pill -> audit:dead_letter       │                       │
│  └─────────────────────────────────────────┘                       │
│       │                                                            │
│       ▼                                                            │
│  Postgres audit_logs (append-only)                                 │
└────────────────────────────────────────────────────────────────────┘
```

Two Redis instances are deployed:

- **`redis` (port 6379)** — speed-layer cache. `--maxmemory 256mb --maxmemory-policy allkeys-lru`. Cache entries can be evicted under memory pressure.
- **`redis-audit` (port 6380)** — audit pipeline. `--maxmemory 32mb --maxmemory-policy noeviction --appendonly yes`. **Writes fail loudly when full** rather than silently dropping queued audit events.

The two are isolated so memory pressure on the cache cannot evict queued audit events.

### Default-deny route classification

Every route is treated as PHI **unless** explicitly listed in `NO_AUDIT_ALLOWLIST`
(`/health*`, `/`, `/docs*`, `/openapi.json`). A second tier `NON_AUTH_ALLOWLIST`
(login/refresh/logout) does not require auth but is still audited as login activity.

A new PHI-touching route therefore gets audited by inertia, not by developer
discipline. This prevents the most common HIPAA finding pattern: "you forgot to
audit endpoint X."

### Failure modes

| Scenario | Behavior | Why this posture |
|---|---|---|
| `redis-audit` unreachable | PHI routes return 503 before handler runs | Silently dropping a PHI-access event is a HIPAA finding. Liveness probes (`/health/*`) are on the allowlist so they continue to respond. |
| Audit queue at memory cap | `RPUSH` raises OOM → fail-closed → 503 | `noeviction` policy ensures we never silently drop a queued event. |
| Drain task crashes | Supervisor wraps drain with `min(60, 2**attempts)` exponential backoff; `_drain_state["restart_count"]` increments | `/health/ready` exposes restart count + drain freshness so an operator/orchestrator can react. |
| Drain task crashes mid-batch | Items left in `audit:processing`. Lifespan recovery sweep on next process startup moves them back to `audit:queue` | At-least-once semantics. Duplicates are accepted (append-only forensic log). |
| Poison-pill payload (invalid JSON, schema mismatch) | Routed to `audit:dead_letter` list with serialized error attached; pipeline continues | Operator can inspect dead-letter; never blocks the rest of the pipeline. |
| Unauthenticated request to a PHI route | `UNAUTH_PHI_ATTEMPT` event emitted with `user_id=null`, then 401 returned | Captures attempted-access signal — auditors specifically ask for this. |

### PHI boundary

**`audit_logs` is metadata only and explicitly NOT PHI.**

| Captured | Not captured |
|---|---|
| `timestamp`, `user_id`, `event_type`, `method`, `route_template` (e.g., `/research/{request_id}`), `status_code`, `latency_ms`, `ip_address`, `user_agent`, `phi_accessed=True`, `result`, `resource_type`, `resource_id` (path-param ID, not record contents) | Request body, query strings, response body, resolved-and-leaked path identifiers (we use the route template, not the resolved path) |

**Why this matters:**
1. `audit_logs` does not need encryption-at-rest (Phase 3b's `EncryptedType` scope is bounded by this decision).
2. Redis queue values are not PHI in transit — `redis-audit` doesn't need TLS termination beyond what's already at the transport layer.
3. The OCR auditor question "does your audit log itself contain PHI?" has the answer "no."

For "what query did user X run that returned N rows" forensics, that is a separate concern (planned for Sprint 9's `query_executions` table — which **will** be PHI and **will** be encrypted).

### Schema versioning

Every payload includes `"schema_version": 1`. The drain reads payload fields
defensively (`payload.get(field)`) so additive changes (new optional fields) are
forward-compatible without changes. Version-aware dispatch will be added if/when
a non-additive schema change (renamed or removed field) ships — at that point a
v1→v2 handler split lives in `_payload_to_audit_log`.

### Observability

`/health/ready` returns 503 when any of the following is true:

- `audit_redis` is unreachable or unset
- queue depth > `AUDIT_QUEUE_DEPTH_503_THRESHOLD` (default 10000; env-tunable)
- last successful drain was > `AUDIT_DRAIN_STALENESS_503_SECONDS` ago (default 30; env-tunable)

The endpoint payload also exposes `audit_queue_depth`, `audit_processing_depth`,
`drain_last_success_seconds_ago`, and `drain_restart_count` for operator inspection.

### Test coverage

Sprint 6.1 Phase 2.2 audit pipeline test surface (~70 tests across):
- `tests/test_audit_classifier.py` — default-deny route classification
- `tests/test_audit_principal.py` — JWT and service-token resolution
- `tests/test_audit_middleware.py` — pre/post pair, fail-closed, UNAUTH path
- `tests/test_audit_drain.py` — single-event drain (Issue #1 back-compat)
- `tests/test_audit_drain_v2.py` — at-least-once, batching, recovery sweep, poison pill, supervisor restart
- `tests/test_audit_resource_map.py` — typed resource_type/resource_id population
- `tests/test_audit_health.py` — `/health/ready` audit pipeline integration
- `tests/test_audit_main_wiring.py` — middleware installed on the FastAPI app

---

## Phase 2.3 — Input validation framework

**Status:** complete (Issues #4, #5, #6 — see `git log --grep "feat(schemas)"`).
**Maps to:** §164.312(c)(1) "Integrity" — protect ePHI from improper alteration; §164.312(b) "Audit Controls" indirectly (validation failures still produce audit events through Phase 2.2's pre/post pair).

### Goal

Bound, type, and validate every request body that flows user input into LLMs, SQL generation, agents, or credential checks. Strip rejected values from 422 responses to close the Sentry/Datadog PHI-leak vector.

### Framework architecture

```
app/schemas/
├── __init__.py        re-exports framework primitives
├── _base.py           PHIInputModel — strict-by-default base class
├── _types.py          ShortText, MediumText, LongText, BoundedDict, IRBNumber, EmailStr
├── _errors.py         phi_safe_validation_handler — wired into app.main lifespan
└── {router}.py × 8    per-router schema files
```

### Constraint conventions

| Type | Cap | Used for |
|---|---|---|
| `ShortText` | 200 chars | names, IDs, view_names, tags |
| `MediumText` | 2,000 chars | notes, reasons, departmental descriptions |
| `LongText` | 50,000 chars | `initial_request`, `sql`, free-form prose (~10K LLM tokens; rejects 1MB DoS bodies) |
| `BoundedDict` | 100 keys × 5 depth | `Dict[str, Any]` escape-hatch fields — JSON-bomb defense |
| `EmailStr` | RFC 5321 | every `email` field across all routers |
| `IRBNumber` | regex `^IRB[-/_]?[A-Z0-9-/_]+$`, max 50 | IRB approval numbers (permissive — supports institutional variation) |

### PHI-safe error response contract

422 body returns only `{loc, msg, type}` per error:

```json
{
  "detail": [
    {"loc": ["body", "researcher_email"], "msg": "value is not a valid email address", "type": "value_error"},
    {"loc": ["body", "irb_number"], "msg": "String should match pattern '^IRB[-/_]?[A-Z0-9-/_]+$'", "type": "string_pattern_mismatch"}
  ]
}
```

**Stripped from default Pydantic response:**
- `input` — the rejected value (PHI/credential leak)
- `url` — Pydantic-internal pointer that leaks Pydantic version
- `ctx` — constraint metadata; some Pydantic error types put input into `ctx.input`

**Why strip everything (not field-aware redaction):** defensibility to institutional reviewer is unconditional — "validation errors never contain field values." Field-aware allowlists invite the question "what if a field is missing from the allowlist?" Closes Sentry/Datadog leak vector by construction.

**Logging:** handler logs `validation_failed loc=… type=…` only — never the input value or request body.

**No separate `VALIDATION_FAILURE` audit event** — Phase 2.2's pre+post middleware pair already records `PHI_ACCESS_REQUESTED` and `PHI_ACCESS_COMPLETED status_code=422`. Auditors reconstruct from the pair.

### What `audit_logs` does NOT contain (still applies after Phase 2.3)

`audit_logs` remains **metadata only**, NOT PHI. The Phase 2.3 `BoundedDict` validators bound the size of dict fields that flow into request bodies, but those dicts are not stored in `audit_logs.event_data`. Phase 2.2's PHI boundary (route_template, not resolved path; status_code; latency_ms) is unchanged.

### Why no SQL keyword filtering on `SQLQueryRequest`

The `/sql_query` endpoint exists to run SQL. Restricting `DROP|DELETE|INSERT|UPDATE|ALTER|CREATE` via regex would:
1. Be HIPAA security theater — trivially bypassed by `SELECT * FROM x; DROP/* */ TABLE y` or comment-encoding. A reviewer who knows what they're doing spots it as such and loses confidence in the rest of the security posture.
2. Break the endpoint's reason for being.

**The right control layer is DB-level least-privilege**: the API user has SELECT-only on the FHIR schema. That is the institutional reviewer's expected answer.

`SQLQueryRequest.sql` is bounded by `LongText` (50K cap, DoS defense) and that is the only validation applied.

### Why permissive IRB regex (not canonical)

Sales-grade HIPAA targets **multiple institutions**, each of which uses different IRB number formats:

```
IRB-001                  IRB-2024-001            IRB-2024-HF-001
IRB-2025-001             IRB-2025-E2E-TEST-001   IRB/2025/04/123
```

A canonical regex like `^IRB-\d{4}-\d{3,8}$` would reject 2 of 5 existing fixture formats and an unknown number of real institutional formats. Permissive regex catches obvious garbage (`"hello"`, `"DROP TABLE"`) without committing to one institution's format.

### Failure modes

| Scenario | Behavior |
|---|---|
| Request body has malformed email | 422 with PHI-safe body, audit pair emitted with `status_code=422` |
| Request body contains unknown field (`is_admin: true`) | 422 with `extra_forbidden` error — defends against attacker-supplied keys getting persisted |
| Request body contains `Dict[str, Any]` with 101+ keys | 422 — JSON bomb defense |
| Request body contains nested dict 6+ levels deep | 422 — JSON bomb defense |
| Request `Authorization` JWT expired but body validates | Phase 2.2 middleware emits `UNAUTH_PHI_ATTEMPT`, returns 401 — body is never validated (auth comes first) |

### Phase 2.3.1 — deferred

`Dict[str, Any]` fields (`structured_requirements`, `requested_changes`, `modifications`, `search_params`, `view_definition`) are bounded by `BoundedDict` but not shape-validated. Discriminated-union shape work requires per-dict investigation (what shapes occur in production? what does consumer code do with them?) that is 2-3 weeks per dict. Deferred until Sprint 11+ when domain stability allows. Tracked in `BACKLOG.md`.

### Test coverage

163 schema tests across 9 test files plus 1 framework integration test:

- `tests/test_schemas/test_types.py` (23) — typed primitives
- `tests/test_schemas/test_bounded_dict.py` (11) — JSON-bomb defense
- `tests/test_schemas/test_base.py` (5) — PHIInputModel base class
- `tests/test_schemas/test_errors.py` (7) — PHI-safe handler unit tests
- `tests/test_schemas/test_main_wiring.py` (2) — handler installed on `app.main:app`
- `tests/test_schemas/test_sql_on_fhir.py` (10) — tracer bullet
- `tests/test_schemas/test_research.py` (28), `test_approvals.py` (19), `test_analytics.py` (15), `test_mcp.py` (6) — Tier 1
- `tests/test_schemas/test_auth.py` (7), `test_users.py` (17), `test_a2a.py` (6) — Tier 2
- `tests/test_schemas/test_validation_integration.py` (1) — end-to-end: malformed body → PHI-safe 422 + audit pre/post pair

---

## Phase 3a — TLS enforcement

**Status:** complete (Issue #7 — see `git log --grep "feat(tls)"`).
**Maps to:** §164.312(e)(1) "Transmission Security" — implement technical security measures to guard against unauthorized access to ePHI being transmitted over an electronic communications network.

### Goal

Every PHI-touching request must be encrypted in transit. Browsers must refuse HTTP downgrades. Local development continues to work over plain HTTP without env-var gymnastics.

### Deployment requirement

**Production deployments must run the application container on a private network behind a TLS-terminating proxy.** The proxy (k8s ingress, AWS ALB, GCP Load Balancer, Render/Fly platform) is responsible for:
- TLS 1.2+ minimum
- Cipher suite policy
- Certificate management (issuance, rotation, OCSP stapling)
- Certificate storage in HSM/Vault if institutional policy requires

The application sees plain HTTP from the proxy with `X-Forwarded-Proto: https` set. uvicorn's `--proxy-headers --forwarded-allow-ips *` rewrites `request.url.scheme` to `"https"` before the app sees the request.

**Why TLS at the LB, not at uvicorn:** institutional pilots deploy via their own platforms. They expect a stateless container that takes plain HTTP from their ingress. BYO-certs into the container creates deployment friction that closes sales doors. Cert management is a separate problem class (Let's Encrypt rotation, ACME challenges, HSM storage) and not Phase 3a-shaped work.

### Redirect contract

Every non-HTTPS request to a non-`/health*` route gets a **308 Permanent Redirect** to the same path on `https://`. Health endpoints (`/health`, `/health/live`, `/health/ready`) pass through without redirect because:
- Load balancers do plain-HTTP probes from internal subnets by default
- LBs don't follow 308s and would silently mark the app unhealthy
- Health endpoints carry no PHI (Phase 2.2 made `/health/ready` return a boolean only)

**308, not 301.** 308 preserves HTTP method and body; 301 may downgrade POST→GET, breaking write requests.

### HSTS configuration

```
Strict-Transport-Security: max-age=31536000; includeSubDomains
```

- **`max-age=31536000` (1 year)** — Chrome's preload-list minimum and the institutional-defensible floor. Anything shorter signals lack of commitment.
- **`includeSubDomains`** — cascades to all current and future subdomains. ResearchFlow has no subdomain story today; setting now forecloses subdomain-on-HTTP footguns later.
- **`preload` is NOT set.** Submitting to `hstspreload.org` hardcodes the domain into Chromium/Firefox/Safari source. Removal is a months-long manual process. Production domain is unknown — committing now is committing to a name that doesn't exist yet. Trivial 5-minute submission once the domain is real.

HSTS is emitted **only on HTTPS responses, not on the 308 redirect**. Browsers ignore HSTS over HTTP per RFC 6797. The header attaches after `call_next`, so the 308 itself is bare.

### Rollback procedure

If HTTPS becomes unavailable in production, browsers with cached HSTS will refuse plain HTTP for up to 1 year. Rollback options:

1. **Fix HTTPS** — restore the LB / cert infrastructure. This is the expected path.
2. **Wait out the cache** — the header tells browsers "trust HTTPS for N seconds since last contact." A user who hasn't visited in 1 year has no cached policy.
3. **Override `HSTS_MAX_AGE`** — set `HSTS_MAX_AGE=300` in the environment so future responses tell browsers to trust HTTPS for only 5 minutes. Doesn't help users with already-cached long max-age.

This is the cost of a 1-year max-age and is acceptable for production-grade HIPAA posture. If the LB/cert infrastructure is unmanaged enough that 1-year HSTS is risky, that infrastructure is itself a HIPAA-compliance concern that needs addressing.

### Environment gating

The TLS middleware is installed at module load **only when `ENVIRONMENT=production`** (strict equality, case-sensitive). Typos (`Production`, trailing space, `prod`) get dev behavior — fail-safe direction. Same posture as Phase 2.2's no-`AUDIT_ENABLED` rule and Phase 2.3's no-`HARDEN_INPUTS` rule.

**Local `make run` and pytest both default to dev mode** (no ENVIRONMENT set → "development" → middleware not installed → no HTTPS redirect → all existing tests work unchanged).

### Open-redirect defense (CSO Finding 1 fix)

The 308 redirect target is constructed from `request.url`, which includes the `Host` header from the incoming request. Without Host validation, an attacker who can set the `Host` header (directly or through a misconfigured LB) steers the redirect to attacker-controlled domains — phishing vector that defeats the entire transport-security narrative.

**Mitigation:** Starlette's `TrustedHostMiddleware` is installed in production when `ALLOWED_HOSTS` is set to anything other than `*`. It validates the `Host` header against the allowlist BEFORE the TLS middleware sees the request. Forged Host → 400 (no 308 leak).

**`ALLOWED_HOSTS=*`** (default) is an explicit opt-out for deployments that haven't allocated their canonical hostname yet. A startup WARNING is logged so the operator sees: `production with ALLOWED_HOSTS=*; Host header not validated. Set ALLOWED_HOSTS=app.example.com to defend against open redirect.`

Production-grade institutions should always set `ALLOWED_HOSTS` to the canonical hostname(s). Subdomain wildcards (`*.researchflow.example`) are supported by Starlette.

**Middleware order in production:**
```
TrustedHost (added last → runs first) → validates Host or 400
TLS enforcement (added 4th → runs 2nd) → HTTP→308 or HSTS
body_size_limit (added 3rd → runs 3rd)
audit_middleware (added 2nd → runs 4th)
rate_limiting (added 1st → runs 5th)
→ handler
```

### Forwarded-allow-ips trust boundary

`FORWARDED_ALLOW_IPS=*` (default) trusts `X-Forwarded-Proto` from any source. **Safe iff the container is on a private network** where only the LB can reach it. If the container is internet-reachable directly, an attacker can spoof `X-Forwarded-Proto: https` on a plain-HTTP request and bypass the redirect.

**Startup warning:** `app/main.py` lifespan logs at WARNING when `ENVIRONMENT=production` AND `FORWARDED_ALLOW_IPS=*`:
```
production with FORWARDED_ALLOW_IPS=*; container must not be internet-reachable directly.
```

Operators with deployment-time knowledge of LB subnets can override: `FORWARDED_ALLOW_IPS=10.0.0.0/8` or comma-separated list.

### Middleware order

```
[outermost — runs first]
  TLS enforcement      ← installed only when ENVIRONMENT=production
  body_size_limit      ← Phase 2.3 fix layer 2
  audit_middleware     ← Phase 2.2 default-deny + fail-closed
  rate_limiting        ← Phase 1.4
  → handler
[innermost — runs last]
```

HTTP redirects don't pollute the audit queue (TLS runs before audit). Same principle as Phase 2.3's body-size-before-audit ordering.

### Test coverage

22 tests in `tests/test_security/test_tls.py`:
- HTTP→308 redirect, HTTPS→HSTS header, `/health*` exempt (no redirect, no HSTS)
- 308 preserves method (POST stays POST) — guards against future "let's switch to 301"
- X-Forwarded-Proto integration via `uvicorn.middleware.proxy_headers.ProxyHeadersMiddleware`
- `is_production()` strict equality (5 typo-rejection parametrize cases + default-unset case)
- HSTS constants: `max-age=31536000`, `includeSubDomains` present, **`preload` absent (regression guard)**
- `install_tls_middleware_if_production` returns False in dev / True + wires middleware in production
- FORWARDED_ALLOW_IPS warning logged in production+`*`, NOT logged in dev or production+specific-CIDR
- TLS middleware NOT on `app.main:app` in dev mode (regression guard against breaking every endpoint test)

---

## Future sections

- **Phase 3b — Encryption-at-rest** (pending)
- **Phase 4 — End-to-end HIPAA narrative** (pending)
