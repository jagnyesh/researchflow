# Architecture Decision Record

Append-only. One entry per sprint capturing the decision and the *why* — not the implementation.

---

## Meta: Recurring workflow pattern — re-examining recommendations when premise may have shifted

Across roughly 48 hours of intense sprint work (2026-05-12 through 2026-05-15),
I encountered the same recurring failure mode roughly 10 times. The shape is
identical each time: an AI agent applies a framework correctly given visible
information; the visible information has a load-bearing assumption that hasn't
been pressure-tested; deliberate re-examination surfaces a richer truth than
the original framing could accommodate; the right action involves updating the
rule, not mechanically applying it.

### The cases

1. **Sprint 8.2 Task 1 (cache diagnostic):** Binary YES/NO frame on cache_control
   wiring → third branch (wired correctly, but system prompt below Anthropic
   threshold).

2. **Sprint 6.3 D4 candidate search:** "DuckDB-FHIR candidates exist as described"
   → didn't exist as named; sqlonfhir surfaced through user-initiated re-search.

3. **Sprint 6.3 verdict revision:** Literal pre-commit said NO-GO for sqlonfhir →
   gate premise was broken by view-def bug #41; fixing #41 changed evidence;
   verdict revised via Q1-refinement override.

4. **Sprint 6.3 post-spike /zoom-out:** Routine architectural verification →
   documented architecture (HybridRunner read path) vs runtime reality (agents
   bypass Runner stack). Five architectural gaps surfaced.

5. **Sprint 8.2 Task 2 (prompt architecture):** "Fix prompt architecture so
   caching engages" → langchain-anthropic 1.0.1 silent transmission bug, dropping
   cache_control for 6 months. The wrapper bug was the real issue, not prompt size.

6. **Sprint 8.2 Task 3 (re-measurement):** "Verify optimization works post-Sonnet
   caching" → bulk-up cost offsets cache savings; original 73% projection was
   wrong by 2-3× because cost model assumed 6 LLM calls per request when actual
   is ~2.

7. **Sprint 8.2 Task 2.1 (prompt bulk-up):** "Respect pre-committed 4200-4500
   token band" → 5185 tokens; band was a guideline, not a constraint; deliberate
   proceed-as-is was right rather than mechanical trim-to-fit.

8. **Sprint 8.4 aggregator bug:** Static-analysis hypothesis (parent+child run
   summation double-count) → wire-level empirical check revealed input_tokens
   already includes cache_read; single-leaf double-charging, not summation.

9. **Sprint 8.3 ceiling derivation:** "1.3× tolerance on measured median" →
   mathematically identical to Sprint 8.1's formula but semantically different
   (cost target vs regression alarm). Math hides semantic shift; honest framing
   preserves distinction.

