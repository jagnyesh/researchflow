# HIPAA Security Posture

ResearchFlow's compliance-relevant controls, organized by HIPAA Security Rule
section. This doc is the artifact for institutional security reviews.

Sprints align as: **Sprint 6** (parameterized SQL, JWT auth, RBAC, rate limiting,
audit log schema), **Sprint 6.1** (audit pipeline + middleware, TLS, encryption-at-rest).

---

## Sprint 6.1 baseline — control-by-control summary

This section is the elevator pitch for an institutional reviewer: every Security
Rule control that ResearchFlow's Sprint 6.1 baseline addresses, with a one-line
control description and a pointer to the code that implements it. Per-phase
deep-dives follow below.

| §164.312 paragraph | Control | Implemented by | Tests | Phase |
|---|---|---|---|---|
| (a)(1) Access Control | JWT-bearer authentication on every PHI route | `app/security/auth.py` + `app/security/audit_middleware.py` (default-deny classifier) | 74 audit + 6 auth | 1.1 + 2.2 |
| (a)(2)(i) Unique User Identification | `User.id` (USR-XXXXXXXX) on every audit row | `app/database/models.py::User` + `AuditLog.user_id` | included above | 1.2 + 2.2 |
| (a)(2)(iii) Automatic Logoff | JWT `exp` claim + `failed_login_attempts` lockout | `app/security/auth.py` + `User.locked_until` | 6 auth | 1.1 + 1.3 |
| (a)(2)(iv) Encryption (Addressable) — at rest | Column-level Fernet encryption on Tier 1 PHI columns | `app/security/encryption.py` + `app/security/encryption_keys.py` | 13 encryption | 3b |
| (b) Audit Controls | Default-deny route classifier + at-least-once Redis queue + Postgres `audit_logs` | `app/security/audit_middleware.py` + `audit_drain.py` | 74 audit | 2.2 |
| (c)(1) Integrity | Pydantic `PHIInputModel` framework + parameterized SQL | `app/schemas/_base.py` + 30 SQL injection fixes (Sprint 6) | 163 schema | 2.3 + Sprint 6 |
| (c)(2) Mechanism to Authenticate ePHI | Fernet HMAC-SHA256 detects ciphertext tampering on read | `FernetEngine` (encrypt-then-MAC, IND-CCA2) | covered by 13 encryption | 3b |
| (d) Person or Entity Authentication | bcrypt password hashing + JWT issuance | `app/security/auth.py::create_access_token` | 6 auth | 1.1 + 1.3 |
| (e)(1) Transmission Security | HTTPS-redirect middleware + HSTS | `app/security/tls.py` | 22 TLS | 3a |
| (e)(2)(i) Integrity Controls — in transit | TLS 1.2+ at the load balancer | platform-managed (k8s ingress / ALB) | covered by 22 TLS | 3a |
| (e)(2)(ii) Encryption (Addressable) — in transit | HSTS `max-age=31536000; includeSubDomains` enforced; HTTP redirected with 308 | `app/security/tls.py::tls_enforcement_middleware` | 22 TLS | 3a |

### What an institutional reviewer asks first

