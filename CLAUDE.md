# ResearchFlow

AI-powered multi-agent system that automates clinical research data requests from natural language to delivery. FastAPI + LangGraph + SQL-on-FHIR. Reduces data request turnaround from weeks to hours.

## Living state — read these for current context

- @CONTEXT.md — what is true *right now* (active sprint, in-progress work, blockers)
- @DECISIONS.md — append-only architecture decision log (one entry per sprint)
- @BACKLOG.md — forward plan (upcoming sprints, decision gates)
- @.claude/architecture.rules — naming conventions, agent patterns, no-go zones

Historical sprint reports live in `docs/sprints/archive/`. Don't load them unless explicitly asked.

## Operating discipline: re-examine recommendations when premise may have shifted

Before accepting an agent recommendation as final, ask: "what would have to be
true for this verdict to be wrong?" Read the cons/concerns section of any
recommendation twice as carefully as the pros section — the load-bearing
hand-waved assumption usually lives in the cons.

For diagnostic work: default to empirical confirmation (read the wire, dump
runtime state, inspect actual values) before scoping fixes. Static analysis
is insufficient for bugs at interface boundaries (wrappers, third-party APIs,
async layers, caching). The Sprint 8.2 langchain-anthropic silent transmission
bug and the Sprint 8.4 aggregator double-charge bug both ran for months
specifically because tests asserted at the wrapper layer, not the wire layer.

For verdict decisions: pre-commitments defend against bias, not against
information. When new information reveals a pre-commit's premise was broken,
deliberate override is appropriate when documented. Precedent: Sprint 6.2
Phase 1.5 Q1 refinement; Sprint 6.3 verdict revision GO sqlonfhir.

Full context with 10 documented cases: see DECISIONS.md "Recurring workflow
pattern" section.

## Quick start

```bash
# Setup (one-time)
python3 -m venv .venv && source .venv/bin/activate
uv pip sync config/requirements.lock
cp config/.env.example .env  # add ANTHROPIC_API_KEY, REDIS_URL
pre-commit install

# Daily loop
redis-server &                                                 # speed layer
python scripts/materialize_views.py                            # batch layer (one-time/nightly)
streamlit run app/web_ui/research_notebook.py --server.port 8501   # exploratory UI
streamlit run app/web_ui/researcher_portal.py --server.port 8502   # formal request UI
streamlit run app/web_ui/admin_dashboard.py --server.port 8503     # admin
make run                                                       # API at :8000

# Tests + security
pytest -xvs
pre-commit run --all-files
bandit -r app/
```

Docker: `make docker-up` (postgres + mock FHIR + app).

## Service ports

| Service | Port | File |
|---|---|---|
| Exploratory Analytics (chat) | 8501 | `app/web_ui/research_notebook.py` |
| Formal Request Portal (form) | 8502 | `app/web_ui/researcher_portal.py` |
| Admin Dashboard | 8503 | `app/web_ui/admin_dashboard.py` |
| API | 8000 | `app/main.py` |
| Mock FHIR | 8080 | docker-compose |
| Postgres | 5432 | docker-compose |

## Key directories

- `app/agents/` — 6 specialized agents (Requirements, Phenotype, Calendar, Extraction, QA, Delivery), all `BaseAgent` subclasses
- `app/orchestrator/` — custom A2A orchestrator + 15-state workflow FSM (production)
- `app/langchain_orchestrator/` — LangGraph migration (23-state FSM, behind `USE_LANGGRAPH_WORKFLOW` flag)
- `app/sql_on_fhir/runner/` — Lambda Architecture: `materialized_view_runner.py` (batch) + `speed_layer_runner.py` (Redis) + `hybrid_runner.py` (serving)
- `app/database/models.py` — 6 tables (ResearchRequest, RequirementsData, FeasibilityReport, AgentExecution, Escalation, DataDelivery)
- `app/security/` — JWT auth, RBAC, rate limiting, audit logging (Sprint 6.1 active work)
- `tests/` — pytest with `pytest-asyncio`; subdirs `e2e/`, `integration/`, `security/`

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool. When in doubt, invoke the skill.

Key routing rules:
- Product ideas/brainstorming → invoke /office-hours
- Strategy/scope → invoke /plan-ceo-review
- Architecture → invoke /plan-eng-review
- Design system/plan review → invoke /design-consultation or /plan-design-review
- Full review pipeline → invoke /autoplan
- Bugs/errors → invoke /investigate or /diagnose
- QA/testing site behavior → invoke /qa or /qa-only
- Code review/diff check → invoke /review
- Visual polish → invoke /design-review
- Ship/deploy/PR → invoke /ship or /land-and-deploy
- Save progress → invoke /context-save
- Resume context → invoke /context-restore
- Token-tight responses → invoke /caveman
- Validate plan/doc against reality → invoke /grill-with-docs

## Agent skills

### Issue tracker

Issues live in this repo's GitHub Issues (`jagnyesh/researchflow`). Skills use the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). All five labels exist in the repo. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout. `CONTEXT.md` at the root for domain vocabulary; `DECISIONS.md` at the root for the append-only ADR log (one entry per sprint). See `docs/agents/domain.md`.
