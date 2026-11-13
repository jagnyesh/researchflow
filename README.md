# ResearchFlow

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11 | 3.12](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg)](https://www.python.org/downloads/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

**LLM-assisted clinical research data requests with human approval gates**

ResearchFlow is a proof of concept that turns a researcher's plain-English request for clinical data into checked SQL. In the exploratory portal, a validator checks each count query. In the formal portal, a human reviewer approves the cohort SQL before any patient rows are extracted. The data is FHIR (Fast Healthcare Interoperability Resources), the HL7 standard format for clinical records. An LLM extracts structured requirements from the request. In the exploratory portal it also writes count-only SQL and classifies ambiguous chat messages.

In the Sprint 6.7 evaluation, the exploratory portal matched a hand-written oracle count on 23 of 23 scored questions. None of 8 adversarial prompts returned row-level data. The rule-based path that it replaced scored 3 of 23, a figure with two confounds that [`tests/eval/README.md`](tests/eval/README.md) names. The median cost was $0.003586 per query.

Every number comes from one developer's corpus of synthetic patients, generated with the open-source tool Synthea. No real patient, researcher, or request has touched the system. The architecture decision records (ADRs) under [`docs/decisions/`](docs/decisions/INDEX.md) hold the evidence for each number.

## Why this project exists

I spent two years supporting clinical research at an academic medical center. A data request took two to four weeks. In my observation, most of that wait was coordination between researchers, administrators, and informaticians, the clinical data specialists who write the queries. Little of it was technical work.

ResearchFlow tests one hypothesis. Software can carry a request from intake to delivery and stop only where an expert must decide. The project has not measured turnaround time, so the speed-up is still a hypothesis.

## Quick start

You need Python 3.11 or 3.12, Docker with Compose, [uv](https://docs.astral.sh/uv/), and an [Anthropic API key](https://console.anthropic.com/).

```bash
git clone https://github.com/jagnyesh/researchflow.git
cd researchflow
python3 -m venv .venv && source .venv/bin/activate
uv pip sync config/requirements.lock
cp config/.env.example .env            # then set ANTHROPIC_API_KEY in .env

docker compose -f config/docker-compose.yml up -d hapi-db hapi-fhir redis redis-audit
./scripts/seed.sh                      # load the 5-patient test fixture
python scripts/materialize_views.py    # build the 7 sqlonfhir views

streamlit run app/web_ui/research_notebook.py --server.port 8501
```

The Compose command starts HAPI FHIR, an open-source FHIR server, with its Postgres database and two Redis instances. Open <http://localhost:8501> and ask how many patients are available. The portal shows a count, the SQL behind the count, and the time of the last view refresh.

`config/.env.example` turns on LangSmith tracing with a placeholder key. Set `LANGCHAIN_TRACING_V2=false`, or set `LANGCHAIN_API_KEY`.

```bash
# One terminal for each service
streamlit run app/web_ui/researcher_portal.py --server.port 8502   # http://localhost:8502
streamlit run app/web_ui/admin_dashboard.py --server.port 8503     # http://localhost:8503
make run                                                           # API on port 8000
```

Start Streamlit from the repo root. `.streamlit/config.toml` pins the dashboards to `127.0.0.1` only for a launch from that directory. A formal request also needs `DEIDENTIFICATION_HMAC_KEY` in `.env`.

## How a request flows

ResearchFlow has two entry points, and the LLM does a different job in each. [`CONTEXT.md`](CONTEXT.md) is the project glossary.

### Exploratory portal: the LLM writes count-only SQL, and code checks it

The exploratory portal is a chat on port 8501. A typical question is "How many diabetes patients do we have?"

1. `ConversationManager` classifies the message with patterns. An ambiguous message costs one LLM call.
2. `SQLSynthesizer` makes one LLM call that returns SQL and an explanation.
3. `SQLValidator` applies 8 default-deny rules. The SQL must be one `SELECT` over the `sqlonfhir` views, and it can return only aggregates and non-identifying dimensions.
4. After a rejection, the portal retries once with the violations. After a second rejection, it shows an error card and no number.
5. The SQL runs as `rf_readonly`, a Postgres role that can only `SELECT` from the `sqlonfhir` schema.

No human reviews this SQL. The validator and the read-only role are the protection.

### Formal portal: rules write the SQL, and a reviewer approves it

The formal portal is a form on port 8502 for an approved study. A typical request is "Extract full dataset for IRB-2025-001". A fixed LangGraph graph of 16 nodes runs five workflow steps. The code calls each step an agent, because each one subclasses `BaseAgent` in `app/agents/`. Only the first step calls an LLM. The other four make no LLM call.

1. `RequirementsAgent` calls the LLM to turn the request into structured criteria.
2. `PhenotypeValidationAgent` builds parameterized SQL with the rule-based `SQLGenerator`. It then counts the cohort, the set of patients who match the criteria.
3. The graph pauses at `phenotype_review`. A reviewer approves, modifies, or rejects the SQL in the admin dashboard.
4. `DataExtractionAgent` extracts a 10-row preview for each data element, and `QualityAssuranceAgent` compares the cohort size with the estimate. The graph pauses at `preview_qa_review` only if that check fails.
5. `DataExtractionAgent` runs the full extraction, de-identified by default, and `QualityAssuranceAgent` checks the result.
6. The graph pauses at `qa_review`. A reviewer approves delivery.
7. `DeliveryAgent` packages the files and writes the citation from a template.

The workflow extracts no patient rows until a reviewer approves the SQL at step 3. The count at step 2 runs before that review, so the reviewer sees the cohort size. Routing and status tracking are graph code, not AI. [Architecture](docs/ARCHITECTURE.md#approval-gates) has the gate table.

## Limits

- **Synthetic data only.** The exploratory evaluation ran on a local Synthea corpus of 380 patients. Do not use ResearchFlow with real patient data.
- **A small evaluation.** The model answered 7 of the 8 adversarial prompts with a safe count, and the validator rejected 1 ([ADR 0031](docs/decisions/0031-sprint-6-7-adversarial-gate-attribution.md)). The result depends on the model as well as the validator.
- **The formal SQL generator passes 5 of its 10 gold cases** ([ADR 0035](docs/decisions/0035-formal-age-cohorts-living-only.md)). It cannot yet express an inclusive age bound, a medication exclusion, a lab value threshold, or a time period.
- **The dashboards have no authentication** ([#39](https://github.com/jagnyesh/researchflow/issues/39)). Anyone who reaches port 8503 can approve a request. A launch from outside the repo root skips the loopback pin ([#219](https://github.com/jagnyesh/researchflow/issues/219)).
- **The API has open authorization gaps.** The approval route has no role check ([#248](https://github.com/jagnyesh/researchflow/issues/248)).
- **Cost numbers assume bursty traffic.** The formal run sent 30 requests in 6 to 7 minutes, and the exploratory run sent 30 queries in 120 seconds. No request waited past Anthropic's 5-minute cache lifetime. The exploratory cache hit rate was 95% ([ADR 0028](docs/decisions/0028-sprint-6-7-exploratory-llm-sql-synthesis.md)).
- **The data layer reads HAPI FHIR's internal Postgres tables.** Another FHIR server, or a HAPI release with a new storage layout, breaks it.

[Architecture](docs/ARCHITECTURE.md#known-gaps) lists the remaining gaps.

## Docs

- [Architecture](docs/ARCHITECTURE.md): the workflow graph, the approval gates, the data layers, and the `HybridRunner` wiring statement.
- [API and configuration](docs/API_AND_CONFIGURATION.md): endpoints, example calls, environment variables, tests, and fixes for common errors.
- [Project history](docs/PROJECT_HISTORY.md): the four engineering arcs, what the Sprint 8 series taught, and the shipped log.
- [`CONTEXT.md`](CONTEXT.md): the current state and the glossary.
- [`BACKLOG.md`](BACKLOG.md): the forward plan and its decision gates.
- [ADR index](docs/decisions/INDEX.md): every decision, by date and by topic.
- [HIPAA posture](docs/HIPAA_POSTURE.md): the Sprint 6.1 security controls, one section for each phase.
- [Docs index](docs/README.md): the older guides. They predate Sprint 7.2 and disagree with the code in places.

## Contributing

[`CONTRIBUTING.md`](CONTRIBUTING.md) has the guidelines. For questions and bugs, use [GitHub Issues](https://github.com/jagnyesh/researchflow/issues).

## License

MIT. See [`LICENSE`](LICENSE).
