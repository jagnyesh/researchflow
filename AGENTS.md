# Repository Guidelines

## Project Structure & Module Organization
The application code lives under `app/`, with domain logic in `agents/`, `services/`, and `orchestrator/`, FastAPI routers in `api/`, integrations in `adapters/` and `clients/`, and shared utilities in `utils/`. Web UI experiments sit in `app/web_ui/`; data connectors and SQL-on-FHIR helpers are in `app/sql_on_fhir/`. Tests live in `tests/` (async workflows, adapters, persistence), while `scripts/` contains reproducible research and QA helpers. Reference diagrams are in `diagrams/`, and long-form documentation lives in `docs/`.

## Build, Test, and Development Commands
Create a virtualenv and install dependencies with `pip install -r config/requirements.txt`. Run the API locally using `make run` (wraps `uvicorn app.main:app --reload --port 8000`). Spin up the full stack, including backing services, via `make docker-up`. Execute the fast feedback suite with `make test` or `pytest -q`. Use `pytest tests/test_sql_on_fhir_integration.py` for focused debugging of database flows.

## Coding Style & Naming Conventions
Use 4-space indentation, type hints, and Google-style docstrings. Format code with `black app tests` (line length 100) and lint with `flake8 app tests` before committing. Modules and files follow snake_case, classes use PascalCase, and async call sites should be explicit (`await`/`async def`). Keep configuration secrets out of the repo; prefer environment variables consumed via `python-dotenv`.

## Testing Guidelines
Prefer pytest fixtures and async markers from `pytest-asyncio` when exercising agents or orchestrators. Place new tests beside existing coverage modules (e.g., `tests/test_text2sql.py`). Maintain the 80% coverage floor; run `pytest --cov=app --cov-report=term-missing` before opening a PR. Include regression tests for bug fixes and document any skipped scenarios with a rationale.

## Commit & Pull Request Guidelines
Write commits using conventional commit prefixes (e.g., `feat(agents): add patient cohort planner`); squash noisy commits locally. Branch from `develop` and open PRs back into `develop`, linking issues and summarizing behavior changes. Every PR must show green test runs, include relevant documentation or diagram updates, and update `CHANGELOG.md`. Provide screenshots or sample payloads whenever API or UI behavior changes.
