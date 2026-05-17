---
sprint: 6
status: shipped
supersedes: []
superseded_by: null
related: []
---

# Sprint 6 — Parameterized SQL via SQLAlchemy `text()` + bound params

30 SQL injection vulnerabilities found via Bandit. Two remediation patterns: ORM-only (rewrite all dynamic SQL) vs `text()` with named bind params (preserves SQL clarity). **Chose: `text()` + bound params** returning `(sql, params)` tuples from generators. Easier to audit and keeps the SQL-on-FHIR query strings readable.
