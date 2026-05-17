---
sprint: 6.1
status: shipped
supersedes: []
superseded_by: null
related: []
---

# Sprint 6.1 — Durable audit pipeline via Redis queue, not BackgroundTasks

Initial design used FastAPI `BackgroundTasks` for audit writes. Codex review flagged: data loss on uvicorn worker crash, deploy, or OOM. **Chose: sync write to Redis `audit:queue` list inside request middleware, asyncio background drain task in `app/main.py` lifespan flushes to `audit_logs` table.** If Redis dies, audit writes fail loudly — correct posture for HIPAA. Reuses existing Redis deployment.
