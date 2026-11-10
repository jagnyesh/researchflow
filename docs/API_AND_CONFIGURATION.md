# API and configuration

This reference covers the HTTP API, the environment variables that the code reads, the test commands, and the fixes for common errors. The interactive API docs are at <http://localhost:8000/docs> when the API runs.

## Authentication

Every route needs a bearer token, except `/`, `/health`, `/health/live`, `/health/ready`, the docs pages, and the login routes. A request without a valid token gets a 401. Users exist only in the `users` table, with the role `researcher`, `data_steward`, or `admin`.

```bash
# Create the first admin. The script prompts for the password.
python scripts/create_user.py admin@example.org "First Admin" --role admin
```

```python
import getpass
import requests

API = "http://localhost:8000"
login = requests.post(
    f"{API}/auth/login",
    json={"email": "admin@example.org", "password": getpass.getpass()},
)
headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
```

## Endpoints

```
# Authentication
POST   /auth/login                              Return a JWT for an email and password
POST   /auth/refresh                            Return a new JWT
POST   /auth/logout                             End the session
GET    /auth/me                                 Return the caller's user record
POST   /a2a/token                               Return a service token

# Research requests, read only. A portal starts each request in-process.
GET    /research/                               List the 50 newest requests that the caller may see
GET    /research/{request_id}                   Return one request's status
GET    /research/{request_id}/delivery          Return the delivery metadata
GET    /research/{request_id}/download          Download the delivery
GET    /research/{request_id}/download/{filename}   Download one file

# Approvals
GET    /approvals/pending                       List pending approvals, with an optional approval_type filter
GET    /approvals/{approval_id}                 Return one approval
POST   /approvals/{approval_id}/respond         Approve, reject, or modify
GET    /approvals/request/{request_id}          List a request's approvals
POST   /approvals/scope-change                  Request a scope change
POST   /approvals/check-timeouts                Mark timed-out approvals and create escalations

# SQL-on-FHIR analytics
GET    /analytics/view-definitions              List the ViewDefinitions
GET    /analytics/view-definitions/{view_name}  Return one ViewDefinition
POST   /analytics/view-definitions              Create a ViewDefinition (admin)
DELETE /analytics/view-definitions/{view_name}  Delete a ViewDefinition (admin)
POST   /analytics/execute                       Run a ViewDefinition and return rows
GET    /analytics/execute/{view_name}           Run a ViewDefinition by name
POST   /analytics/count                         Count a ViewDefinition's rows
POST   /analytics/query                         Run several ViewDefinitions and combine the results
GET    /analytics/schema/{view_name}            Return a view's columns
GET    /analytics/materialized-views/           List the materialized views
GET    /analytics/materialized-views/{view_name}/status
POST   /analytics/materialized-views/{view_name}/refresh   (admin)
POST   /analytics/materialized-views/refresh-all           (admin)
POST   /analytics/materialized-views/refresh-stale         (admin)
POST   /analytics/materialized-views/create-all            (admin)
DELETE /analytics/materialized-views/{view_name}           (admin)

# Health
GET    /health                                  Check the database, the FHIR server, and the caches
GET    /health/live                             Liveness probe
GET    /health/ready                            Readiness probe
GET    /health/ready/detailed                   Readiness with the audit-queue state
```

The API also serves `/users`, `/sql_query`, and `/mcp/context`. `app/api/` has one module for each router.

## Examples

### Start a formal request

No HTTP endpoint submits a request. The formal portal and the exploratory portal both call `LangGraphRequestFacade` in-process.

```python
from app.langchain_orchestrator.request_facade import LangGraphRequestFacade

facade = LangGraphRequestFacade(use_real_agents=True, use_persistence=True)
request_id = await facade.process_new_request(
    researcher_request="Female patients over 50 with diabetes in past 2 years",
    researcher_info={"name": "Dr. Smith", "email": "smith@hospital.org", "irb_number": "IRB-2025-001"},
    from_formal_portal=True,
)
```

### Approve the SQL

```python
approvals = requests.get(
    f"{API}/approvals/pending?approval_type=phenotype_sql", headers=headers
).json()["approvals"]

requests.post(
    f"{API}/approvals/{approvals[0]['id']}/respond",
    headers=headers,
    json={
        "decision": "approve",
        "reviewer": "informatician@hospital.org",
        "notes": "SQL validated against schema",
    },
)
```

`decision` is `approve`, `reject`, or `modify`.

### Run a ViewDefinition

```python
response = requests.post(
    f"{API}/analytics/execute",
    headers=headers,
    json={
        "view_name": "patient_demographics",
        "search_params": {"gender": "female"},
        "max_resources": 100,
    },
)
results = response.json()
print(f"Found {results['row_count']} patients")
```

[`API_EXAMPLES.md`](API_EXAMPLES.md) has more analytics calls. Its examples send no token, so add the `Authorization` header.

## Environment variables