10. **Post-Sprint-8 /zoom-out:** Routine architectural verification → phenotype
    SQL drops gender/age predicates in some cases (Gap #6). A correctness bug
    nobody was asking about, surfaced by structural investigation.

### The pattern

Agents are good at applying rules to visible information. They're less good at
recognizing when the rule's premise has shifted. The defense is asking, before
accepting a recommendation: "what would have to be true for this verdict to be
wrong?" Usually 30-45 minutes of targeted re-examination either confirms the
verdict with stronger evidence or surfaces a third branch the original frame missed.

The trigger I learned to look for: when an agent's recommendation comes back,
read the cons/concerns section twice as carefully as the pros. The load-bearing
hand-waved assumption usually lives in the cons.

### The defense

Pre-commitments defend against bias, not against information. Better information
justifies deliberate override when documented. Precedent: Sprint 6.2 Phase 1.5
Q1 refinement — pre-committed pivot rule was deliberately refined when new
information ("cataloged mechanical bugs are Phase 1.2 scope, not pivot triggers")
surfaced before the gate fired.

### The cost-benefit

~30-45 min per spike or major decision. Across the 10 cases above, ~3 hours of
re-examination work surfaced: 3 silent bugs (Task 1 prompt size, langchain
transmission, aggregator double-charge), 1 architecture drift (Runner stack
bypass), 1 correctness bug (phenotype SQL predicate-dropping), 1 reversed verdict
(Sprint 6.3 GO sqlonfhir not GO Pathling), and multiple framing improvements.
Asymmetric ROI.

### The transferable observation

This pattern likely generalizes beyond this project. Any AI-augmented engineering
work in stacks with multiple interfa[...truncated; finish this section when polishing the note]

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

## Sprint 6.1 — HIPAA security baseline before further feature work

Two paths after 22 sprints: pivot to feedback-loop infrastructure vs finish security hardening. **Chose: finish security hardening (Phases 1.5, 2.2, 2.3, 3a, 3b, 4)** because production deployment is gated on the baseline regardless of feature surface; deferring the baseline is the more expensive option later. Feedback-loop work resumes after the baseline ships.

## Sprint 6.1 — Durable audit pipeline via Redis queue, not BackgroundTasks

Initial design used FastAPI `BackgroundTasks` for audit writes. Codex review flagged: data loss on uvicorn worker crash, deploy, or OOM. **Chose: sync write to Redis `audit:queue` list inside request middleware, asyncio background drain task in `app/main.py` lifespan flushes to `audit_logs` table.** If Redis dies, audit writes fail loudly — correct posture for HIPAA. Reuses existing Redis deployment.

## Sprint 6.1 — Split human/agent auth, not unified JWT

Agent traffic (`mcp`, `a2a` routes) authenticating with the same JWT issuance flow as humans would 401-itself on every internal call. **Chose: separate `verify_service_token()` helper reusing existing `app/a2a/auth.py` JWT issuance for agent routes;** human routes use `Depends(get_current_user)`. Two auth models, one issuer.

## Sprint 6.1 — Documentation reorg: split CLAUDE.md, create CONTEXT/DECISIONS/BACKLOG, install mattpocock/skills

CLAUDE.md grew to 978 lines, claiming Sprint 7 was "ready for production rollout" while Sprint 6.1 was the actual active work. ~16K tokens auto-loaded per session of stale prose. **Chose: slim CLAUDE.md to ~80 lines with `@`-imports; create CONTEXT.md (current state), DECISIONS.md (this file), BACKLOG.md (forward plan); install mattpocock/skills globally for `/caveman` and `/grill-with-docs`.** Hooks added in Phase 2 for HIPAA path enforcement and SQL validation.

## Sprint 6.1 Phase 2.2 — Audit middleware: fail-closed default-deny, at-least-once queue, accept dupes

Three coupled decisions for the Redis-queue audit pipeline. **(1) Failure semantics:** fail-closed on PHI routes (5xx if Redis enqueue fails), fail-open on a small non-PHI allowlist (`/health*`, `/auth/login|refresh|logout`, `/`, `/docs*`, `/openapi.json`). Silently dropping PHI-access events is the OCR-finding pattern; 5xx-ing `/health` breaks liveness checks. **(2) Route classification:** default-deny — every route is treated as PHI unless explicitly allowlisted. New PHI-touching routes get audited by inertia rather than by developer discipline; `/a2a`, `/mcp`, `/users` are correctly captured because agent flows and admin actions touch PHI. Blast radius accepted: a Redis outage 5xxs the entire app minus the allowlist. **(3) Queue pattern:** at-least-once via processing list (`RPUSH audit:queue` on write; `BRPOPLPUSH audit:queue audit:processing` on drain; `LREM audit:processing` after Postgres INSERT; lifespan startup recovery sweep moves orphaned `audit:processing` entries back to `audit:queue`). **AuditLog accepts dupes — dedup at query time; idempotency-key deferred to Phase 2.2.1.** Append-only forensic log; auditors care about presence, not exactly-once.

## Sprint 6.1 Phase 2.3 — Input validation framework: PHI-safe error responses, hardening with HIPAA-scoped priority, hard-break migration

Three coupled decisions for the input validation framework. **(1) Framework + hardening with HIPAA-scoped priority:** ship reusable typed primitives (`ShortText`/`MediumText`/`LongText`/`BoundedDict`/`IRBNumber`) and a `PHIInputModel` base class in `app/schemas/`, then migrate the 12 highest-priority request models (Tier 1 PHI/LLM-touching: `sql_on_fhir`, `research`, `approvals`, `analytics`, `mcp`; Tier 2 credentials: `auth`, `users`, `a2a`). Response models stay loose (we emit, don't receive). `Dict[str, Any]` fields get a `BoundedDict(max_keys=100, max_depth=5)` validator now; explicit shape work deferred to Phase 2.3.1. Permissive `IRBNumber` regex `^IRB[-/_]?[A-Z0-9-]+$` supports IRB-format variation across deployment environments. `SQLQueryRequest.sql` gets length cap only — keyword filtering is HIPAA security theater that an external compliance reviewer spots and loses confidence over; DB-level least-privilege user is the right control layer. **(2) PHI-safe 422 response:** central `RequestValidationError` handler returns `{loc, msg, type}` per error only — `input`, `url`, `ctx` stripped to close the Sentry/Datadog leak vector by construction. No separate `VALIDATION_FAILURE` audit event — Phase 2.2's pre+post pair already records `status_code=422`. **(3) Hard-break migration:** no `HARDEN_INPUTS` env var (same HIPAA-gun trap as Phase 2.2's no-AUDIT_ENABLED rule); breaking constraint changes ship with test-fixture fixes in the same PR. Per-router layout in `app/schemas/` matches existing codebase organizational style; per-domain DDD layout would be the only directory in the codebase using that pattern.

## Sprint 6.1 Phase 3a — TLS enforcement: terminate at LB, exempt /health, HSTS 1-year-no-preload

Three coupled decisions for HTTPS enforcement. **(1) TLS termination at the load balancer / platform**, not at uvicorn directly. App trusts `X-Forwarded-Proto` via uvicorn's `--proxy-headers --forwarded-allow-ips *` flags. Production deployment requirement: container runs on a private network, only reachable via TLS-terminating proxy (k8s ingress, AWS ALB, Render/Fly platform). Cert management is the platform's problem, not ours — production deployments use their own platform ingress and BYO-certs would create deployment friction. **(2) Custom `TLSEnforcementMiddleware` exempts `/health*` only, redirects with 308 (not 301).** Health probes pass through over plain HTTP from internal subnets — without the exemption, LBs see a redirect and silently mark the app unhealthy. 308 preserves method+body so POST stays POST after redirect (301 risks browser downgrade to GET, breaking writes). `/docs`, `/openapi.json`, `/` all redirect to HTTPS — they're public-facing and "your API docs work over plain HTTP" is the kind of small thing that makes an external reviewer wince. Custom middleware (vs Starlette's built-in `HTTPSRedirectMiddleware`) is ~15 lines and lets us inject HSTS in the same place. **(3) HSTS `max-age=31536000; includeSubDomains` (1 year, no preload).** 1 year is Chrome's preload-list minimum and the defensible floor for production; shorter signals lack of commitment, longer is overkill until preload submission. `includeSubDomains` is safe today (no subdomain story) and forecloses future-subdomain-on-HTTP footguns. **`preload` deferred** — submission hardcodes the domain into Chromium/Firefox/Safari source and removal is months-long manual; production domain is unknown so this is a near-permanent commitment to a name we don't have yet. HSTS only emitted on HTTPS responses (RFC 6797 — browsers ignore it over HTTP). Middleware order in `app/main.py`: TLS runs FIRST (registered last), then body_size, then audit — HTTP redirects don't pollute the audit queue. Gated by `ENVIRONMENT=production` strict equality (typos fail-safe to dev); `FORWARDED_ALLOW_IPS=*` default with startup warning when production+`*` (container must not be internet-reachable directly).

## Sprint 6.2 Phase 1.5 — PROCEED to Phase 2 (gate cleared at 7/7, anchors all PASS)

The pre-committed pivot rule from the lambda-finish design doc said: **"≥6/7 PASS, ALL 3 anchors PASS → PROCEED to Phase 2; <6/7 OR any anchor FAIL → pivot to Pathling-only Approach B (3 weeks)."** Issue #14 milestone applies the rule against the harness output after issues #10-#13 + #16.

**Gate result, 2026-05-09:** **PROCEED.** Every criterion exceeds threshold:

| Criterion | Required | Actual | Verified by |
|---|---|---|---|
| View-level PASS rate | ≥6/7 | **7/7** | harness 48/48 |
| Anchor PASS (mandatory) | 3/3 | **3/3** | sample_values for patient_simple, patient_demographics, condition_simple |
| Bug 9 production callsite verified | yes | 7/7 | mvr_get_schema test parametrized over all view defs |
| UNIQUE INDEX for CONCURRENTLY refresh | per MV | 7/7 | test_unique_index_on_id |

**The Q1 refinement was load-bearing.** The original pivot rule would have fired during issue #11 implementation when uncataloged Bugs 10/11/12 surfaced (and again in #12 when Bugs 13/14/15 surfaced). The Q1 refinement (cataloged-bug fixes are Phase 1.2 scope, NOT pivot triggers) let the work proceed: each newly-discovered bug got added to the design doc bugs table and fixed in scope. **Catalog grew from planned 9 to actual 15 bugs** — every one mechanical or scoped-structural, none "transpiler can't do FHIRPath feature X." Pre-committing the refinement before implementation prevented mid-sprint pressure from forcing a Pathling rewrite that wasn't actually warranted.

**No Pathling fallback evaluation needed.** The pre-committed 5/7 PASS scenario (which would have triggered Pathling-fallback for stragglers) never materialized — every view def transpiled with the custom transpiler after bug fixes.

**Notable narrative side-effects:**
- The `/qa` mutation testing pattern (Mutation 1 for Bug 1, Mutation 2 for Bug 9) proved the harness's PASS/FAIL signal was sensitive enough BEFORE any bug fix was attempted. When the actual fixes shipped in #10 and #13, both flipped exactly as the mutations predicted — zero surprises.
- The harness caught its own author's bugs DURING TDD: cycle 2 of issue #9 (information_schema vs pg_attribute), cycle 6 of issue #12 (Bug 13 v1 over-aggressive scalar-leaf detection that regressed patient_demographics). Both fixed before any production code trusted false signals.
- The grilling pattern compounded: each `/tdd` cycle exposed at least one uncataloged bug that planning didn't predict. Issues #11, #12, #16 each grew their scope by 1-3 bugs as new manifestations surfaced. Per-issue scope expansion is recorded in commit messages so future-me can trace why each cluster shipped together.

**Phase 2 unblocked.** Phase 1.6 (issue #15 — switch streamlit demo to MV path) now safe to execute. Phase 2.0 (poll-based speed layer + on-demand refresh endpoint) and Phase 2.1 (HybridRunner merge + dedup) follow per design doc.

---

## Sprint 6.2 Phase 2.5 (out-of-band) — Materialized-views router hardening: admin gate every mutating endpoint + view_name allowlist before any SQL is built

`/cso` review of PR #24 surfaced a CRITICAL pre-existing finding: `DELETE /analytics/materialized-views/{view_name}` f-string-interpolated the path param into a `DROP MATERIALIZED VIEW IF EXISTS sqlonfhir.{view_name} CASCADE` statement with no admin gate, only Sprint 6.1's audit-middleware default-deny (which any researcher token passes). The mock researcher account (`researcher@example.com / password123`, loaded at import time in every environment) made the SQLi path one POST + one DELETE away. **Decision: harden in-band on PR #24 rather than ship and follow-up.** Three coupled choices:

**(1) Per-endpoint `Depends(require_role("admin"))`, not router-level dependency.** The materialized-views router has 8 endpoints. 5 are mutating (1 was already gated by `019666d`/issue #18; 4 weren't). 3 are read-only (list, status, health) and should stay reader-accessible. Per-endpoint dependencies make the gate VISIBLE in each function signature — a future maintainer sees `_admin=Depends(require_role("admin"))` and can't miss it. Router-level with selective opt-out (set the dep on the router, override on GETs) was rejected: it's the same "looks-secure" anti-pattern that bit us originally — the pattern signals "everything is gated" while one carve-out negates it.

**(2) Allowlist via `ViewDefinitionManager.list()` filename-stems + identifier regex `^[a-z][a-z0-9_]*$`, both returning 404.** Filename-stem allowlist gives membership in O(1) against a server-side list. The regex is belt-and-suspenders for the future case where someone drops a malformed JSON file under `app/sql_on_fhir/view_definitions/` — even then, the regex refuses to interpolate it. Both branches return 404 (not 422) so callers cannot distinguish "malformed name" from "unknown view" — same response surface as `GET /{view_name}/status` when the view doesn't exist. Hardening the SELECT/COUNT paths in `materialized_view_runner._build_query` (lines 321, 349) is out of scope: `view_name` there arrives via `view_def["name"]` from server-controlled JSON files, not user input. Already safe.

**(3) Test mock pattern: override `get_current_active_user`, NOT `require_role("admin")`.** First test attempt overrode `app.dependency_overrides[require_role("admin")]` and the override didn't fire. Root cause: `require_role` is a factory that returns a NEW `role_checker` function instance each call — the route captured a different instance than the test override creates. Override `get_current_active_user` (the inner dependency that EVERY `role_checker` delegates to) instead. One override covers all 5 admin-gated routes. Documented in `tests/test_materialized_views_auth.py` comment block to save the next dev the same hour. Tests prove injection payloads return 404 AND `db_client.execute_query` is `assert_not_called` — the SQL layer is provably never reached, not just "passes a status check."

Identifier-quoting via `psycopg2.sql.Identifier` rejected: post-allowlist, `view_name` is known-safe (letter-prefixed lowercase ASCII identifier from a JSON file stem). Adding a new dependency just for `sql.Identifier` is marginal-gain.

---

## Sprint 6.1 Phase 3b — Encryption-at-rest: Tier 1 freeform-PHI columns only, FernetEngine, pluggable key callable, drop-and-recreate

Five coupled decisions for column-level encryption-at-rest. **(1) Scope is freeform-PHI columns only — `ResearchRequest.initial_request` (Text), `RequirementsData.inclusion_criteria` (JSON), `RequirementsData.exclusion_criteria` (JSON), `FeasibilityReport.phenotype_sql` (Text).** [Initial design grilling listed `ResearchRequest.structured_requirements` (JSON) as a fifth column, but a codebase scan during /tdd revealed it does not exist as a model column — it's a runtime dict key in agent context only; structured criteria persist in `RequirementsData.inclusion_criteria`/`exclusion_criteria`. Stale-doc flag caught and corrected before #9 implementation.] Researcher PII (`User.email`, `*.researcher_email`, `User.full_name`, `User.department`) is **deferred to Phase 3b.1** — it's PII not ePHI under §164.312, and `User.email` is the unique-indexed login key so encrypting it forces deterministic encryption (weakens crypto) or a separate hashed-email index column (Sprint 11 multi-tenant index work). **The previously-claimed scope of "User.SSN/MRN/DOB/etc." in old design notes was wrong — this app's `User` model is researcher accounts, not patient records; patient PHI lives in HAPI Postgres, separate DB.** **(2) Pluggable key callable, env-var default, fail-closed startup gate.** `app/security/encryption_keys.py` exports `get_encryption_key()` that reads `ENCRYPTION_KEY_PRIMARY` and a sibling `assert_encryption_key_present_if_production()` that raises `RuntimeError` in lifespan startup if the var is missing **or** the value isn't a parseable Fernet key. Process exits non-zero, never serves PHI plaintext-write traffic. The callable indirection is ~5 lines and lets deployment environments that mandate KMS/Vault swap the function body at deploy time without touching column definitions. AWS KMS / Vault hardcoded from day one is rejected — narrows deployment options (some environments require Azure-only, some require on-prem Vault). **(3) `FernetEngine` (AES-128-CBC + HMAC-SHA256, versioned ciphertext) + documented rotation runbook, no MultiFernet code.** Rotation procedure ("dump → re-encrypt with new key → swap env var → restart") lands in `docs/HIPAA_POSTURE.md` Phase 3b section. MultiFernet read-fallback for rolling rotation is deferred to Sprint 11+ — Phase 3b's job is "encryption exists at rest," not "rotation is automated." `AesEngine` (default) rejected: no version byte means future rotation forces a brittle model-aware re-encrypt-all migration. `AesGcmEngine` rejected this sprint: newer in `sqlalchemy-utils` (0.41+), weaker rotation story; revisit if a deployment environment explicitly requires AES-256-GCM. **(4) Column wrappers: `StringEncryptedType(Text, …, FernetEngine)` for Text columns, `EncryptedType(JSON, …, FernetEngine)` for JSON columns; drop-and-recreate dev/test DBs with no backfill.** Underlying storage becomes `BYTEA` — we lose Postgres JSONB query operators (`->>`, `@>`), which is fine because `grep -rn "->>"` on the codebase shows we never query *into* these JSON blobs (wholesale ORM round-trip only). Half-day spike during the tracer-bullet issue verifies asyncpg + SQLite round-trip; fallback path is `StringEncryptedType(Text)` + `@validates(json.dumps/loads)` if asyncpg fights the native `JSON+EncryptedType` composition. No backfill migration — production has zero rows; dual-mode "read-plaintext-or-ciphertext" is rejected as the same OCR-finding pattern as Phase 2.2's no-AUDIT_ENABLED rule (the "graceful migration" code becomes a permanent backdoor that lets plaintext rows survive forever). **(5) Tests use a fixed dev-only Fernet key in `tests/conftest.py` autouse fixture; Phase 4 HIPAA narrative gets an explicit carve-out for what encryption-at-rest does NOT cover.** Test key is a constant `_TEST_FERNET_KEY = b"…"` set on `os.environ` *before* model import — deterministic encrypt/decrypt across the test run, zero CI flakiness, hits the production code path (no mocking of `get_encryption_key`). The carve-out: column-encryption-at-rest does not protect decrypted values in process memory, in logger calls (`logger.info(f"req={req.initial_request}")`), or in API response bodies that the researcher is allowed to see. §164.312(a)(2)(iv) speaks to storage; logs/memory are out-of-band controls. Doc honesty over external-reviewer-wince.

---

## Workflow — PR cadence: one cohesive squash PR per sprint, opened only when the sprint's gate has fired

One squash PR per sprint, opened only when the sprint's pre-committed gate has fired. No mid-sprint PRs — even when a sub-phase looks clean enough to ship in isolation. Rationale: this is a solo portfolio project; the audience is async readers reviewing the repo history later (recruiters, collaborators, future-me), not synchronous reviewers approving incremental diffs. A single PR per sprint with a coherent narrative — design doc → grilling → /tdd cycles → /cso/codex review → /qa → squash → merge — reads cleanly six months from now. A churn of 5–10 mid-sprint PRs forces the reader to reconstruct the arc from PR metadata that nobody wrote with that audience in mind. The downside (one big diff, less bisect granularity) is bounded by gstack discipline: each /tdd cycle is its own commit on the feature branch, the squash preserves the *story* in the PR body, and the in-branch commit log is still bisectable for post-merge regression hunts.

Supersedes: the implicit PR-A / PR-B split from `/plan-eng-review` CQ2 (issue #25) — under this rule, both stop being separate PRs and become sub-phases of the same sprint PR. The feature branch for issue #25 stays open until the rest of the sprint's gate fires.

---

## Sprint 8.1 — LangSmith is source-of-truth for LLM cost; explicit portal tags promote domain language into trace data

Two coupled decisions for the cost-verification sprint. **(1) Read cost/latency telemetry directly from LangSmith.** The Sprint 8 archive doc deferred a `QueryTelemetry` Postgres table as "Optimization 10." Sprint 8.1 re-grilled the question and rejected the table. `@traceable` decorators already ship token counts (`input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`) for all 6 production agents and `MultiLLMClient.complete` — the data exists upstream. Building a parallel write path means: (a) duplicate code on the LLM call hot path; (b) two sources of truth that can silently drift; (c) ownership of a schema we'd otherwise let LangSmith own. Trade accepted: dashboard reads depend on LangSmith API quota and uptime. We already depend on LangSmith for tracing — making it explicit for reads doesn't expand the blast radius. Offline-dev dashboards display "no recent data" instead of stale local rows, which is the honest UX. Hybrid (`prompt_cost_daily` aggregation table populated by a periodic LangSmith pull) was rejected for this sprint: cron-based aggregation is the right shape if and only if (a) the dashboard becomes hot enough that LangSmith API rate-limits bite, or (b) we want to outlive the LangSmith subscription. Neither is true today; defer to a future sprint with a real trigger.

**(2) Differentiate portal traffic via explicit `portal:formal` / `portal:exploratory` tags on `@traceable` decorators.** The codebase already tags by agent name (`requirements-agent`, `phenotype-agent`, etc. for formal; `feasibility-service`, `hybrid-runner` for exploratory) but has no portal-level tag. Three options considered: (a) tag-based inference at query time (fragile rule "if any tag matches `*-agent` then formal"); (b) separate LangSmith projects per portal (clean separation but two-project ops overhead); (c) add explicit `portal:formal` / `portal:exploratory` tags to the 8 `@traceable` decorators (6 formal agents + `query_interpreter` + `feasibility_service`). **Chose (c).** ~8 single-line additions, promotes the documented "Formal Portal" / "Exploratory Portal" domain vocabulary into trace data, makes `cost_telemetry_service.py` queries trivially `has(tags, "portal:formal")` rather than encoding an inference rule. Future-me reads the tag and knows immediately what portal a run belongs to.

**Aggregation rules** (independent of the source-of-truth choice): formal portal groups runs by LangSmith `thread_id` (LangGraph checkpointer sets it per workflow invocation; one thread = one user submission). Exploratory portal aggregates per root trace (one root = one query; QueryInterpreter is the typical entry point). `cost_telemetry_service.get_formal_portal_cost_p50(n=30)` computes sum-tokens-per-thread × per-model-price, sorted by start time desc, median of last 30 threads.

**Sprint 8.1 gate (pre-committed):** median cost-per-request ≤ 1.3× projected, rolling 30 requests, both portals clear independently. Failure mode: sprint closes either way; if red, BACKLOG gets a Sprint 8.2 entry for the gap-close work.

---

## Sprint 6.3 — DuckDB-FHIR spike verdict: GO Pathling (with sqlonfhir captured for Sprint 6.5+ recheck)

Spike executed 2026-05-14, well within the 2-day hard cap. Three FHIRPath constructs empirically evaluated against samples + synthetic data. Pre-committed numeric thresholds applied strictly. The override mechanism (`pre-commit defends against bias, not against information`) was deliberately considered for sqlonfhir and did NOT fire — the row-count match against HAPI oracle was 2/3, not the 3/3 the override required.

### Measured outcomes vs pre-committed thresholds

**Named Primary `sql-on-fhir-v2` Python ref impl:** does not exist as a Python package. The HL7 ref impl is JavaScript (`sof-js`). Primary tier eliminated by non-existence.

**Named Secondary "DuckDB community FHIR extension":** does not exist (0 GitHub search hits). Secondary tier eliminated by non-existence. DuckDB-FHIR candidate set is empty; methodology triggers Pathling evaluation.

**Mid-spike discovery — `sqlonfhir` (one word, missed in D4):** SAS Healthcare's Python implementation. Apache 2.0. Pure-Python (`fhirpathpy~=2.1.0`). User-directed deep evaluation against the 4 thresholds within a 45-min hard cap.

| | sqlonfhir | Pathling |
|---|---|---|
| C1 — construct coverage (3/3 expected) | 2/3 by row-count match; **3/3 by construct-correctness** (synthetic test confirms forEach cardinality math) | not empirically tested — Spark init failed on Mac under PySpark 4.0; ≥90% prior that procedure_history is shared 0-row |
| C2 — integration shape | ✅ Pure Python, no JVM, no Spark | ⚠️ "Native Python lib" tier per pre-commit but real cost: Java 17 hard requirement, PySpark 4.0 with known Mac/Spark init issues, ~430MB deployment surface |
| C3 — maturity (pass requires ALL 4) | ❌ FAIL 2/4: 2025-09-29 release (7.5 months), 7 GitHub stars | ✅ PASS 3/4 measured (release 2026-04-23, commits today, 126 stars); maintainer responsiveness deferred |
| C4 — performance | not measured | not measured |

**Verdict trigger:** sqlonfhir fails C3 strict pre-commit (2/4 thresholds). procedure_history row-count fails the 3/3 override gate (HAPI oracle = 66,448; sqlonfhir against Synthea = 0). Override does NOT fire. Per user-pre-committed framework ("If 1 or 2 view-defs work but procedure_history doesn't, verdict stays GO Pathling but the recheck has measured data"): **GO Pathling.**

### Why the override did not fire — discipline note

The override evaluation was real, not pro-forma. sqlonfhir has unambiguous technical merit: it handles all 3 target FHIRPath constructs correctly (verified empirically), has the cleanest possible Python integration shape, vendor backing, and active commits. The Sprint 6.2 Phase 1.5 Q1 refinement pattern (cataloged-bug fixes are scope, not pivot triggers) was the precedent for considering override.

What the override DID NOT do: change the C3 reading. The "≥ 50 stars" + "≤ 6mo release" thresholds proxy for community stress-testing maturity. **Construct correctness is necessary but not sufficient for production adoption.** A library can be technically correct AND insufficiently stress-tested. The pre-commit catches that.

What the override could have done: fire if all 3 view-defs matched (3/3 → "demonstrated construct coverage IS the maturity proxy I needed"). Got 2/3 plus a shared-issue interpretation for procedure_history. The strict gate held.

### Pathling's C2 surprises (warrant Sprint 6.4 mitigation)

Pathling 9.6.0 pulls in PySpark 4.0.2 which requires Java 17 specifically. Spark init failed on Mac (M-series Apple Silicon, OpenJDK 17.0.19) with `BlockManagerId.executorId()` NPE. Pathling cannot be downgraded to PySpark 3.x (imports `pyspark.sql.classic` which is 4.0-only namespace). Sprint 6.4 implementation must:
1. Pin Java 17 in deployment env (not Java 11 currently in docker-compose stack)
2. Resolve PySpark 4.0 Spark-init issue on whatever platform Sprint 6.4 deploys (likely needs `SPARK_LOCAL_IP` or hostname-resolution config)
3. Accept the ~430MB deployment surface increase from PySpark wheel + Pathling library-runtime JARs

The pre-committed C2 reading still says PASS ("Subprocess / CLI invocation acceptable"). The cost is real and goes into the Sprint 6.4 risk register.

### Side-finding to file separately

**`procedure_history` view-def is structurally broken** regardless of engine. Three `forEach` blocks over `performer` / `reasonCode` / `bodySite` arrays empty in 100% of Synthea Procedures. Per FHIRPath spec, `forEach` over empty = 0 rows. Fix: change `"forEach"` → `"forEachOrNull"` in the 3 nested select blocks. Not in scope for the engine spike; filed as separate issue.

### sqlonfhir captured for Sprint 6.5+ recheck (deferred follow-on)

If by 2026-11-14 sqlonfhir has shipped v0.1.0+ with a real release cadence and >50 stars, Sprint 6.5+ should re-evaluate. The measured evidence base from this spike (FHIRPath constructs work, pure-Python integration) gives a strong starting point.

### Time-box honored

Total spike effort: ~30 min Day 1. Well within 2-day hard cap. Pathling-debugging time-cap consideration was correctly applied: ~15 min sunk on Spark init before accepting the data gap and proceeding to verdict.

### Downstream issues filed

- Sprint 6.4 implementation: Pathling integration + Java 17 + PySpark 4.0 ops setup + port 3 zero-row MVs + plumb dispatch in MaterializedViewRunner
- Side-finding: procedure_history view-def needs `forEachOrNull` (separate from engine choice)
- Sprint 6.5+ recheck candidate: re-evaluate sqlonfhir at 2026-11-14 or upon v0.1.0+ release

---

## Sprint 6.3 — VERDICT REVISION 2026-05-14: GO sqlonfhir (Q1-refinement applied)

Same-day revision. Original verdict "GO Pathling" was reached by strict enforcement of the 3/3 row-count gate. User-directed re-examination surfaced that the gate's premise was broken: `procedure_history`'s 0-row state under the original view-def is an engine-independent bug (see #41), not a sqlonfhir-specific failure. Pathling produces the same 0 against the same view-def + Synthea data.

Sprint 6.2 Phase 1.5 Q1 refinement is the precedent: pre-commits are updated, not blindly enforced, when new information reveals the rule was based on a wrong premise. Q1 there was "cataloged-bug fixes are Phase 1.2 scope, NOT pivot triggers." Q1 here is **"the gate is evaluated against the fixed view-def, not the broken one."**

### Re-test against patched view-def (#41 `forEach` → `forEachOrNull`)

```
30 Synthea Procedures (all 0×0×0)  →  30 rows  ✓ (30/30 distinct Procedure IDs)
Synth 2×1×1                         →  2 rows  ✓
Synth 1×0×0                         →  1 row   ✓ (outer-join surfaces row with NULL columns)
Synth 0×0×0 (Synthea shape)         →  1 row   ✓ (outer-join surfaces row with NULL columns)
```

**3/3 view-defs now pass Criterion 1:**
- observation_labs 19/19 ✓
- condition_diagnoses 50/50 ✓
- procedure_history 30/30 distinct Procedure IDs ✓ (under `forEachOrNull` semantics)

Projecting to the full HAPI corpus: 66,448 Procedures → 66,448 distinct IDs in the MV, matching the HAPI REST oracle. (Full-corpus exact-match validation deferred to Sprint 6.4 implementation.)

### Override of C3 maturity proxies — now fires

User's explicit rationale: *"The override rationale isn't 'we found a shinier object'; it's 'the rule's premise was wrong, the rule is updated with corrected information, the override against C3 proxies is justified by direct evidence (vendor backing, active commits, Apache 2.0, verified coverage) being stronger than indirect proxies (stars, release age).'"*

Direct evidence accumulated:
- **Vendor backing:** SAS Institute (legitimate analytics vendor, $3B+ annual revenue, ~14k employees)
- **Active commits:** `sassoftware/sqlonfhir` pushed 2026-05-07 (1 week ago, source `__version__ = "0.1.1-alpha"` ahead of PyPI's 0.0.2)
- **License:** Apache 2.0 (compatible)
- **Construct coverage:** 3/3 view-defs empirically verified — `category.coding.where(system=X and code=Y).exists()` + `status in (...)` + `clinicalStatus.coding.code.where($this in (...)).exists()` + `forEachOrNull` (outer-join cardinality, including the all-empty case)

Indirect proxies (the C3 thresholds):
- Stars (7) and release age (7.5 months since last PyPI) proxy for *community stress-testing* and *release cadence health*. They are not zero-information — but they are weaker evidence than direct empirical confirmation of construct coverage against the actual view-defs Sprint 6.4 needs to ship.

### Comparison with Pathling — also relevant to the revision

The original verdict assumed Pathling was the safe fallback. Pathling was never validated against the same gate sqlonfhir was held to:
- ❌ Pathling C1 (construct coverage): **never tested** — Spark init failed on dev machine
- ⚠️ Pathling C2 (integration shape): nominally PASS, but real cost is Java 17 hard requirement + PySpark 4.0 + Mac Spark init NPE + ~430MB deployment surface
- ✅ Pathling C3 (maturity proxies): PASS 3/4 measured

Pathling has *better proxies* but *no direct construct-coverage evidence*. sqlonfhir has *worse proxies* but *direct construct-coverage evidence on the exact view-defs this project ships*. The override correctly weights direct evidence over proxy evidence.

### Revised verdict: GO sqlonfhir

- Sprint 6.4 implementation target: **sqlonfhir + dispatch plumbing** (issue #40 retargets)
- Pathling deferred as fallback if sqlonfhir proves unresponsive during Sprint 6.4 (the override is reversible: empirical evidence about library responsiveness during real implementation work would justify reversal)
- Side-finding #41 (procedure_history `forEachOrNull`) lands as part of Sprint 6.3 spike PR — it's load-bearing for the verdict
- Sprint 6.5+ recheck closed (sqlonfhir is the chosen engine; recheck N/A)
- Pathling 6-month recheck added: if sqlonfhir proves problematic mid-Sprint 6.4, Pathling is the documented fallback. Java 17 ops setup work captured in Sprint 6.4 issue body as deferred-if-needed scope.

### Discipline note

This revision is not "I changed my mind because I wanted to." The strict-reading verdict was reached procedurally and the override was deliberately rejected. The user re-examined the verdict's reasoning, identified that the gate's premise was broken (the 3/3 was unreachable in its literal form because of a view-def bug, not engine choice), and directed a re-test with the corrected premise. That re-test produced new information (3/3 PASS). The Q1 refinement pattern applies: the rule is updated with the corrected premise, the override fires.

Sprint 6.2 Phase 1.5 used the Q1 refinement to AVOID a Pathling pivot when uncataloged bugs surfaced. Sprint 6.3 uses the same pattern to PIVOT TO sqlonfhir when the gate's premise was revealed broken. The pattern works in both directions — that's what makes it discipline, not bias.

---

## Sprint 8.2 — The 6-month silent prompt-caching bug: langchain-anthropic transmission gap

### Setup

Sprint 8 (2025, archive doc `docs/sprints/archive/SPRINT_08_PROMPT_OPTIMIZATION.md`) projected a 73% cost reduction primarily from prompt caching. The optimization was implemented in `app/utils/llm_client.py:354-370`:

```python
messages.append(
    SystemMessage(
        content=system,
        additional_kwargs={"cache_control": {"type": "ephemeral"}}
    )
)
```

Sprint 8.1 (2026-05-12) verified the claim against production traffic: median cost-per-request was $0.009026 (formal) vs $0.003 projected (3.01× the band ceiling), `cache_hit_rate = 0.0%` on every observed run. The verdict was RED.

### What Sprint 8.2 found

Three concurrent failure modes, not one:

**(1) Wrong message shape for the transmission layer.** `langchain-anthropic 1.0.1`'s `_format_messages` (`chat_models.py:352-366`) translates a `SystemMessage` to Anthropic's API kwargs by branching on `message.content` type:
- If `content` is a **list of content blocks** (e.g., `[{"type": "text", "text": "...", "cache_control": {...}}]`), the blocks are passed through to Anthropic's API as `system=[...]`, preserving `cache_control`.
- If `content` is a **plain string**, the branch sends `system="..."` to Anthropic. **`additional_kwargs.cache_control` is silently discarded.**

Sprint 8 shipped the string-content + additional_kwargs form. cache_control never reached Anthropic for ~6 months.

**(2) System prompts below Anthropic's minimum cacheable token threshold.** Even if `cache_control` had reached the wire, the system message was `"You are a helpful clinical research data specialist."` (~12 tokens). Anthropic Sonnet 4 silently ignores `cache_control` on prompts below ~1024 tokens; Haiku 4.5 below ~2048 tokens (empirically appears to be even higher). With 12 tokens, no caching would have happened regardless.

**(3) Existing unit tests asserted against the input shape, not the wire shape.** `TestPromptCachingEnabled` checked `assert "cache_control" in system_msg.additional_kwargs` — which langchain-anthropic *receives* but then *discards*. The tests passed for 6 months while the wire-level behavior was broken. Sprint 8.2's diagnostic (Task 1) inspected the LangSmith trace inputs (the same input shape) and concluded "wiring correct" — same mistake.

### Why this matters beyond the immediate fix

This is the failure mode the Sprint 6.2 pivot rule and Sprint 8.1 pre-committed gate were designed to catch. The system *worked* end-to-end — requests succeeded, cost telemetry recorded numbers, dashboards rendered — but the load-bearing optimization was silently disabled by a third-party wrapper translation. No exception, no warning, no test failure. The only signal was `cache_hit_rate = 0.0%` against the expected positive number, and that signal took 6 months to investigate because the verdict's wrong-projection assumption made the cost numbers look explainable.

### Fixes shipped (PR #43)

**(1) Content-block form** — `llm_client.py` always emits SystemMessage with content as a list of content blocks:

```python
SystemMessage(content=[
    {"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}
])
```

This is the only form `langchain-anthropic` actually transmits to Anthropic's API.

**(2) Substantive system prompts above threshold** — module-level `_REQUIREMENTS_SYSTEM_PROMPT` (~3000 tiktoken tokens, Sonnet) and `_MEDICAL_CONCEPTS_SYSTEM_PROMPT` (~2500 tiktoken tokens, Haiku-target). Byte-stable across calls (no f-string interpolation) — required for cache key stability. User messages become minimal (dynamic content only).

**(3) Wire-level integration test** — `TestPromptCachingWireLevel.test_cache_control_reaches_anthropic_wire_for_custom_system_prompt` mocks `anthropic.resources.messages.AsyncMessages.create` and asserts `cache_control` arrives in the outbound `system` kwarg as a content-block array. Verified to catch the buggy shape (test fails when reverted) AND pass with the fix (test passes when restored). Future maintainers cannot revert the fix without breaking this test.

**(4) Unit test updates** — `TestPromptCachingEnabled` updated to assert content-block form, not `additional_kwargs`. Brings the input-level tests in alignment with the wire-level reality.

### Empirical verification (LangSmith, 2026-05-14)

After the fix, 7 fresh formal-portal requests through `scripts/drive_qa_traffic.py`. Every Sonnet 4.6 `extract_requirements` call now shows `cache_create=3087` on first call (in the 5-min TTL window) and `cache_read=3087` on subsequent calls. Haiku 4.5 `extract_medical_concepts` still shows `cache_create=0` — its threshold appears higher than the 2500-token prompt currently provides; filed as Sprint 8.2 follow-up Task 2.1.

### Implications for the Sprint 8 archive doc projection

The Sprint 8 archive doc's 73% cost-reduction projection assumed cache_control was working as wired. Per the fixes above:
- It wasn't working (root cause #1).
- The system prompts wouldn't have cached anyway (root cause #2).
- The tests wouldn't have caught it (root cause #3).

With root cause #1 + #2 fixed (Sonnet now caches; Haiku pending), the actual achievable reduction is **30-50% per request, not 73%**. Archive doc updated 2026-05-14 with a "Verdict revision" section that names this honestly: the optimization shipped, the dependency stack silently disabled it, the silent disablement is now found and fixed.

### Why the test was the most important addition

The 6-month silent bug existed BECAUSE the existing tests asserted at the wrong layer. Input-shape assertions (LangChain message construction) passed while wire-shape behavior (what Anthropic actually receives) was broken. Adding the wire-level test brings the test surface in alignment with what we actually need to verify — and prevents the same class of regression from running 6 months again on a future LangChain version bump.

This is the structural lesson: **for fixes whose correctness depends on third-party library behavior, the test must assert the third-party API contract, not the wrapper API contract.** The wrapper is the system under test only for unit tests; the wire is the system under test for integration tests. We had the unit tests; we lacked the integration tests.

---

## Sprint 8.2 CLOSE — diagnostic chain completed; corrected baseline established

Sprint 8.2 closes 2026-05-14. The original framing ("investigate cache_hit_rate=0% root cause") suggested a single-root-cause investigation. The actual sprint resolved a chain of THREE concurrent failure modes, plus surfaced a CRITICAL aggregator bug that invalidates Sprint 8.1's reported baseline. **The sprint succeeded — it produced a corrected understanding of the cost system, not a target-hit verdict.**

### The three failure modes Sprint 8.2 diagnosed and fixed

**(1) Task 1 — threshold miss.** Sprint 8 wired `cache_control` on a 12-token default system message (`"You are a helpful clinical research data specialist."`). Anthropic Sonnet 4.6 requires ≥1024 tokens to cache; Haiku 4.5 requires ≥4096 tokens. The prompt was 0.3% of Sonnet's threshold; Anthropic silently ignores cache_control on undersized prompts. Cache was never going to fire regardless of wiring.

**(2) Task 2 — `langchain-anthropic` wrapper transmission bug.** Even after diagnosing (1), Task 2's deeper inspection revealed `langchain-anthropic 1.0.1`'s `_format_messages` (`chat_models.py:352-366`) **silently discards `additional_kwargs.cache_control`** when SystemMessage content is a plain string. Only the content-block-array form (`[{"type": "text", "text": "...", "cache_control": {...}}]`) preserves transmission to Anthropic. Sprint 8 shipped the string + additional_kwargs form. **cache_control never reached Anthropic for ~6 months** — silently dropped by a third-party wrapper, with no exception, warning, or test failure. PR #45 (merged 2026-05-14 as `6bf1e86`) shipped the content-block form fix + module-level system prompts (~3000 tokens Sonnet, ~5185 tokens Haiku) + a wire-level integration test that asserts `cache_control` arrives in the outbound `anthropic.AsyncMessages.create` payload as a content-block array.

**(3) Task 3 — projection model error in Sprint 8 baseline.** The Sprint 8 archive doc projected 73% cost reduction assuming 6 LLM calls per formal-portal request × $0.0005 projected per-call. Empirical sampling of 10 production traces (2026-05-12 Sprint 8.1 traffic) found **only 2 LLM calls per request** (only `requirements_agent` makes LLM calls; phenotype/extraction/qa/delivery agents execute as chain spans with no LLM children). Per-call cost is ~$0.0045 (9× the projection). Sprint 8's projection was wrong on BOTH dimensions: 3× call-count overestimate AND 9× per-call cost underestimate. The original $0.003/request projection is structurally unrecoverable at current model pricing/architecture; a realistic floor with both prompts caching at steady state is ~$0.0073/request.

### Task 2.1 measured outcome (2026-05-14)

Bulked `_MEDICAL_CONCEPTS_SYSTEM_PROMPT` from ~2474 tiktoken tokens to ~5185 (5850 Anthropic-counted) to clear Haiku 4.5's documented 4096-token threshold. Empirical verification across 30 fresh formal-portal traces:

| Metric | Value |
|---|---:|
| Sonnet cache state | 1 create / 29 read / 0 miss (100% hit after warmup) |
| Haiku cache state | 0 create / 30 read / 0 miss (warm from Gate 0.5 single-call test) |
| **Per-thread cost — median (manual)** | **$0.007754** |
| Per-thread cost — mean | $0.007985 |
| Per-thread cost — min | $0.006829 |
| Per-thread cost — max | $0.018356 (outlier — cache_create thread + larger input) |
| **Δ vs Sprint 8.1 $0.009026 baseline** | **−14.1%** |

The 14.1% reduction is concrete engineering value delivered against the corrected baseline. It is NOT the projected 73% reduction — that target was structurally unreachable per Task 3's projection-error diagnosis.

### CRITICAL finding: aggregator over-counts by ~2.95×

Manual per-thread cost (walking trace tree, summing `usage_metadata` from LLM child runs only): **$0.007754**.
`CostTelemetryService.get_formal_portal_cost_p50(n=30)` reports: **$0.022865**.
Ratio: **2.95× inflation**.

This is not a Sprint 8.2 deviation from baseline; it is evidence that the cost-telemetry aggregator in `app/services/cost_telemetry_service.py` is producing incorrect numbers — possibly by summing parent-trace `usage_metadata` (which LangSmith aggregates UP from LLM children) alongside the individual LLM-child counts, effectively double-counting. The Sprint 8.1 RED baseline of $0.009026 (which informed the Sprint 8.2 investigation) was produced by the same aggregator and is therefore likely inflated too. **Sprint 8.4 is filed as BLOCKING for any future ceiling-re-derivation work** because the aggregator's correctness is a prerequisite for any cost-baseline measurement to be trusted.

### Discipline notes — what made this sprint work

**(a) Diagnostic-first scoping.** Task 1 was explicitly framed as a binary YES/NO diagnostic (~30 min) before any code changes. The actual diagnosis required investigation BEYOND the YES/NO binary frame — a third branch ("prompt below threshold, AND wrapper drops cache_control, AND test layer asserted wrong API surface"). The diagnostic-first scope prevented committing to a Task 2 fix before understanding what needed fixing.

**(b) Wire-level test added in PR #45.** The 6-month silent bug existed because the original `TestPromptCachingEnabled` asserted against the LangChain input shape, which langchain *receives* but then *discards*. The new `TestPromptCachingWireLevel` mocks `anthropic.AsyncMessages.create` and asserts cache_control arrives in the outbound payload — verified to catch the buggy shape (test FAILS when reverted to string + additional_kwargs form) and pass with the fix. Future wrapper version bumps won't silently re-disable caching.

**(c) Manual verification supplanted aggregator at Task 2.1 close.** The aggregator's $0.022865 number was internally inconsistent with the per-call costs that empirically showed cache_read working. Walking the trace tree manually revealed the 2.95× inflation. Sprint 8.2 closes with the manual number as the authoritative baseline ($0.007754), not the aggregator number ($0.022865). This is the structural lesson: **for sprint-gating cost measurements, manual computation is the authoritative measure; aggregator output is convenience reporting that must be independently verified.**

**(d) Q1-refinement on band-violation.** Gate 0 said target 4200-4500 tiktoken tokens for the Haiku prompt; actual landed at 5185 (15% over). Pre-committed discipline said "halt and surface." User-pre-committed override fired ("band was cost-efficiency guideline, not load-bearing constraint; 5185 cleared cache + content was substantive not filler"). The override saved a content-change cycle that would have contaminated the measurement. **Same Q1-refinement pattern as Sprint 6.3 spike: pre-commits defend against bias, not against information.**

### Sprint 8.2 follow-ups filed (priority order)

1. **Sprint 8.4 (BLOCKING) — Cost telemetry aggregator audit (#TBD).** Investigate the 2.95× inflation factor in `app/services/cost_telemetry_service.py`. Likely: parent-trace `usage_metadata` propagation is double-counted alongside LLM-child counts. If confirmed, ALL Sprint 8 series cost numbers (Sprint 8.1's $0.009026 baseline, Sprint 8.2 medians) need recomputation against the corrected aggregator. This blocks Sprint 8.3 because the ceiling-re-derivation is meaningless if the aggregator that measures against the ceiling is broken.

2. **Sprint 8.3 (depends on 8.4) — Ceiling re-derivation + structural redesign question (#TBD).** Once aggregator is corrected, re-derive the cost-per-request ceiling against measured per-call costs (Haiku ~$1/M in, ~$5/M out; Sonnet ~$3/M in, ~$15/M out; both with caching) and actual call count (2). Then assess: does ResearchFlow's current model strategy (formal portal = Sonnet for requirements + Haiku for concepts) clear a defensible ceiling? If no, the structural redesign question becomes: hybrid model strategy revisit, prompt-architecture overhaul, or accept higher per-request cost as the floor.

### Sprint 8.2 closes

Issues closed by this PR's merge:
- `#37` Sprint 8.2 umbrella — diagnostic chain completed, corrected baseline established
- `#43` Task 3 re-measurement — manual per-thread baseline ($0.007754) documented
- `#44` Task 2.1 Haiku bulk-up — Haiku now caches at 100% hit rate after warmup

---

## Sprint 8.4 — Aggregator over-count root cause: `_run_cost_usd` double-charges `cache_read` tokens

### Setup

Sprint 8.2's close (2026-05-14) surfaced that `CostTelemetryService.get_formal_portal_cost_p50` reported $0.022865 against a manual per-thread sum of $0.007754 — a 2.95× inflation factor — and filed Sprint 8.4 as BLOCKING for any further ceiling-re-derivation work. The Sprint 8.2 CLOSE ADR hypothesized parent-trace `usage_metadata` was being double-counted alongside LLM-child counts via tag inheritance. **That hypothesis was wrong.**

### Diagnostic-first methodology (Sprint 8.2 structural lesson applied)

Sprint 8.4 Task 1 was static-analysis-confidence. The Sprint 8.2 close ADR's structural lesson — "for fixes whose correctness depends on third-party library behavior, the test must assert the third-party API contract" — applied. Task 1 pulled one real production trace (`trace_id=62ef0f8c-8920-42a7-bd34-e77edaf65d11` from 2026-05-14 19:56) via the langsmith SDK and walked its tree before writing any fix.

The wire-level pull contradicted the static-analysis hypothesis. The full corrected diagnostic (with trace tree dump + pricing math) is on issue [#46](https://github.com/jagnyesh/researchflow/issues/46#issuecomment-4454629786). Summary:

**(1) Parent+child double-counting did NOT happen.** The 6 `execute_task` `@traceable` chain spans carry `portal:formal` but have `metadata.thread_id == None`. `_extract_thread_id()` returns None and `_summarize_threaded` filters them out (the `if thread_id is not None:` check). Only the 2 LLM leaves per thread get bucketed. The aggregator was summing exactly the same runs the manual walk used.

**(2) The real bug: LangSmith's `Run.input_tokens` already INCLUDES `cache_read_input_tokens`.** Empirical verification on the trace: every LLM leaf satisfied `total_tokens == input_tokens + output_tokens` (cache_read is INSIDE input_tokens, not added on top). But `_run_cost_usd` charged `input_tokens * prices["input"] + cache_read * prices["cache_read"]` — double-billing the cache_read portion at both rates.

**(3) The bug fires only when `cache_read > 0`.** Sprint 8.1's 2026-05-12 traffic had `cache_hit_rate = 0.0%` everywhere; with `cache_read = 0`, the buggy formula reduces to the correct formula (the second term is zero). **Sprint 8.1's $0.009026 baseline is therefore CORRECT, not inflated.** The Sprint 8.2 CLOSE ADR's claim that "Sprint 8.1's baseline came from the same aggregator and is therefore likely also inflated" is **wrong** — corrected here.

### Fixes shipped

**(1) `_run_cost_usd` subtracts `cache_read` from `input_tokens` before pricing.** New helper `_get_non_cached_input_tokens(run) = max(0, input_tokens - cache_read)` consolidates the subtraction in one place.

**(2) `cache_hit_rate` calculation corrected via the same helper.** `_summarize_threaded` and `_summarize_per_root` previously summed raw `input_tokens` as "non_cached" — same underlying mistake. Post-fix the dashboard reports cache_hit_rate = 0.9488 on Sprint 8.2's 30-thread sample (was 0.4869 pre-fix, under-reporting by ~2×).

**(3) Wire-level fixture test.** `TestCostTelemetryService.test_cache_read_not_double_charged_against_wire_shape` uses the exact numbers from the real production trace (Sonnet `input=3362, cr=3087`; Haiku `input=5927, cr=5850`) and asserts the corrected cost. Verified to FAIL on the pre-fix formula ($0.022074) and PASS on the corrected formula ($0.006963). Future maintainers cannot revert the fix without breaking this test.

**(4) Schema contract test.** `test_langsmith_schema_contract_input_includes_cache_read` asserts `total_tokens == input_tokens + output_tokens` for the same fixture. Documents the LangSmith accounting assumption (`input_tokens` includes `cache_read`); if LangSmith ever changes accounting, the test breaks and forces revisiting `_run_cost_usd`.

**(5) `_get_input_tokens` docstring rewrite.** Previously said "Non-cached input tokens. Anthropic returns cache_read separately." That was true for Anthropic's API but wrong for LangSmith's storage. Corrected.

### Pre-committed gate (empirically verified)

| Gate | Target | Measured | Delta | Status |
|---|---:|---:|---:|:---:|
| Sprint 8.2 30-thread re-aggregate | $0.007754 | $0.007754 | 0.01% | ✅ |
| Sprint 8.1 2026-05-12 re-aggregate | $0.009026 | $0.008997 | 0.32% | ✅ |

Both within the pre-committed ±1% tolerance. The Sprint 8.1 cross-check empirically confirms the "bug only fires with caching" claim — cache_hit_rate on Sprint 8.1 traffic measured 0.0000, so the median was unaffected.

### Dashboard banner

`app/web_ui/admin_dashboard.py:show_cost_telemetry` now renders an `st.info` banner above the Sprint 8.1 verification panels: "Numbers corrected 2026-05-14 (Sprint 8.4) — pre-fix display inflated ~3× by `cache_read` double-charge bug. Sprint 8.1's $0.009026 baseline was unaffected." Future-me opening the dashboard six months from now sees the discontinuity context without digging through git history.

### Discipline notes

**(a) Diagnostic-first scoping paid for itself again.** Static analysis predicted parent+child double-count via tag inheritance. Wire-level pull (~10 min effort) revealed the real cause was a single-leaf cache_read double-charge. Without the wire-level step, Sprint 8.4 would have shipped a fix that didn't change aggregator output — or worse, attempted a `run_type == "llm"` filter that broke the existing thread-id-bucketing logic. Cost: 10 minutes. Value: avoiding a wrong-fix-shipped sprint.

**(b) Append-only revision pattern continued.** Sprint 8.2 CLOSE ADR's "Sprint 8.1 baseline suspect" claim is wrong. Per the append-only DECISIONS.md discipline (preserved from D1 of the Sprint 8.4 grill), this ADR appends the correction rather than editing the prior entry in place. Future readers see the original wrong claim AND the correction — that's how audit trails stay honest.

**(c) Empirical gates were two-part by design.** Verifying only the "fix output matches manual" leg would have left "Sprint 8.1 baseline correctness" as an inferred claim. The Sprint 8.1 cross-check turned it into measured evidence. Both gates were pre-committed before code work; both fired at sprint close. The pattern works because the prediction ("cache_hit=0% protected Sprint 8.1") was risky — falsifiable by the second gate's result.

### Sprint 8.4 closes

Issues closed by this PR's merge:
- `#46` Sprint 8.4 — Cost telemetry aggregator audit complete; fix shipped + empirically verified

### Sprint 8.3 unblocked

With the aggregator corrected, Sprint 8.3 (#47) can now re-derive the cost-per-request ceiling against measured per-call costs. The structural redesign question can be evaluated against trustworthy numbers. **Updated Sprint 8.3 framing:** the corrected Sprint 8.2 baseline of $0.007754 against the (still-valid) Sprint 8.1 baseline of $0.009026 means Sprint 8.2 delivered a real 14.1% reduction. Whether that clears a defensible ceiling for the formal portal — and what the right ceiling actually is — is Sprint 8.3's call to make against post-fix data.

---

## Sprint 7.2 — A2A FSM to LangGraph migration close-out

Captures the intent + schedules the execution to deprecate the custom A2A FSM (`app/orchestrator/`) in favor of the LangGraph FSM (`app/langchain_orchestrator/`). This ADR converts the dual-orchestration state from "silent drift accumulation" into "documented transitional state with explicit close-out trigger." No code shipped by this ADR — it's the capture step. Real execution happens in Sprint 7.2 (a future sprint, sequenced after Sprint 6.4 closes, before Sprint 6.5 starts).

### Empirical state at capture (2026-05-15)

Verified via Explore agent + direct `.env` read:

| Surface | Value |
|---|---|
| User's local `.env:87` | `USE_LANGGRAPH_WORKFLOW=true` |
| Template `config/.env.example:125` | `USE_LANGGRAPH_WORKFLOW=false` |
| Sprint 8.4 trace `62ef0f8c-...` root node | `name=LangGraph` (empirical proof Sprint 8 ran through LangGraph) |
| `app/orchestrator/` (custom A2A FSM) | 1,324 LOC across 3 files |
| `app/langchain_orchestrator/` (LangGraph FSM) | 6,490 LOC across 9 files |
| Production scripts still importing A2A | 7 (`scripts/recover_stuck_request.py`, `process_stuck_requests.py`, `fix_stuck_*.py`, `trigger_delivery.py`, `advance_workflow.py`) |
| Tests still exercising A2A path | 7 files (`test_agent_handoffs.py`, `test_admin_dashboard_updates.py`, `test_nlp_to_sql_workflow.py`, `test_preview_extraction_workflow.py`, `test_workflow_incomplete_requirements.py`, `test_database_persistence.py`, `test_dashboard_tabs.py`) |
| UI dispatcher | `researcher_portal.py:430-480` + `admin_dashboard.py:160-210` (identical conditional dispatch) |

### Why this ADR now

The dual state is **deliberate transitional**, not accidental architecture. Sprint 4 ADR ("Keep custom FSM in production; LangGraph as parallel migration target") committed to running both. Sprint 7 ADR ("LangGraph migration finalized via singleton checkpointer + LangSmith tracing") completed the technical migration — the orchestration works async-safely, all 6 agents are `@traceable`-instrumented, gradual rollout via `LANGGRAPH_ROLLOUT_PCT` works.

What was never written: a close-out ADR. The migration is **locally validated but template-still-A2A** — user's `.env` flipped (Sprint 8 series ran on LangGraph), but the template default, the 7 production scripts, and 7 test files still wire to the legacy orchestrator. Without an explicit close-out plan, this state accumulates ~5-10% maintenance tax on every agent-layer change (modify in both, debug across both, two-mode test coverage).

The 2026-05-15 architecture review (`docs/architecture/05-15architecturereview.md`, orchestration layer box) snapshotted this gap. This ADR converts the gap into a scheduled decision.

### The close-out: Sprint 7.2 (3-5 days, sequenced)

**Why "Sprint 7.2"** — preserves migration lineage. Sprint 4 (decision to migrate) → Sprint 7 (technical finalization: singleton + tracing) → Sprint 7.2 (deprecation + cleanup). A new top-level "Sprint 12" or similar would obscure the relationship.

**Why between Sprint 6.4 and Sprint 6.5** — load-bearing sequencing:
- Sprint 6.4 (sqlonfhir batch-refresh swap) doesn't touch the orchestration layer; safe with dual state.
- Sprint 6.5 (wire agents through HybridRunner for online reads) CHANGES the orchestration→agent invocation surface. **If Sprint 6.5 runs while dual orchestration exists, the wiring change has to be done in BOTH orchestrations.** Closing the migration first means Sprint 6.5 only changes LangGraph.

**Trigger:** Sprint 6.4 closes (a concrete, dated event).

### Close-out criteria (Sprint 7.2 pre-committed gates)

**1. Parity verification — structural, not content-equality.** Drive 30 formal-portal requests with `USE_LANGGRAPH_WORKFLOW=false` (legacy A2A) and 30 with `=true` (LangGraph), same inputs. Compare:

- **Workflow state sequence identical** — same states traversed in same order (e.g., `new_request → requirements_gathering → feasibility_validation → ...`)
- **Agent execution order identical** — same 6 agents fire in same sequence
- **Approval gate triggers identical** — same HITL pause points hit (requirements, phenotype, extraction, delivery)
- **Final state classification equivalent** — SUCCESS / NEEDS_HUMAN_REVIEW / FAILED bucket matches per request
- **Audit trail same shape** — `audit_logs` event count and event-type sequence match per `thread_id`

**NOT compared:** LLM-generated content. Sonnet/Haiku output is non-deterministic (different word choices, different field ordering, different prose); content-equality would fail parity verification on irrelevant differences. The five structural checks above test the orchestration's correctness, not the LLM's output stability.

This methodology is load-bearing for keeping Sprint 7.2 at 3-5 days. "Diff outputs" would balloon into a multi-week LLM-determinism investigation; structural parity is testable in hours.

**2. Template flip:** `config/.env.example` switches `USE_LANGGRAPH_WORKFLOW=true`. Fresh clones default to LangGraph.

**3. Production scripts migrated:** All 7 scripts under `scripts/` that import `ResearchRequestOrchestrator` or `WorkflowEngine` are ported to `LangGraphRequestFacade` (which already implements API-compatible methods — `request_facade.py:35-100`). Each migrated script is run against a real stuck-state row to verify recovery outcome preserved.

**4. A2A FSM deleted, not archived.** `app/orchestrator/` is removed via `git rm -r`. **Rationale: git history is the rollback mechanism.** An `app/_archive_a2a_fsm/` directory would create appearance-of-dual-state in the repo (search results, imports, AI agent discoverability) without functional benefit. If the deletion needs reversal, `git revert` recovers the directory. Future readers see a clean main-line history with the deletion's commit message documenting the rationale.

**5. Dispatcher simplified.** `researcher_portal.py:430-480` and `admin_dashboard.py:160-210` collapse to unconditional `LangGraphRequestFacade` instantiation. `USE_LANGGRAPH_WORKFLOW` and `LANGGRAPH_ROLLOUT_PCT` env vars + their handling logic removed.

**6. Test files: port-vs-delete decision per file.** For each of the 7 A2A-exercising test files, decide:
- **PORT** if the test exercises a behavior LangGraph must also exhibit (e.g., agent handoffs, persistence after restart, dashboard state-update semantics). Rewrite the test against `LangGraphRequestFacade` + `FullWorkflow`.
- **DELETE** if the test is A2A-internal (e.g., `WorkflowState` schema assertions, `WorkflowEngine` state-transition tests). LangGraph's `AgentState` is a different schema; A2A-internal tests have no LangGraph equivalent.

This decision per file is made during Sprint 7.2 execution, with the rationale recorded in the Sprint 7.2 close ADR.

**7. CONTEXT.md updated:** "Workflow nodes" line no longer mentions "two parallel implementations." Replace with "17 nodes in LangGraph FSM (`app/langchain_orchestrator/langgraph_workflow.py`)."

**8. Sprint 7.2 close ADR appended to DECISIONS.md** documenting which tests were ported vs deleted, the parity verification result (clean / bounded-diffs / large-diffs), and the date the migration formally closed.

### What this ADR is NOT

- NOT execution. Two doc-only commits land tonight (this ADR + the BACKLOG entry). The real engineering work is Sprint 7.2.
- NOT a content-equality parity claim. The five structural checks define parity for this migration; content equality is out of scope (LLM non-determinism).
- NOT a commitment to archive. Sprint 7.2 will `git rm` the legacy directory. Git history is the rollback path.
- NOT a permanent dual-state acceptance. The dual state ends in Sprint 7.2.

### Risk + mitigations

| Risk | Mitigation |
|---|---|
| Sprint 7.2 keeps getting pushed past Sprint 6.5 | Sprint 6.5's prerequisite ("close the migration first") makes deferral expensive — every sprint touching the orchestration layer pays the dual-mode tax until Sprint 7.2 runs |
| Parity verification produces bounded structural diffs (e.g., LangGraph hits an extra audit event) | Document the diff in Sprint 7.2 close ADR. Decide accept (LangGraph more correct) or fix (LangGraph wrong) per diff. Bounded diffs don't block close-out; they get tracked |
| Parity verification produces large diffs | Migration isn't actually done. Sprint 7.2 splits into 7.2a (close existing diffs) + 7.2b (deprecation). The 3-5 day estimate becomes longer; BACKLOG entry updated honestly |
| `git rm` of `app/orchestrator/` breaks something not in the 7 known scripts | Pre-Sprint-7.2 `grep -rn "from app.orchestrator" .` runs as the first task; any new caller surfaces and gets migrated before deletion |

### Empirical correction surfaced at execution start (2026-05-15)

Post Sprint 6.4 merge, the `/grill-with-docs Sprint 7.2` re-scan ran the ADR's own mitigation step (`grep -rn "from app.orchestrator"`) and surfaced **5 production-code couplings the original ADR scan missed.** Per the append-only DECISIONS.md discipline (precedent: Sprint 8.4 correcting Sprint 8.2's framing), this section appends the corrections rather than rewriting the body above.

**What the original ADR scoped:**
- 2 dispatchers (`researcher_portal.py:430-480`, `admin_dashboard.py:160-210`)
- 7 production scripts
- 7 A2A test files
- Delete `app/orchestrator/` (1,324 LOC)

**What the re-scan additionally surfaced:**

| File | Coupling | Severity if deleted naively |
|---|---|---|
| `app/main.py:21-23,113` | Owns the `ResearchRequestOrchestrator` singleton; calls `set_orchestrator` on both routers at startup | App fails to start |
| `app/api/approvals.py:15,27,30` | Receives orchestrator; FastAPI routes call methods on it | 500 on every approval route |
| `app/api/research.py:16` + 8 sites | Imports `WorkflowState` enum, uses `.value` strings as canonical state values for the `research_requests.current_state` DB column | 500 on every research route |
| `app/services/approval_service.py:14,32` | Instantiates `WorkflowEngine()` directly | 500 in approval service |
| `app/web_ui/dashboard_helpers.py:19,154,162-165` | Filters DB queries by `WorkflowState.COMPLETE/REQUIREMENTS_GATHERING/...` | Dashboard crash |

**WorkflowState is effectively the DB schema enum, not just an orchestrator internal.** `research_requests.current_state` is `Column(String)` (free-form; no DB constraint), but five production callers write/query its `.value` strings.

**A2A and LangGraph state strings diverge:** A2A's `WorkflowState` has 25 enum values; LangGraph's `langgraph_workflow.py` uses 17 distinct strings. ~15 names overlap. A2A-only that production code still references: `DELIVERED`, `REQUIREMENTS_COMPLETE`, `EXTRACTION_APPROVAL`, `SCOPE_CHANGE`, `PREVIEW_COMPLETE`, `FEASIBLE`, `KICKOFF_COMPLETE`, `EXTRACTION_COMPLETE`, `QA_PASSED`, `DELIVERY_REVIEW`. LangGraph-only: `human_review`, `preview_qa_review`. Current dev.db distribution: 113 `complete`, 3 `phenotype_review`, 2 `error`, 1 `preview_qa_review`, 1 `human_review`. No `delivered` rows.

**Latent bug surfaced (out of Sprint 7.2 scope):** `app/api/research.py:270-271,343-344,403-404` queries `WHERE current_state IN ('delivered', 'complete')`. LangGraph never writes `'delivered'` (terminal is `'complete'` only). LangGraph-completed rows are silently missing from those result sets today. Filed as [#53](https://github.com/jagnyesh/researchflow/issues/53). Sprint 7.2 preserves existing behavior and documents the bug as known-issue; the fix is a separate sprint.

### D1 decision (2026-05-15) — promote `WorkflowState` to schema module

Three options grilled:
- **A. Promote `WorkflowState` to `app/database/workflow_states.py`** (filename signals what it represents, not just that it's an enum). All 5 production callers + LangGraph + scripts import from the new home. A2A-only states stay in the enum as historical values that LangGraph doesn't emit but production code can still reference. DB rows keep their existing strings.
- **B. Adopt LangGraph state strings as source of truth.** Extract LangGraph's 17 states into a typed enum; force-port production code. Audits every reference. A2A-only states explicitly retired.
- **C. Decouple — production code uses bare strings, no Python enum.** Cheapest delete; loses type safety.

**Chose A.** Cleanest deletion path that preserves the schema; surfaces A2A/LangGraph state divergence as documented historical values rather than hidden behavior; doesn't require a DB migration (column stays `String`). The new module carries a docstring naming the historical-vs-current state values explicitly:

```python
"""Canonical workflow state strings for research_requests.current_state.

This enum was historically internal to the A2A orchestrator
(app/orchestrator/workflow_engine.py). Sprint 7.2 promoted it to a schema
module because production code (5 callers) depends on the .value strings
as the canonical DB state values.

The enum contains 25 states. The current LangGraph orchestrator emits
only 17 of them. The remaining 8 are historical values that may exist
in production DB rows from the A2A era:
    DELIVERED, REQUIREMENTS_COMPLETE, EXTRACTION_APPROVAL, SCOPE_CHANGE,
    PREVIEW_COMPLETE, FEASIBLE, KICKOFF_COMPLETE, EXTRACTION_COMPLETE,
    QA_PASSED, DELIVERY_REVIEW

These are retained for backward-compat queries. Production code that
filters by state should be aware that LangGraph never emits these
values — any query depending on them only matches pre-LangGraph rows.

Known related issue: app/api/research.py queries
WHERE current_state IN ('delivered', 'complete'). LangGraph never writes
'delivered'. Pre-existing latent bug, filed separately — not in
Sprint 7.2 scope.
"""
```

### Revised phase sequence (D1 forces a Phase 0 insert)

The original ADR's 8 phases assumed `app/orchestrator/` deletion was the lift. The empirical correction shows production callers must be migrated FIRST or the deletion breaks app startup. New sequence:

| Phase | Step | Why this order |
|---:|---|---|
| **0 (new)** | Promote `WorkflowState` to `app/database/workflow_states.py`; update 5 production callers' imports (`main.py`, `approvals.py`, `research.py`, `approval_service.py`, `dashboard_helpers.py`); update LangGraph + 7 scripts to import from new home. Run full test suite + boot app to confirm. | Decouple production code from `app/orchestrator/` BEFORE the deletion makes it impossible. After Phase 0, `app/orchestrator/` is import-clean. |
| 1 | Parity verification (30 requests through each flag value) | Need to verify equivalence before any user-visible default flip |
| 2 | Flip `config/.env.example` default to `true` | Template + CI now match user's local |
| 3 | Migrate 7 production scripts to `LangGraphRequestFacade` | Last remaining A2A callers gone |
| 4 | `git rm -r app/orchestrator/` (now safe — no production callers remain) | Phases 0+3 eliminated all callers; deletion is mechanical |
| 5 | Simplify dispatchers in `researcher_portal.py` + `admin_dashboard.py` | Conditional dispatch becomes unconditional `LangGraphRequestFacade` |
| 6 | Port-vs-delete the 7 A2A test files | Test surface follows production surface |
| 7 | Sprint 7.2 close ADR + CONTEXT.md update | Document outcomes |

**Realistic scope estimate after empirical correction:** 6-8 days (was 3-5). Phase 0 adds ~1-2 days of work. The deletion phase itself becomes cheaper (no surprise breakage during `git rm`).

**Sprint 7.2 still preserves existing behavior, not improves it.** The `delivered`/`complete` latent bug stays bug-for-bug because Sprint 7.2's pre-committed gate is structural parity, not correctness fixes. The bug is filed separately, fixed in a future sprint.

### Phase 6 risk + realistic estimate

D3 grilling locked the per-file test verdict: 5 PORT + 2 SPLIT + 3 DELETE.

| File | LOC | Verdict | Rationale |
|---|---:|---|---|
| `tests/test_agent_handoffs.py` | 431 | PORT | Behavioral test of agent routing + approval pause/resume; in-place port to `LangGraphRequestFacade` |
| `tests/test_admin_dashboard_updates.py` | 477 | PORT | Dashboard behavior must still work post Sprint 7.2 |
| `tests/test_nlp_to_sql_workflow.py` | 316 | PORT | Canonical formal-portal e2e flow LangGraph runs today |
| `tests/test_workflow_incomplete_requirements.py` | 173 | DELETE | All 6 tests exercise A2A-only API surface (`WorkflowEngine.determine_next_step`, `workflow_rules`, `is_terminal_state`, `is_approval_state`). Behaviors covered by Phase 1 parity verification. |
| `tests/test_database_persistence.py` | 519 | PORT | DB-layer tests are framework-not-engine |
| `tests/test_dashboard_tabs.py` | 432 | PORT | Same as dashboard_updates |
| `tests/test_preview_extraction_workflow.py` | 566 | SPLIT | DELETE `TestWorkflowEnginePreviewTransitions` class (A2A FSM-internal); PORT other 3 classes |
| `tests/e2e/test_ui_with_langgraph.py` | 391 | SPLIT | DELETE 2 migration-moot tests (`test_feature_flag_toggle_*`, `test_facade_has_same_interface_*`); KEEP other 5 |
| `scripts/test_approval_workflow.py` | 432 | DELETE | Stale dev script, superseded by pytest suite |
| `scripts/migrate_to_langgraph.py` | 492 | DELETE | One-shot migration helper, job complete |

**Naive Phase 6 estimate:** 5 ports × ~3hrs + 2 splits × ~2hrs + 3 deletes × ~5min = **~19-22 hrs, ~2.5 days.**

**Realistic Phase 6 estimate (per user calibration note):** **25-32 hours, 3-4 days.** File ports are NOT uniform — `test_database_persistence.py` (519 LOC) and `test_preview_extraction_workflow.py` (566 LOC) are 2-3× larger than smaller ports. Wire-level surprises are likely at port time (precedent: Sprint 6.4 cycle 4 surfaced the sqlonfhir mutation bug at port time; similar surprises probable here when LangGraph's API behaves differently than A2A's for specific edge cases the tests exercise).

**Phase 6 budget within sprint envelope:** Phase 6 alone consumes roughly 50% of the 6-8 day revised Sprint 7.2 budget. Other phases (0 enum promotion, 1 parity, 2-5 mechanical changes, 7 ADR close) consume the rest. If Phase 6 surprises blow past 4 days, the sprint splits per the existing risk register's "Parity verification produces large diffs" mitigation: Sprint 7.2a (Phases 0-5 + per-file ports as they complete) and Sprint 7.2b (any remaining ports + close ADR).

**D3b decision:** In-place port (NOT rewrite-from-scratch). Preserves `git log --follow` per file. Costs larger diffs in Phase 6 commits; the per-file commit cadence (D3c) keeps each diff scoped.

**D3c decision:** 5 per-file commits during Phase 6 (one per ported file) + 1 cleanup commit for splits + deletes. Phase 6 ends with 6 commits. Each PORT commit is a meaningful unit-of-change a future reader can bisect against.

### D2 decision — Phase 0 commit shape + name collision

**D2a (commit shape):** Phase 0 lands as ONE atomic commit on the Sprint 7.2 feature branch. Scope:
1. Create `app/database/workflow_states.py` (new module with the D1 docstring).
2. Update 8 importers (2 production: `app/api/research.py`, `app/web_ui/dashboard_helpers.py`; 1 script: `scripts/test_approval_workflow.py`; 5 tests: `test_dashboard_tabs.py`, `test_database_persistence.py`, `test_admin_dashboard_updates.py`, `test_preview_extraction_workflow.py`, `test_workflow_incomplete_requirements.py`).
3. Add `tests/test_workflow_states_promotion.py` guard test (verifies enum-still-resolves contract).
4. Run full test suite + boot app to confirm no breakage.

Rationale: 8 files is small enough that bisect-granularity from splitting isn't worth losing the atomic guarantee. Either the import-path change holds across the codebase or none of it does. Per the cadence rule, Sprint 7.2's PR squashes everything at end — in-branch commits ARE the bisect granularity.

NOT direct-to-main. This is sprint code work, not a doc snapshot. Feature branch `feature/sprint-7-2-langgraph-closeout` (or similar).

**D2b (name collision):** `app/langchain_orchestrator/simple_workflow.py:27` defines a LOCAL `WorkflowState` TypedDict (LangGraph's 3-state demo type). After Phase 0, the A2A enum becomes `app.database.workflow_states.WorkflowState` and the LangGraph TypedDict stays at `app.langchain_orchestrator.simple_workflow.WorkflowState` — same name, different modules.

**Decision A2 (resolved):**
1. **Rename `simple_workflow.WorkflowState` → `SimpleWorkflowState`** in the SAME Phase 0 commit. Two files touched: the definition + its test import. Mechanical disambiguation.
2. **Add module-level deprecation docstring** to `simple_workflow.py`:
   ```
   """Deprecated demo scaffolding from Sprint 4→7 LangGraph migration tracer
   bullet. Retained for historical reference. Slated for deletion in Sprint 7.3
   candidate (see BACKLOG.md). Zero production callers — only its own test
   file imports SimpleWorkflow."""
   ```
3. **File Sprint 7.3 candidate** in BACKLOG.md (done: commit `8e9b744`) for the full file deletion (~30 min, single commit, post-Sprint-7.2).

Logic: rename + deprecation docstring belong in the same commit as the D1 enum promotion. Both are about resolving `WorkflowState` ambiguity in the codebase. Full file deletion is out of Sprint 7.2's named scope (LangGraph cleanup, not A2A retirement) — deferred to Sprint 7.3 to avoid mid-sprint scope expansion.

### D4 decision — parity verification methodology (Phase 1)

**D4a (methodology): hybrid (option C).** Each of the 5 structural-parity dimensions queries its highest-fidelity signal source:

| Dimension | Source | Why |
|---|---|---|
| 1. Workflow state sequence | `research_requests.state_history` JSON column | Full sequence persisted per row; SQL queryable |
| 2. Agent execution order | LangSmith trace tree (root span's children, sorted by start_time) | `@traceable` decorators make agent boundaries first-class; pre-flight check required (see below) |
| 3. Approval gate triggers | `approvals` table join on request_id | Authoritative HITL pause record |
| 4. Final state classification | `research_requests.current_state` + `final_state` | DB final state is the canonical bucket |
| 5. Audit trail shape | `audit_logs` table grouped by `thread_id` | The HIPAA-grade evidence channel |

Rejected alternatives:
- **Option A (audit_logs only):** Gap on dimension 2 (agent execution order — audit_logs records route invocations, not agent boundaries underneath).
- **Option B (LangSmith trace tree only):** Gap on dimension 5 (LangSmith doesn't see `audit_logs`).

C splits each dimension to its strongest signal; harness coordinates 3 data sources but each query is scoped.

**D4b (harness location):** `scripts/parity_verify_a2a_vs_langgraph.py` — descriptive filename, sprint-number-agnostic. Same precedent as `scripts/migrate_to_langgraph.py` (which Sprint 7.2 deletes per Phase 6). Deleted at sprint close per the one-shot-tool pattern. ~250 LOC: drive 30 requests through each `USE_LANGGRAPH_WORKFLOW` value, for each thread_id pair query 3 sources, output JSONL.

**D4c (output schema):** JSONL with self-describing rows + bounded/blocking severity:

```jsonl
{"thread_id": "REQ-...", "dimension": "state_sequence",
 "langgraph": ["new_request", "requirements_gathering", "..."],
 "a2a":       ["new_request", "requirements_gathering", "..."],
 "match": true, "severity": null, "diff": null}

{"thread_id": "REQ-...", "dimension": "audit_trail_shape",
 "langgraph": ["PHI_ACCESS", "APPROVAL_REQUESTED", "..."],
 "a2a":       ["PHI_ACCESS", "APPROVAL_REQUESTED", "AUDIT_BREAKER_FIRED", "..."],
 "match": false, "severity": "bounded",
 "diff": "LangGraph emits 1 fewer AUDIT_BREAKER_FIRED event per thread; structurally equivalent"}

{"thread_id": "REQ-...", "dimension": "final_state",
 "langgraph": "complete", "a2a": "delivered",
 "match": false, "severity": "blocking",
 "diff": "Terminal state divergence — A2A two-step (delivered→complete) vs LangGraph one-step (complete only)"}
```

Each row is self-describing: a reader can verify match assessments without re-running the harness. Severity encoding makes the original ADR's "bounded diffs don't block close-out" rule concrete and harness-enforced:
- `"match": true` — equal, no diff
- `"match": false, "severity": "bounded"` — acceptable diff, documented in close ADR
- `"match": false, "severity": "blocking"` — sprint cannot close, requires fix or scope split

**Bounded-vs-blocking classification rules** (encoded in the harness):
- Per-dimension list of permitted diffs (e.g., `audit_trail_shape` permits ±1 event count for known no-ops; `state_sequence` permits LangGraph emitting `preview_qa_review` where A2A emits `preview_qa` then `qa_review` — same semantic gate, different state names).
- Anything not in the permitted-diff list defaults to `blocking`. Harness fails the sprint gate if any row is `blocking`.

Pass criterion at sprint close: 0 blocking rows. Bounded rows enumerated in Sprint 7.2 close ADR with rationale.

**Pre-flight check (required BEFORE Phase 1 begins):**

D4's option C depends on LangSmith capturing agent boundaries equivalently for both orchestrators. Per the user-imposed pre-flight gate (2026-05-15 grilling), Phase 1 cannot start until this is verified:

1. Pull one Sprint 8 trace (LangGraph era — confirmed available via Sprint 8.4 trace `62ef0f8c-8920-42a7-bd34-e77edaf65d11` from DECISIONS.md).
2. Drive one request through `USE_LANGGRAPH_WORKFLOW=false` locally, capture the resulting trace (or check LangSmith for pre-Sprint-7 traces still retained).
3. Compare trace structure at the agent-boundary level.

**Pass:** both orchestrators emit similar trace span structure (agent boundaries visible, state transitions traced). Dimension 2 works as planned.

**Fail:** A2A significantly under-instrumented. Either define "equivalent under coverage asymmetry" (relax dimension 2 to "agent NAMES match" rather than "trace span sequence matches") or find a fallback signal (`agent_executions` table has per-agent rows with timestamps — usable as dimension 2 source if LangSmith traces aren't reliable for both).

Result of pre-flight + any methodology adjustment landed in this ADR before Phase 1 commits begin.

---

## Sprint 8.3 — Cost-per-request ceilings re-derived against measured baselines; Sprint 8 series closes

Sprint 8.3 closes 2026-05-14 with corrected ceilings shipped. Scope-split per pre-committed grilling (D1=A): Sprint 8.3 is ceiling re-derivation only; the broader "structural redesign question" is decoupled into a separate sprint if and when the corrected ceilings show a genuine gap.

### Empirical inputs (2026-05-14, post-Sprint-8.4 aggregator)

Re-aggregated against trustworthy numbers, with manual trace-tree walks verifying aggregator output within ±0.01%:

| Portal | Median | n | Cache hit rate | Aggregator-vs-manual delta |
|---|---:|---:|---:|---:|
| Formal | $0.007754 | 30/30 threads | 94.88% | 0.01% |
| Exploratory | $0.003540 | 30/30 root traces | **0.0000%** | 0.000% |

### Derived ceilings (formula: `measured_median × 1.3`, per D2=A)

| Portal | Sprint 8.1 ceiling (projection × 1.3) | Sprint 8.3 ceiling (median × 1.3) | Direction |
|---|---:|---:|:---:|
| Formal | $0.0039 | **$0.010080** | +158% — old ceiling was projection-aspirational, new ceiling is measurement-grounded |
| Exploratory | $0.00091 | **$0.004602** | +406% — same shift |

### THREE framing notes (mandatory per pre-committed grilling)

**(1) Semantic shift, NOT goalpost-moving.** Sprint 8.1's ceilings were `projection × 1.3` — a tolerance band around an aspirational cost target ("we projected $0.003/request post-optimization; allow 30% tolerance"). Sprint 8.3's ceilings are `measured_median × 1.3` — a tolerance band around the current operating point ("we measure $0.007754/request at steady state; alarm at 30% above that"). The math is identical. **The meaning shifts from "cost target with tolerance" to "regression alarm against current baseline."** This is honest framing: the Sprint 8 series projections were structurally falsified by Sprint 8.2 Task 3 (3× call-count overestimate + 9× per-call cost underestimate). Setting the ceiling at measured-median × 1.3 calibrates the gate to catch regressions, not to enforce the projection that didn't match reality. Future readers who notice the ~2.5× upward ceiling shift should land on this framing first, not "they moved the goalposts."

**(2) Bursty-traffic calibration.** The medians come from `scripts/drive_qa_traffic.py` which fires 30 requests in 6-7 minutes — entirely within Anthropic's 5-min cache TTL. Steady-state caching applies to runs 2-30 (with run 1 paying cache_create). Sparse real-world traffic (gaps > 5 min between requests) would shift the median toward the worst-case cache_create cost. **The Sprint 8.3 ceilings are calibrated for bursty patterns; sparse-traffic measurement is a known gap.** Filed as Sprint 8.5 candidate (#TBD) in BACKLOG.md so the open question stays visible. Until that fires, the dashboard's gate-status reflects bursty-pattern truth; in sparse real-world traffic the median can plausibly drift into the new ceiling without indicating a code regression.

**(3) Exploratory cache_hit_rate is 0.0000%, which is a real finding.** Formal portal post-Sprint-8.2 fires cache at 94.88% (Sonnet + Haiku both cleared their thresholds). Exploratory portal QueryInterpreter shows zero cache hits on 30 root traces. This is the SAME structural class of below-threshold issue Sprint 8.2 fixed for the formal portal's `_REQUIREMENTS_SYSTEM_PROMPT` and `_MEDICAL_CONCEPTS_SYSTEM_PROMPT`. **The corrected exploratory baseline of $0.003540 is therefore the pre-caching baseline.** If QueryInterpreter were to clear Anthropic's caching threshold (likely requires bulking the system prompt past 1024 tokens for Sonnet fallback or 4096 for Haiku primary, plus the langchain content-block-array form from PR #45), the exploratory median would drop further and the $0.004602 ceiling would become trivially generous. Filed as Sprint 8.6 candidate in BACKLOG.md. This finding is OUT OF SCOPE for Sprint 8.3 (which is ceiling derivation only per D1=A) but the ceiling derivation is honest about the assumption it bakes in.

### What shipped

- `app/services/cost_telemetry_service.py:82-110` — `FORMAL_BAND_CEILING_USD` and `EXPLORATORY_BAND_CEILING_USD` updated with multi-line provenance comments explaining the semantic shift, traffic-pattern assumption, and exploratory caching finding.
- All 16 existing `test_cost_telemetry_service.py` tests pass against the new ceilings (the tests assert against the constants by name, not by value, so changing the numbers doesn't break them).

### Gate verification (informational — ships against new ceilings)

| Portal | Median | New ceiling | Gate |
|---|---:|---:|:---:|
| Formal | $0.007754 | $0.010080 | 🟢 GREEN |
| Exploratory | $0.003540 | $0.004602 | 🟢 GREEN |

**Both portals now GREEN against the corrected ceilings.** This is the predictable consequence of calibrating the ceiling to the current operating point — the gate's job becomes regression-alarm, not target-pursuit. The structural redesign question (does ResearchFlow's current model strategy clear a defensible ceiling?) collapses to "yes, against a measurement-grounded ceiling." If the user wants a TIGHTER ceiling (e.g., "we won't accept current cost as the floor — get it under $0.005/request"), that's the structural redesign sprint, not Sprint 8.3.

### Sprint 8 series closes

| Sprint | Verdict | Outcome |
|---|---|---|
| 8 (original, 2025) | SHIPPED — implementation projected 73% reduction | Reality: projection falsified by Sprint 8.2 |
| 8.1 (verification, 2026-05-12) | CLOSED RED | Correct at $0.009026 (cache_hit=0% protected baseline from aggregator bug) |
| 8.2 (cache-hit investigation, 2026-05-14) | CLOSED — three failure modes diagnosed | Cache_control wire fix shipped; manual baseline $0.007754 established |
| 8.4 (aggregator audit, 2026-05-14) | SHIPPED | `cache_read` double-charge fixed; aggregator now matches manual ±0.01% |
| 8.3 (this sprint, 2026-05-14) | SHIPPED | Ceilings re-derived against measured medians; both portals GREEN at new ceilings |

The arc: ship → measure → falsify projection → diagnose three concurrent failure modes → fix transmission bug → fix aggregator bug → re-derive ceilings against trustworthy data. Took 5 sprints. The structural lesson — "for fixes whose correctness depends on third-party library behavior, the test must assert the third-party API contract" — was named in Sprint 8.2 and applied recursively in Sprint 8.4. Sprint 8.3 closes by codifying the corrected ceilings in code with provenance preserved in this ADR.

### Sprint 8.3 closes

Issues closed by this PR's merge:
- `#47` Sprint 8.3 — Cost-per-request ceilings re-derived against measured baselines

Filed by this PR:
- Sprint 8.5 candidate — sparse-traffic median measurement (calibrate against gaps > 5 min between requests; verify Sprint 8.3 ceilings still defensible OR re-derive for sparse case)
- Sprint 8.6 candidate — exploratory portal caching (QueryInterpreter shows cache_hit=0%; same class as Sprint 8.2's formal-prompt issue)

---

## Sprint 6.4 — sqlonfhir integration: dispatch-on-runner_hint + 3 zero-row MVs ported + post-write health check

Sprint 6.3's verdict (revised same-day to GO sqlonfhir) committed the project to swapping the FHIRPath engine for 3 view-defs the custom transpiler couldn't deliver (observation_labs + condition_diagnoses both had non-trivial `where(...)` filters; procedure_history needed `forEachOrNull` outer-join semantics). Sprint 6.4 ships that swap with the smallest possible blast radius: per-view-def opt-in via a `runner_hint` field, two backend methods on `ViewMaterializer`, and the existing custom path unchanged for the 4 MVs it already serves correctly.

### Five coupled decisions (locked into issue #40 pre-implementation grilling)

**(1) Dispatch granularity — per-view-def `runner_hint`, NOT per-resource-type or per-environment env var.** Per-view-def lets the 3 sqlonfhir-target view-defs each declare their backend choice in their own JSON file (`"runner_hint": "sqlonfhir"`). The 4 working custom-path MVs (patient_simple, patient_demographics, condition_simple, medication_requests) declare nothing and default to custom. Per-resource-type ("all Conditions go through sqlonfhir") was rejected — condition_simple works correctly via custom today and forcing it into the new backend would expand blast radius without payoff. Env var ("USE_SQLONFHIR=true") was rejected — it's the same trap as Sprint 6.1 Phase 2.2's no-AUDIT_ENABLED rule: a flag that lets the wrong path stay live indefinitely. Per-view-def opt-in makes the routing decision read directly from the view-def the dispatcher is processing.

**(2) Storage shape asymmetry accepted — custom path writes `CREATE MATERIALIZED VIEW`, sqlonfhir path writes `CREATE TABLE + TRUNCATE + INSERT`.** The custom backend produces a SQL string that Postgres can materialize; the sqlonfhir backend produces rows in memory (via `sqlonfhir.evaluate()`). Two storage shapes for the same logical surface (`sqlonfhir.<view_name>`). Trade accepted: type-aware DROP via `pg_class.relkind` lookup (returns bytes `b"r"` for table vs `b"m"` for materialized view — asyncpg-specific gotcha worth documenting), and CONCURRENTLY refresh is no longer available for sqlonfhir-path MVs. Pre-aligning the storage shape (e.g., writing the sqlonfhir output back through `CREATE MATERIALIZED VIEW AS SELECT ... FROM jsonb_to_recordset(...)`) was considered and rejected — it adds ~50 lines of JSON-to-Postgres marshaling for negligible operational benefit (the batch refresh path doesn't run concurrently with reads anyway; the existing `materialize_views.py` is invoked manually or nightly).

**(3) Health-check detection mechanism — same-run oracle, 5% per-run threshold, N=3 consecutive-warn alarm filter, JSONL output.** Same-run oracle (query HAPI count and MV row count at the same materialization moment) is data-drift-immune: the oracle moves with the data, so a delta between MV and oracle is a code regression, not a fixture drift. 5% per-run threshold is the slack against transient HAPI consistency hiccups. N=3 consecutive-warn alarm filters single-run noise — one warn doesn't fire the alarm; three in a row does. JSONL output keeps the log machine-parseable and append-only; the dashboard reads the tail. Residual risk: if the bug introduces a CONSISTENT 5%+ delta across runs, the alarm only fires after 3 batch refreshes — accepted because the alternative (alarm on first warn) is noisier in practice.

**(4) Health-check scope — sqlonfhir MVs only this sprint; custom-path MV oracles deferred.** The 3 sqlonfhir-target MVs have explicit oracle queries in `tests/fixtures/mv_row_count_oracles.sql` (with documented WHERE-clause replication + data observations). The 4 custom-path MVs do NOT have oracle queries this sprint — adding them would be marginal: cycle 7's regression test already verifies the row count anchors against raw resource counts (no WHERE clauses on any of the 4), and the transpiler harness (Sprint 6.2 Phase 1.1, 48/48 tests) is the existing regression net. Filed as Sprint 6.6 candidate to add oracles for the custom-path MVs if a future bug surfaces that the transpiler harness misses.

**(5) Test surface — wire-level integration for both backends; the unit-only level cannot catch the routing bug.** Each backend gets one end-to-end integration test parametrized over its set of MVs: `test_sqlonfhir_integration.py` covers the 3 sqlonfhir-path MVs; `test_custom_path_regression.py` covers the 4 custom-path MVs. Both gated by `@pytest.mark.requires_hapi` so the suite runs cleanly offline. Dispatch unit tests (`test_backend_dispatcher.py`) cover the routing primitive in isolation. Same structural lesson as Sprint 8.2 PR #45: when the system under test depends on third-party library shape (here: sqlonfhir's evaluate() output, asyncpg's pg_class return type), assert at the wire, not the wrapper.

### Empirical outcome (2026-05-15)

All 6 pre-committed gates GREEN. Full HAPI-gated suite: **35/35 PASS in ~88s**.

| Gate | Target | Measured | Status |
|---|---|---|:---:|
| #1 row count ≤1% of oracle, sqlonfhir MVs | 3/3 within tolerance | 3/3 exact match (0.00% delta) | ✓ |
| #2 4 custom-path MVs unchanged | 4/4 within 1% | 4/4 exact match | ✓ |
| #3 observation_labs materialize ≤60s | ≤60.0s | 53.7s (6s headroom) | ✓ |
| #4 audit middleware unchanged | no audit-touching code | no audit-touching code | ✓ |
| #5 dispatch unit test exists | yes | 4 unit tests in test_backend_dispatcher.py | ✓ |
| #6 sqlonfhir equivalence (Sprint 6.3) | 3/3 match HAPI oracle | 3/3 + same-run health check ongoing | ✓ |

Three sqlonfhir MVs land at expected counts:
- `condition_diagnoses`: 14,832 rows (matches HAPI oracle exactly)
- `observation_labs`: 157,689 rows (matches HAPI oracle exactly)
- `procedure_history`: 66,448 rows (matches HAPI oracle exactly)

### What this sprint NOTABLY did NOT do

- **Did not flip any agents through HybridRunner.** Sprint 6.2 architectural gap (production agents bypass the Runner stack) is unchanged. Sprint 6.5 candidate.
- **Did not change the API surface to materialized_views router.** Sprint 6.1 Phase 2.5 admin-gating and view_name allowlist remain in place; no new endpoints; no migration of existing endpoints.
- **Did not migrate condition_simple from custom to sqlonfhir.** It works correctly via custom; per D1, opt-in is per-view-def. If a future ingestion adds resources where condition_simple's transpiled SQL produces wrong rows, that's the migration trigger; not now.
- **Did not retire the custom-FHIRPath transpiler.** It serves 4 MVs correctly and the Sprint 6.2 Phase 1.1 transpiler harness (48/48 tests) is the regression net for ALL of them. Sprint 6.4 narrows the transpiler's scope, doesn't remove it.

### Eight-cycle structure (vertical-slice /tdd, one RED→GREEN per cycle)

The sprint shipped across 8 commits on `feature/sprint-6-4-sqlonfhir-integration`:

| Cycle | Tracer bullet | Commit |
|---|---|---|
| 1 | Backend dispatch primitive + 4 unit tests | `7e1afaa` |
| 2 | ViewMaterializer dispatch integration | `0a63f1e` |
| 3 | sqlonfhir end-to-end for condition_diagnoses | `b4d7d76` |
| 4 | observation_labs + procedure_history via sqlonfhir | `d5d2e82` |
| 5 | post-write MV health check + jsonl logging | `9eed8e2` |
| 6 | admin-dashboard MV health surface | `401e8c0` |
| 7 | custom-path MV regression check | `60abeff` |
| 8 | sprint close docs (this commit) | tba |

Each cycle added ≤1 new module + its tests, kept the full suite GREEN, and was self-demoable. Cycle 4's sub-decision (architectural asymmetry around CREATE TABLE vs MATERIALIZED VIEW) was the only one that required mid-sprint design adjustment — captured in cycle 4's commit message and decision (2) above.

### Discipline notes — what made this sprint work

**(a) Locked pre-commits into issue #40 body before code work.** The Sprint 6.3 verdict-revision precedent established that pre-commits defend against bias, not information. Sprint 6.4's grilling produced 6 numeric gates that became the test-suite's structure (each gate = an assertion in a specific test file). Cycle 7 in particular existed only because gate #2 demanded explicit verification — without the pre-commit, the temptation would have been "the existing transpiler harness covers it." Empirically it does, but the new test catches a regression class (mis-dispatching to sqlonfhir for a custom-path view-def) that the harness can't.

**(b) Sub-decision surfaced mid-sprint, captured in commit message + ADR.** Before cycle 3, the implementing agent surfaced "the sqlonfhir backend produces rows, not SQL — we can't write through CREATE MATERIALIZED VIEW." User chose B (embrace the asymmetry) over A (marshal rows back through a SELECT-from-VALUES MV) with explicit rationale documented in cycle 3's commit. Decision (2) above is the formal capture. Sub-decisions caught at implementation time, not at design time, are the cheapest cost-of-change.

**(c) Cycle 4 surfaced an asyncpg-specific gotcha.** `pg_class.relkind` returns `bytes` (b"r"/b"m") under asyncpg, not `str`. The DROP-by-type dispatcher silently failed until the bytes comparison was added. Lesson: typed comparisons at trust-boundary reads (DB return values are a trust boundary, same as third-party library outputs). Sprint 8.2's structural lesson generalizes: assert against the wire shape, not the wrapper shape.

**(d) Lean-ctx tools used through the sprint after the user called out the prior session's drift.** ctx_read, ctx_search, ctx_edit, ctx_shell replaced native Read/Bash/Edit where applicable. Cycle 4 onward. The token-efficiency win was material on a sprint that touched 8 commits across the lifetime of the work.

### Sprint 6.4 closes

Issues closed by this sprint's merge:
- `#40` Sprint 6.4 — sqlonfhir integration + dispatch plumbing + port 3 zero-row MVs
- `#41` procedure_history view-def `forEachOrNull` fix (landed with Sprint 6.3 spike PR; verified in cycle 4)

Filed by this sprint:
- **Sprint 6.6 candidate** — custom-path MV health-check oracles. The 4 custom-path MVs currently rely on the transpiler harness for regression coverage; adding explicit oracles (raw resource count anchors per cycle 7's pattern, plus any WHERE-clause replication if a custom view-def later gains a WHERE) would unify the health-check surface for all 7 MVs. File when transpiler harness misses a regression OR when a custom view-def gains a non-trivial WHERE clause.

### Sprint 7.2 unblocked

Per the Sprint 7.2 ADR's sequencing rationale ("Sprint 6.4 closes → Sprint 7.2 starts → Sprint 6.5 starts"), the A2A FSM to LangGraph migration close-out is now the next-up sprint. Sprint 6.5 (agents through HybridRunner) waits behind 7.2 to avoid forcing the wiring change in both orchestrations.
