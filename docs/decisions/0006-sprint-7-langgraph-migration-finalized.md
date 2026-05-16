---
sprint: 7
status: shipped
supersedes: []
superseded_by: null
related: []
---

# Sprint 7 — LangGraph migration finalized via singleton checkpointer + LangSmith tracing

Bug #11 surfaced: AsyncSqliteSaver was being recreated per workflow invocation, causing event-loop conflicts and 100% async failure. **Chose: singleton checkpointer pattern with `threading.Lock` for atomic recreation on event-loop ID change.** All 6 production agents instrumented with `@traceable`. Gradual rollout via `LANGGRAPH_ROLLOUT_PCT` percentage flag rather than binary toggle.
