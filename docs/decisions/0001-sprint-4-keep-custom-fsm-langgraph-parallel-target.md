---
sprint: 4
status: shipped
supersedes: []
superseded_by: null
related: []
---

# Sprint 4 — Keep custom FSM in production; LangGraph as parallel migration target

Benchmarked LangGraph against the existing custom orchestrator (71/71 tests passed both sides). LangGraph won on observability, durability, and maintainability; custom won on incumbency and zero-risk path. **Chose: keep custom in production, build LangGraph migration in parallel behind feature flag.** Migration uses adapter pattern over rewrite to preserve 1,500+ lines of agent business logic.
