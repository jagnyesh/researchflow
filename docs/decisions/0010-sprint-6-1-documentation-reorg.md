---
sprint: 6.1
status: shipped
supersedes: []
superseded_by: null
related: []
---

# Sprint 6.1 — Documentation reorg: split CLAUDE.md, create CONTEXT/DECISIONS/BACKLOG, install mattpocock/skills

CLAUDE.md grew to 978 lines, claiming Sprint 7 was "ready for production rollout" while Sprint 6.1 was the actual active work. ~16K tokens auto-loaded per session of stale prose. **Chose: slim CLAUDE.md to ~80 lines with `@`-imports; create CONTEXT.md (current state), DECISIONS.md (this file), BACKLOG.md (forward plan); install mattpocock/skills globally for `/caveman` and `/grill-with-docs`.** Hooks added in Phase 2 for HIPAA path enforcement and SQL validation.
