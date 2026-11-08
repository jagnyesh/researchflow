---
sprint: null
date: 2026-11-07
status: accepted
supersedes: []
superseded_by: null
related: [0028-sprint-6-7-exploratory-llm-sql-synthesis.md]
---

# Compose store URLs match what the code reads, and the exploratory fallback is development-only (#312)

**Amends** the `EXPLORATORY_DB_URL` guard that ADR 0028 decision 4 added with the `rf_readonly` role. ADR 0028 is left unedited, following the append-only convention. `rf_readonly` is the Postgres role that can only `SELECT` the `sqlonfhir` views. The exploratory portal runs its LLM-synthesized SQL as that role.

**Problem.** The compose `app` service sets environment names and values that the code doesn't read:
- `EXPLORATORY_DB_URL` is unset, so `FeasibilityService` falls back to `HAPI_DB_URL` and would run synthesized SQL as the full `hapi` user. The guard refuses the fallback only when `ENVIRONMENT` is `production`. With `staging` or a typo, it logs a warning and continues.
- `/health` reads `FHIR_BASE_URL` (`app/api/health.py:29`), but compose and `app/clients/fhir_client.py` use `FHIR_SERVER_URL`. Inside the container, `/health` probes `localhost:8081`.
- Compose sets `HAPI_DB_URL` to `postgresql://`. `get_hapi_engine()` builds a SQLAlchemy async engine from it, and the async engine rejects that scheme. It needs `postgresql+asyncpg://`.
- `langgraph_workflow.py:221` reads `HEALTHCARE_DB_URL` and passes it to `DataExtractionAgent`. That agent's `SQLonFHIRAdapter` has ignored its `database_url` argument since #8, so the variable controls nothing.

#274 fixed the same class of problem for the host in `HAPI_DB_URL`.

**Severity: latent.** No synthesized SQL runs in the compose `app` container today. In `app/`, only the Streamlit notebook (`app/web_ui/research_notebook.py`) builds a `FeasibilityService`, and compose doesn't run the notebook. `scripts/drive_qa_traffic.py` builds one on the host. The container runs `uvicorn app.main:app`. The `app` image probably can't start at all, because `build: .` resolves to `config/`, which has no `app/` package. That finding comes from `docker compose config`, not from a build, and is filed as #389.

**Decision (owner, 2026-11-07).**
1. `FeasibilityService` falls back to `HAPI_DB_URL` only when `ENVIRONMENT` is exactly `development`. An unset `ENVIRONMENT` counts as `development`, as it does in `app/security/auth.py`, `tls.py` and `encryption_keys.py`. Every other value raises `RuntimeError` at construction, including `staging`, `Development` and `test`. Compose sets `EXPLORATORY_DB_URL` to the `rf_readonly` role on `hapi-db`, so the fallback never runs there.
2. `FHIR_SERVER_URL` is the only FHIR URL variable. `/health` builds `FHIRClient()` without a base URL when a request arrives, so `fhir_client.py` is the only place that reads the variable. `FHIR_BASE_URL` gets no alias, because nothing sets it.
3. The `HEALTHCARE_DB_URL` read is deleted, and compose doesn't set the variable. The extraction agent receives `HAPI_DB_URL`, which matches what it does today.
4. Compose sets `HAPI_DB_URL` to `postgresql+asyncpg://`, as the host `.env` already does. `HAPIDBClient` strips the `+asyncpg` suffix, so it accepts both forms.
5. A test in `tests/test_health_stores.py` collects every store URL variable named as a string literal in `app/` outside `app/web_ui/`. Store URL variables are `DATABASE_URL`, `*_DB_URL`, `FHIR_*URL` and `REDIS*_URL`. The test asserts that compose's `app` environment sets each one and points it at a compose service, not at `localhost`. It also checks that `create_async_engine` accepts compose's `DATABASE_URL` and `HAPI_DB_URL`, and that `EXPLORATORY_DB_URL` connects to `hapi-db` as `rf_readonly`.

**Considered options.**
- Keeping the production-only refusal leaves `staging` and any typo running synthesized SQL as `hapi`.
- Dropping the fallback entirely breaks five test files that construct `FeasibilityService` without the variable. It also breaks the notebook for anyone whose dev database predates #106 and lacks the role.
- Allowing `test` as a fallback value adds a value that no test or CI job sets. The documented values are `development`, `staging` and `production` (`config/.env.example`).
- A hard-coded list of variable names in the compose test misses the next variable someone adds. #274 and #312 are that miss, twice.

**Consequences.**
- With `ENVIRONMENT=staging` and no `EXPLORATORY_DB_URL`, the notebook fails at startup instead of warning.
- `POST /analytics/materialized-views/create-all` runs `scripts/create_materialized_views.py`, which calls `asyncpg.connect` directly, and asyncpg rejects the `+asyncpg` scheme. The endpoint already fails with the host `.env`. Normalizing the scheme in the script is #390.
- `tests/e2e/test_extraction_synthea_csv.py` still sets `HEALTHCARE_DB_URL` as if it chose the extraction database. It never did (#391).