**Q1 — "Where is patient PHI at rest in your stack, and how is it protected?"**
Patient PHI lives in HAPI FHIR's separate Postgres (encrypted at the institution's
deployment layer). ResearchFlow's app DB stores derived metadata, audit records, and
four free-form fields that may contain inline patient identifiers from researcher
queries: `ResearchRequest.initial_request`, `RequirementsData.inclusion_criteria`,
`RequirementsData.exclusion_criteria`, `FeasibilityReport.phenotype_sql`. Those four
columns are encrypted at the application layer with Fernet (AES-128-CBC + HMAC-SHA256);
key sourcing is pluggable via `get_encryption_key()` so institutions that mandate KMS or
Vault can swap the function body at deploy without touching column definitions. See
[Phase 3b](#phase-3b--encryption-at-rest).

**Q2 — "Show me the audit trail for a PHI access. What does it record? What does it
NOT record?"**
Every authenticated request to a non-allowlisted route emits two audit rows
(`PHI_ACCESS_REQUESTED` pre-event and `PHI_ACCESS_COMPLETED` post-event with status
code) via a fail-closed default-deny middleware. Records: `route_template` (not
resolved path, so `/users/123` becomes `/users/{id}`), HTTP method, response status,
latency, and JWT principal. Does NOT record: request body, response body, query
strings, headers. The `audit_logs` table is metadata-only by design — see
[Phase 2.2 PHI boundary](#phi-boundary). Durability: at-least-once via Redis
processing-list pattern with crash-recovery sweep on lifespan startup.

**Q3 — "What happens when something goes wrong? Show me the failure mode."**
Three coupled fail-closed postures. **(1) Audit:** if the Redis audit queue is
unreachable, every PHI route returns 5xx (silently dropping access events is the
OCR-finding pattern; we 5xx the app instead). A small allowlist (`/health*`,
`/auth/{login,refresh,logout}`, `/`, `/docs*`, `/openapi.json`) fails open to keep
liveness probes alive and bootstrap unblocked. **(2) Encryption:** if
`ENCRYPTION_KEY_PRIMARY` is missing or malformed in production, FastAPI lifespan +
each streamlit dashboard refuse to start with a clean RuntimeError. No silent fallback
to plaintext writes. **(3) Validation:** malformed bodies return 422 with a PHI-safe
error response that strips `input`, `url`, `ctx` from Pydantic's default 422 shape —
closes the Sentry/Datadog leak vector by construction, not by Sentry config. See
[Phase 2.3 PHI-safe error response contract](#phi-safe-error-response-contract).

**Q4 — "What's NOT covered? Where are the seams?"**
Encryption-at-rest does not protect decrypted values in process memory, in logger
calls (`logger.info(f"req={req.initial_request}")` is a leak vector — application
discipline, not framework guarantee), or in API response bodies the researcher is
authorized to see. The audit pipeline is metadata-only — body-content audit is
deferred indefinitely as it would itself become a PHI store. Researcher PII
(`User.email`, `*.researcher_email`, `User.full_name`) is NOT encrypted at rest —
it's PII not ePHI under §164.312, and `User.email` is the unique-indexed login key;
encryption is deferred to Phase 3b.1 (Sprint 11+ multi-tenant index work).
TLS termination happens at the load balancer / platform, not at uvicorn directly —
deployment requirement is that the container runs on a private network behind
a TLS-terminating proxy. See each phase section's "what this does NOT cover"
subsection for the full carve-out per control.

**Q5 — "Has this been tested end-to-end?"**
`tests/e2e/test_hipaa_baseline_e2e.py` walks one PHI-bearing request through every
Sprint 6.1 control in execution order and asserts each fired: body-size middleware
accepts → audit middleware emits `PHI_ACCESS_REQUESTED` → JWT principal lands on the
audit row → Pydantic validates → `ResearchRequest` row written with ciphertext on
disk (raw `SELECT` bypassing the column type) → audit middleware emits
`PHI_ACCESS_COMPLETED` → drain task flushes both events to `audit_logs`. Plus a
negative-path tracer that confirms a malformed body returns 422 with the PHI-safe
error shape. The test is gated on the audit Redis being reachable; per-phase unit
tests (350+ across Phases 1–3b) cover the controls in isolation.

### Test coverage summary

| Layer | File | Count | Phase |
|---|---|---|---|
| Auth + RBAC | `tests/test_security/test_auth*.py` | ~6 | 1.1–1.4 |
| Audit pipeline | `tests/test_security/test_audit*.py` | 74 | 2.2 |
| Input validation | `tests/test_schemas/test_*.py` | 163 | 2.3 |
| TLS | `tests/test_security/test_tls.py` | 22 | 3a |
| Encryption | `tests/test_security/test_encryption*.py` | 13 | 3b |
| End-to-end | `tests/e2e/test_audit_pipeline_e2e.py`, `test_hipaa_baseline_e2e.py` | 2 | 2.2 + 4 |
| **Total** | | **~280** | |

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

## Phase 3b — Encryption-at-rest

**Maps to:** §164.312(a)(2)(iv) "Encryption (Addressable)" — render ePHI unusable to unauthorized persons via cryptographic mechanism. Storage scope only; in-transit encryption is Phase 3a.

### Goal

Make freeform-PHI columns unreadable on disk to anyone with a database file or backup but no encryption key. Limits the blast radius of a stolen Postgres dump, lost backup tape, or misconfigured storage volume.

### Scope

Tier 1 freeform-PHI columns only — fields that can carry inline patient identifiers (MRN, DOB, names) injected by free text or query templating:

| Model | Column | Type | Why encrypted |
|---|---|---|---|
| `ResearchRequest` | `initial_request` | Text | Researcher's natural-language prompt — may contain "patient ABC-123…" |
| `RequirementsData` | `inclusion_criteria` | JSON | Structured criteria with `label` fields that may carry patient identifiers |
| `RequirementsData` | `exclusion_criteria` | JSON | Same shape as above |
| `FeasibilityReport` | `phenotype_sql` | Text | Generated SQL — may contain inline PHI from query templating before parameterization |

**Out of scope (deferred to Phase 3b.1):** researcher PII (`User.email`, `*.researcher_email`, `User.full_name`, `User.department`). PII is not ePHI under §164.312, and `User.email` is the unique-indexed login key — encrypting it forces deterministic encryption (weakens crypto) or a hashed-email index column (Sprint 11 multi-tenant index work).

**Out of scope (architectural):** HAPI FHIR's patient resource columns. Patient PHI lives in HAPI's separate Postgres database, encrypted at the HAPI deployment layer (institution's own database security configuration). ResearchFlow's app DB only stores derived metadata, audit records, and the freeform fields above.

**Out of scope by design (Phase 2.2 boundary):** `audit_logs.event_data`. The audit pipeline is metadata-only; encrypting it would cost forensic queryability for zero ePHI gain.

### Algorithm

`StringEncryptedType` / `EncryptedType` from `sqlalchemy-utils` with `FernetEngine` — AES-128-CBC + HMAC-SHA256, encrypt-then-MAC (IND-CCA2). Versioned ciphertext (Fernet's leading version byte) keeps the format stable across library upgrades and is what makes a future MultiFernet-based rotation envelope ergonomic without a schema-aware backfill.

`AesEngine` (the `sqlalchemy-utils` default) was rejected — no version byte means future rotation forces a brittle model-aware re-encrypt-all migration.

### JSON column composition (D4 spike outcome)

`EncryptedType(JSON)` does NOT round-trip cleanly. `sqlalchemy-utils` calls `underlying_type.python_type(decrypted_value)` in `process_result_value`; for JSON that becomes `dict("[{...JSON-string...}]")` — `ValueError` because `dict()` cannot init from a string. The library never invokes `json.loads` on the decrypted side.

**Workaround:** `app/security/encryption.py::_EncryptedJSONImpl` is a `TypeDecorator` that wraps `StringEncryptedType(Text)` with explicit `json.dumps` on bind / `json.loads` on result. Models stay clean (round-trip Python dicts/lists), encryption stays at the column-type layer, no `@validates` boilerplate per model.

JSONB query operators (`->>`, `@>`) are unavailable on encrypted columns — only wholesale ORM round-trip reads. Codebase scan (`grep -rn "->>"`) confirmed none of our encryption-targeted JSON columns use JSONB ops; all JSONB usage targets HAPI's `res_text_vc::jsonb` (a separate database).

### Key sourcing

`get_encryption_key()` in `app/security/encryption_keys.py` is a pluggable callable. The default reads `ENCRYPTION_KEY_PRIMARY` from the environment. Institutions that mandate KMS or Vault swap the function body at deploy time without touching column definitions — column types reference the callable, not the bytes.

### Startup gate

`assert_encryption_key_present_if_production()` runs in `app/main.py` lifespan. In production, it raises `RuntimeError` if `ENCRYPTION_KEY_PRIMARY` is missing or is not a parseable Fernet key. The process exits non-zero; uvicorn surfaces the error; the orchestrator restart loop advertises the misconfiguration loudly. **No silent fallback to plaintext writes.** Same "no kill switches" posture as Phase 2.2 (no `AUDIT_ENABLED`), Phase 2.3 (no `HARDEN_INPUTS`), Phase 3a (`ENVIRONMENT` strict equality).

The Fernet-key format check is the typo-catcher: `ENCRYPTION_KEY_PRIMARY="abc"` fails at boot, not at the first row write hours later. Outside production the gate is a no-op so dev/test/CI environments don't need a key set.

### Migration strategy

**Drop-and-recreate dev/test DBs; no backfill script.** Production has zero pilot rows (no external pilot user yet — the Sprint 6.1 sales-grade-HIPAA-posture decision predates any institution deployment). Test DBs are recreated per session via `init_test_db` autouse fixture. Local dev DBs are an operator concern — `rm dev.db` is a one-line action.

A dual-mode "read-plaintext-or-ciphertext, write-ciphertext" migration was rejected as the same OCR-finding pattern as Phase 2.2's no-`AUDIT_ENABLED` rule: the "graceful migration" code path becomes a permanent backdoor that lets plaintext rows survive forever.

### Key rotation runbook

Rotation is a manual operator procedure. MultiFernet read-fallback for rolling rotation is deferred to Sprint 11+ — Phase 3b's job is "encryption exists at rest," not "rotation is automated." When the first rotation triggers (annually, on suspected key compromise, or on operator transition), follow this runbook:

1. **Generate a new Fernet key:**
   ```
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

2. **Stop the application** to prevent concurrent writes during the cutover. Audit pipeline drain completes its in-flight `audit:processing` items via the standard shutdown path (Phase 2.2).

3. **Re-encrypt rows under the new key.** A one-shot script reads each Tier 1 column with the OLD key (`ENCRYPTION_KEY_PRIMARY` set to the previous value), writes back with the NEW key:
   ```python
   # script/rotate_encryption_key.py — runs offline, single-process
   # 1. Set ENCRYPTION_KEY_PRIMARY=<old key>, query+collect plaintext rows
   # 2. Set ENCRYPTION_KEY_PRIMARY=<new key>, write rows back via ORM
   # 3. Verify a sample of rows decrypts under the new key
   ```
   This script is unwritten — write it the moment the first rotation triggers; treat it as throwaway. Operator runs it on a maintenance window with backups in hand.

4. **Swap the env var to the new key.** Update `ENCRYPTION_KEY_PRIMARY` in the production secret store / KMS / `.env`. Restart the application.

5. **Verify** by exercising a PHI-write/PHI-read flow end-to-end. Confirm the prior key is destroyed (paper key wipe, KMS key disable, env var rotation history pruned per institutional retention policy).

The version byte in Fernet ciphertext means a future MultiFernet implementation can read both old and new keys simultaneously, eliminating the application-stop step. Worth implementing the day a rotating production deployment exists; not worth speculating against today.

### What encryption-at-rest does NOT cover

Column-level encryption protects **data at rest in the database row**. It does NOT protect:

- **Decrypted values in process memory.** Any code holding a session-bound row plus the key can recover plaintext — that is the design.
- **Decrypted values in logs and exception traces.** A `logger.info(f"updated request: {req.initial_request}")` writes plaintext to the log stream. Sentry or Datadog stack traces that include local variables can capture decrypted PHI. Application code must avoid serializing PHI fields into log messages or unstructured error context. Phase 2.3's `phi_safe_validation_handler` already strips `input`/`url`/`ctx` from 422 response bodies; structured logging discipline is a separate, ongoing review.
- **API response bodies.** A researcher reading their own `ResearchRequest` sees the plaintext — that is the application contract, not a leak. Authorization (Phase 1.x JWT) is what ensures the request reaches only its owner; encryption-at-rest is the layer below that.
- **In-transit traffic.** That is Phase 3a (TLS termination + HSTS).
- **Backups taken before encryption rolled out.** Existing dev/test DB files contain plaintext history; the drop-and-recreate migration assumes operators rotate backup volumes accordingly.

§164.312(a)(2)(iv) speaks specifically to storage. The other layers (transport, access logging, audit) are separate Security Rule provisions, addressed elsewhere in this document and in code.

### Test coverage

12 tests across `tests/test_security/`:

- `test_encryption.py` (6): env-var read, dev no-op, prod-missing-key raises `RuntimeError`, prod-malformed-key raises `RuntimeError`, prod-valid-key passes, lifespan wiring (regression guard against the gate being removed from `app/main.py`).
- `test_encryption_models.py` (6): per-column round-trip via ORM AND ciphertext-on-disk via raw `SELECT` bypassing the column type. The ciphertext assertion is the actual encryption-at-rest verification — a future regression that disabled the column type would round-trip fine via ORM but fail the raw-bytes check immediately. JSON columns also assert that `json.dumps(payload)` is absent from stored bytes (catches a hypothetical "store as JSON, encryption disabled silently" bug).

`tests/conftest.py` sets `ENCRYPTION_KEY_PRIMARY` at module-load before model import (autouse-equivalent). Test key is a pinned constant marked `# pragma: allowlist secret`; production keys are generated per-deployment and never checked in.

---

## Future sections

- **Phase 4 — End-to-end HIPAA narrative** (pending)
