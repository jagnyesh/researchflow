---
sprint: 4.5
status: shipped
supersedes: []
superseded_by: null
related: []
---

# Sprint 4.5 — Lambda batch layer via materialized views

Need cohort-count latency under 50ms. Two options: query optimization (incremental, capped) vs precomputed views (10-100x speedup, refresh complexity). **Chose: PostgreSQL materialized views in `sqlonfhir` schema, refreshed nightly.** Synchronizes with 24hr Redis TTL on the speed layer (Sprint 5.5) so the merge window is bounded.
