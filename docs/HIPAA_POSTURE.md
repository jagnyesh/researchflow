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

Every payload includes `"schema_version": 1`. The drain dispatches on version,
so new fields added in a later release won't break older drain processes that
might still be running during a rolling deploy.

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

## Future sections

- **Phase 3a — TLS** (in progress)
- **Phase 3b — Encryption-at-rest** (pending)
- **Phase 4 — End-to-end HIPAA narrative** (pending)
