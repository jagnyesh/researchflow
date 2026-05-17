---
sprint: 5
status: shipped
supersedes: []
superseded_by: null
related: []
---

# Sprint 5 — LangSmith for observability over custom logging

Custom structured logging vs LangSmith with `@traceable`. Custom gives full control; LangSmith gives trace replay, cost tracking, and prompt versioning out of the box. **Chose: LangSmith** at <5ms overhead per call. Trade: vendor dependency, but key rotation runbook documented and traces are exportable.