`config/.env.example` is the template. This table is partial. It lists the variables that you set to run the system or to change what the system does. `grep -rhoE "getenv\(\"[A-Z_0-9]+\"" app | sort -u` lists every variable that the code reads.

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | None | Required for every LLM call |
| `DATABASE_URL` | `sqlite+aiosqlite:///./dev.db` | Application database. Use `postgresql+asyncpg://` for Postgres |
| `HAPI_DB_URL` | `postgresql+asyncpg://hapi:hapi@localhost:5433/hapi` | HAPI Postgres, where the `sqlonfhir` schema lives |
| `EXPLORATORY_DB_URL` | None | Connection for the `rf_readonly` role. Required unless `ENVIRONMENT` is `development` or unset |
| `FHIR_SERVER_URL` | `http://localhost:8081/fhir` | FHIR REST endpoint |
| `REDIS_URL` | `redis://localhost:6379/0` | Speed layer |
| `USE_SPEED_LAYER` | `true` | Turns the speed-layer merge on or off |
| `REDIS_AUDIT_URL` | None | Audit queue. When it is unset, every PHI route returns 503 |
| `ENVIRONMENT` | `development` | `production` turns on the TLS redirect, HSTS, and the startup checks |
| `JWT_SECRET_KEY` | A development default | Signs the tokens. Required in production |
| `A2A_JWT_SECRET` | `devsecret` | Signs the service tokens |
| `ENCRYPTION_KEY_PRIMARY` | None | Fernet key for the encrypted columns. Required in production. [`HIPAA_POSTURE.md`](HIPAA_POSTURE.md) has the generation and rotation steps |
| `DEIDENTIFICATION_HMAC_KEY` | None | Key for the pseudonyms in a de-identified extract. At least 32 characters. Extraction refuses to run without it |
| `DATA_DELIVERY_PATH` | `/data/deliveries` | Where delivered files are stored |
| `AUTO_APPROVE_FOR_DEV` | `false` | `true` skips every approval gate. Refused in production |
| `VIEWDEF_RUNNER` | `hybrid` | Analytics runner: `hybrid`, `postgres`, `materialized`, or `in_memory` |
| `ENABLE_QUERY_CACHE` | `true` | In-memory query cache for the analytics API |
| `CACHE_TTL_SECONDS` | `300` | Lifetime of a cached query |

The LangSmith libraries read `LANGCHAIN_TRACING_V2`, `LANGCHAIN_API_KEY`, and `LANGCHAIN_PROJECT`. Tracing is optional. The Cost Telemetry tab in the admin dashboard needs it.

`config/.env.example` also sets `USE_LANGGRAPH_WORKFLOW`, `LANGGRAPH_ROLLOUT_PCT`, and `MAX_DOWNLOAD_SIZE_MB`, which no code under `app/` reads.

## Tests and checks

```bash
pytest -xvs                                    # default run
pytest --cov=app --cov-report=html             # with coverage
pytest tests/test_speed_layer_runner.py        # speed layer
pytest tests/test_hybrid_runner_speed_integration.py
pre-commit run --all-files
bandit -r app/
```

- `pytest.ini` leaves `tests/e2e`, `tests/integration`, `scripts`, and six named test files out of the default run.
- CI's base job runs `pytest tests/ -m "not requires_services and not requires_api_key"`. A second job starts the Compose services for the `requires_services` tests.
- `tests/eval/test_eval_replay.py` replays the recorded exploratory SQL against HAPI without an API key. [`tests/eval/README.md`](../tests/eval/README.md) explains what a green run does and does not show.

For development, install the pinned tools and the hooks.

```bash
uv pip install -c config/requirements.lock -r config/requirements-dev.lock
pre-commit install
black app/
flake8 app/
mypy app/
```

## Common errors

| Symptom | Cause and fix |
|---|---|
| `ModuleNotFoundError` | The environment is out of sync. Run `uv pip sync config/requirements.lock` with `.venv` active |
| `make run` cannot find `uvicorn` | The Makefile calls a bare `uvicorn`. Activate `.venv` first |
| Port already in use | Stop the old process: `lsof -ti:8000 \| xargs kill -9` |
| A variable from `.env` is missing | Confirm that `.env` is in the repo root, then run the first check below |
| LangSmith traces do not appear | Run the second check below. Uploads are asynchronous, so wait 5 to 10 seconds and refresh |
| The API returns 401 | The request has no bearer token. See [Authentication](#authentication) |
| A PHI route returns 503 | The audit Redis on port 6380 is down, or `REDIS_AUDIT_URL` is unset |
| A dashboard shows old numbers after a code change | Streamlit keeps imported modules in memory. Restart the Streamlit process |
| `create-all` fails with a `postgresql+asyncpg` URL | [#390](https://github.com/jagnyesh/researchflow/issues/390) |

These checks print only whether each secret is set. They never print the value.

```bash
python -c "import os; from dotenv import load_dotenv; load_dotenv(); print('ANTHROPIC_API_KEY set:', bool(os.getenv('ANTHROPIC_API_KEY')))"

echo "LANGCHAIN_TRACING_V2=$LANGCHAIN_TRACING_V2"                     # expect: true
[ -n "$LANGCHAIN_API_KEY" ] && echo "LANGCHAIN_API_KEY is set" || echo "LANGCHAIN_API_KEY is not set"
```

[`operations/stuck-request-recovery.md`](operations/stuck-request-recovery.md) covers a request that is stuck at a gate.
