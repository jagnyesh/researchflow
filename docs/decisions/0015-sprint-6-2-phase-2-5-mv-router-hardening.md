---
sprint: 6.2
date: 2026-05-08
status: shipped
supersedes: []
superseded_by: null
related: []
---

# Sprint 6.2 Phase 2.5 (out-of-band) — Materialized-views router hardening: admin gate every mutating endpoint + view_name allowlist before any SQL is built

`/cso` review of PR #24 surfaced a CRITICAL pre-existing finding: `DELETE /analytics/materialized-views/{view_name}` f-string-interpolated the path param into a `DROP MATERIALIZED VIEW IF EXISTS sqlonfhir.{view_name} CASCADE` statement with no admin gate, only Sprint 6.1's audit-middleware default-deny (which any researcher token passes). The mock researcher account (`researcher@example.com / password123`, loaded at import time in every environment) made the SQLi path one POST + one DELETE away. **Decision: harden in-band on PR #24 rather than ship and follow-up.** Three coupled choices:

**(1) Per-endpoint `Depends(require_role("admin"))`, not router-level dependency.** The materialized-views router has 8 endpoints. 5 are mutating (1 was already gated by `019666d`/issue #18; 4 weren't). 3 are read-only (list, status, health) and should stay reader-accessible. Per-endpoint dependencies make the gate VISIBLE in each function signature — a future maintainer sees `_admin=Depends(require_role("admin"))` and can't miss it. Router-level with selective opt-out (set the dep on the router, override on GETs) was rejected: it's the same "looks-secure" anti-pattern that bit us originally — the pattern signals "everything is gated" while one carve-out negates it.

**(2) Allowlist via `ViewDefinitionManager.list()` filename-stems + identifier regex `^[a-z][a-z0-9_]*$`, both returning 404.** Filename-stem allowlist gives membership in O(1) against a server-side list. The regex is belt-and-suspenders for the future case where someone drops a malformed JSON file under `app/sql_on_fhir/view_definitions/` — even then, the regex refuses to interpolate it. Both branches return 404 (not 422) so callers cannot distinguish "malformed name" from "unknown view" — same response surface as `GET /{view_name}/status` when the view doesn't exist. Hardening the SELECT/COUNT paths in `materialized_view_runner._build_query` (lines 321, 349) is out of scope: `view_name` there arrives via `view_def["name"]` from server-controlled JSON files, not user input. Already safe.

**(3) Test mock pattern: override `get_current_active_user`, NOT `require_role("admin")`.** First test attempt overrode `app.dependency_overrides[require_role("admin")]` and the override didn't fire. Root cause: `require_role` is a factory that returns a NEW `role_checker` function instance each call — the route captured a different instance than the test override creates. Override `get_current_active_user` (the inner dependency that EVERY `role_checker` delegates to) instead. One override covers all 5 admin-gated routes. Documented in `tests/test_materialized_views_auth.py` comment block to save the next dev the same hour. Tests prove injection payloads return 404 AND `db_client.execute_query` is `assert_not_called` — the SQL layer is provably never reached, not just "passes a status check."

Identifier-quoting via `psycopg2.sql.Identifier` rejected: post-allowlist, `view_name` is known-safe (letter-prefixed lowercase ASCII identifier from a JSON file stem). Adding a new dependency just for `sql.Identifier` is marginal-gain.
