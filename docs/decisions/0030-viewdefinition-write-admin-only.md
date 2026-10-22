---
date: 2026-10-21
status: accepted
supersedes: []
superseded_by: null
related: [0007-sprint-6-1-hipaa-security-baseline.md, 0029-api-error-path-phi-safe-500s.md]
---

# ViewDefinition writes are admin-only; execution stays open (#178)

**Context.** No `/analytics/*` route had a role dependency. Any authenticated user, researchers included, could create, overwrite or delete ViewDefinition files, and could execute any definition against HAPI. ViewDefinitions feed SQL generation and the materialized views. Writing one is an infrastructure change, the same class as the MV mutations `materialized_views.py` already gates admin-only (#26).

**Decision.**
- `POST` and `DELETE /analytics/view-definitions` require `require_role("admin")`.
- Execution and reads stay open to any authenticated user: `/analytics/execute`, `/count`, `/query`, `/schema`, and `GET /view-definitions`.

## Considered options

- **Admin plus informatician for writes.** Rejected. Informaticians review SQL, but authoring definitions changes what every caller's queries compile to; that is the wider blast radius.
- **Restrict execution to admin and informatician.** Rejected. Once writes are gated, a researcher can only run curated definitions, so execution adds no new SQL shapes. Closing it would cut researchers off from the analytics API for no boundary gain.

## Consequences

- No in-repo caller creates or deletes definitions through the API (checked when #178 shipped). Library changes now go through an admin or through the repo.
- Overwriting is gated as part of create. That includes the case-insensitive-filesystem collision found in #177's review, where `PATIENT_SIMPLE` overwrote `patient_simple.json`.
