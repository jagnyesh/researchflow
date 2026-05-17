---
sprint: 5.5
status: shipped
supersedes: []
superseded_by: null
related: []
---

# Sprint 5.5 — Redis as Lambda speed layer

Need <1 minute data freshness. Options: Kafka + stream processor (heavyweight, ops cost) vs Redis with TTL (24hr) + HybridRunner merge. **Chose: Redis.** Reuses existing Redis deployment, fits the 24hr-Redis / nightly-MV synchronization model, and HybridRunner deduplicates on the merge.
