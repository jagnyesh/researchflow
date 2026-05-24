# ResearchFlow

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-green.svg)](https://fastapi.tiangolo.com/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

**Multi-Agent AI System for Clinical Research Automation**

ResearchFlow is a proof-of-concept testing whether AI can replace the administrative middle layer in academic clinical research data requests. After 2 years supporting clinical research at an academic medical center, I observed a consistent structural pattern: the people with the tacit knowledge to do the technical work — informaticians, data engineers, biostatisticians — are typically separated from researchers by administrative gatekeepers who don't share that expertise. The result is 2-4 week turnaround times where most of the wait is coordination latency, not technical work.

ResearchFlow tests whether AI agents can absorb the administrative coordination (scheduling, routing, status tracking, requirements gathering) while routing technical decisions (SQL generation, phenotype validation, data quality) directly to the human experts who can make them. The architecture reflects this hypothesis: 4 human-in-loop gates for technical decisions, fully autonomous multi-agent orchestration for everything administrative.

> Active development project. See [Known Limitations](#known-limitations) for what's not production-ready and [What's Not Done Yet](#whats-not-done-yet) for the documented gaps between this proof-of-concept and a real deployment.

---

## What's distinctive about this project

The project's first 5 sprints built the **Foundation**: prototyped the Requirements Agent, validated LangGraph as a 15-state workflow, benchmarked it against the custom A2A FSM (3-55× faster), and made the MIGRATE decision (Sprints 0-4). Sprint 5 instrumented all 6 agents with `@traceable` for LangSmith observability — the substrate every subsequent sprint depended on. The four engineering arcs below build on that foundation.

1. **Lambda Architecture for Clinical Data** (Sprints 4.5 → 5.5 → 6.2 → 6.3 → 6.4 → 6.5, six sprints) — built batch + speed + serving stack against real FHIR data, starting with the original batch layer (10-100× speedup, Sprint 4.5), adding the Redis speed layer (Sprint 5.5, 29/29 tests), then a 7-cycle TDD transpiler-correctness arc that fixed 15 bugs (Sprint 6.2), grilled the right engine through a spike that produced a verdict revision (Sprint 6.3, GO sqlonfhir over Pathling), shipped the engine swap for 3 zero-row MVs (Sprint 6.4), and closed with three-mode freshness routing — EXPLORATORY / FORMAL_DRAFT / FORMAL_EXTRACTION (Sprint 6.5).

2. **A2A → LangGraph Migration** (Sprints 1 → 2 → 3 → 4 → 7 → 7.2, six sprints) — prototyped the Requirements Agent in LangChain (Sprint 1), validated the StateGraph pattern with a simple workflow (Sprint 2), built the full 15-state workflow (Sprint 3), benchmarked against the custom A2A FSM and made the MIGRATE decision (Sprint 4, 3-55× faster, 71/71 tests), completed LangGraph integration in production (Sprint 7, singleton checkpointer + `@traceable` on all 6 agents), then retired 1,324 LOC of the legacy A2A orchestrator behind a parity-verification harness (Sprint 7.2, ~-3,200 LOC net). The parity gate's "FAILED" verdict initially looked like real divergence; diagnostic checks revealed it was measuring non-executed workflows — the meta-pattern documented in [ADR 0000](docs/decisions/0000-meta-recurring-workflow-pattern.md).

3. **LLM Cost Telemetry — Falsification + Repair** (Sprints 8 → 8.1 → 8.2 → 8.4 → 8.3, five sprints) — projected 73% cost reduction (Sprint 8), measured 0% reduction (Sprint 8.1), diagnosed three concurrent bugs (Sprint 8.2) including a 6-month silent langchain-anthropic bug where `cache_control` was silently dropped for plain-string SystemMessage content, then fixed the cost-aggregator's 2.95× double-charge (Sprint 8.4) and re-derived ceilings against measured medians (Sprint 8.3). Each bug fixed in its own sprint with wire-level integration tests.

4. **Security Baseline** (Sprints 6 → 6.1, two sprints) — started with 30 SQL-injection vulnerability fixes (Sprint 6, Nov 2025: parameterized SQL via SQLAlchemy `text()` across all 6 agents + the FHIR query builders), then a five-phase HIPAA compliance baseline shipped in 8 days (Sprint 6.1, May 2026): JWT auth + RBAC, audit middleware with Redis-backed durable queue, PHI-safe input validation framework, TLS enforcement with HSTS, ePHI encryption-at-rest via Fernet. 74 audit tests + 163 input-validation schema tests across Phases 2.2/2.3 alone.

Detailed long-form write-ups for each arc — covering the problem, the design decisions including bad guesses and corrections, empirical evidence, and residual work — are queued as separate deliverables in the project plan.

---

## Architecture Overview

![ResearchFlow Architecture](docs/images/architecture-overview.png)

ResearchFlow's architecture spans 8 layers: UI (3 Streamlit ports) → API (FastAPI) → Orchestration (LangGraph) → Agents (6 specialized) → Core Services → Infrastructure (Lambda Architecture) → Data → External integrations.

[View interactive architecture diagram →](https://jagnyesh.github.io/researchflow/architecture.html)

For the empirically-derived per-layer breakdown of what's documented vs what's actually wired, see [`docs/architecture/05-24architecturereview.md`](docs/architecture/05-24architecturereview.md). The earlier [05-15 snapshot](docs/architecture/05-15architecturereview.md) is retained for historical chronology.

---

## Table of Contents

- [What's distinctive about this project](#whats-distinctive-about-this-project)
- [Architecture Overview](#architecture-overview)
- [Architecture](#architecture)
- [Key Features](#key-features)
- [Quick Start](#quick-start)
- [Performance](#performance)
- [Human-in-Loop Safety](#human-in-loop-safety)
- [Current Status](#current-status)
- [Known Limitations](#known-limitations)
- [What's Not Done Yet](#whats-not-done-yet)
- [Documentation](#documentation)

---

## Architecture

### Lambda Architecture (3 Layers)

ResearchFlow implements a **Lambda Architecture** for FHIR analytics as a learning exercise:

```
┌─────────────────────────────────────────────────────────────┐
│                    FHIR DATA SOURCE                         │
│               HAPI FHIR Server (PostgreSQL)                 │
│   375 patients, 14,841 conditions (Synthea FHIR R4)         │
└────────────────┬──────────────────┬─────────────────────────┘
                 │                  │
        Batch Ingestion      Real-time Updates
      (materialize_views)    (Redis caching)

                 │                  │
                 ↓                  ↓
┌─────────────────────────┐  ┌──────────────────────────────┐
│   BATCH LAYER           │  │   SPEED LAYER                │
│ MaterializedViewRunner  │  │  SpeedLayerRunner            │
├─────────────────────────┤  ├──────────────────────────────┤
│ • Materialized views    │  │ • Redis cache (24hr TTL)     │
│ • 5-15ms performance    │  │ • <1 minute latency          │
│ • Historical data       │  │ • Recent updates             │
│ • Manual/Cron refresh   │  │ • Real-time access           │
└───────────┬─────────────┘  └──────────┬───────────────────┘
            │                           │
            └──────────┬────────────────┘
                       ↓
         ┌─────────────────────────────────────────┐
         │   SERVING LAYER                         │
         │  HybridRunner (FreshnessAnnotation)     │
         ├─────────────────────────────────────────┤
         │ • EXPLORATORY    → batch + speed merge  │
         │ • FORMAL_DRAFT   → batch + speed merge  │
         │                    + batch_anchor_ts    │
         │ • FORMAL_EXTRACTION → batch-only        │
         │                       (citable, no merge)│
         │ • Dedup (speed wins) on merged modes    │
         │ • View existence caching                │
         └─────────────────────────────────────────┘
```

> ⚠️ **Architecture-vs-actual gap (partially closed):** Sprint 6.5 wired `phenotype_agent` through `HybridRunner` with three-mode freshness routing (EXPLORATORY / FORMAL_DRAFT / FORMAL_EXTRACTION). `FORMAL_EXTRACTION` deliberately skips the speed-layer merge so the same SQL re-run against the same `batch_anchor_ts` produces a bit-identical row-set (citability contract) — see [ADR 0027](docs/decisions/0027-sprint-6-5-differential-freshness-routing.md). `feasibility_service` and `extraction_agent` still call `SQLonFHIRAdapter` directly because their multi-view JOIN shapes need an API extension that's filed as [Sprint 6.5b candidate (#71)](https://github.com/jagnyesh/researchflow/issues/71). See [`docs/architecture/05-24architecturereview.md`](docs/architecture/05-24architecturereview.md) for the current empirical map.

### Multi-Agent System (6 Specialized Agents)

```
┌───────────────────────────────────────────────────────┐
│                   Orchestrator                        │
│  (LangGraph FSM | 17 nodes | A2A retired Sprint 7.2)  │
└────────────────────┬──────────────────────────────────┘
                     │
     ┌───────────────┼───────────────┐
     │               │               │
     ▼               ▼               ▼
┌──────────┐  ┌────────────┐  ┌────────────┐
│Requirements│ │ Phenotype  │  │  Calendar  │
│   Agent   │─→│   Agent    │─→│   Agent    │
└──────────┘  └────────────┘  └────────────┘
                     │
     ┌───────────────┼───────────────┐
     ▼               ▼               ▼
┌──────────┐  ┌────────────┐  ┌────────────┐
│Extraction│  │     QA     │  │  Delivery  │
│  Agent   │─→│   Agent    │─→│   Agent    │
└──────────┘  └────────────┘  └────────────┘
```

**Division of Labor:**

| Agent | Role | AI-Owned | Human-Validated |
|-------|------|----------|-----------------|
| **Requirements** | Extract structured requirements | Conversation flow | Medical accuracy |
| **Phenotype** | Generate SQL-on-FHIR queries | Query generation | SQL correctness |
| **Calendar** | Schedule stakeholder meetings | Meeting coordination | N/A (automated) |
| **Extraction** | Multi-source data retrieval | Data fetching | Authorization |
| **QA** | Quality validation | Automated checks | Quality approval |
| **Delivery** | Data packaging & distribution | Packaging | Final approval |

---

## Key Features

### 🤖 AI for Coordination, Humans for Expertise

**The Core Pattern:**
- **AI Handles:** Scheduling, routing, status tracking, notifications, workflow orchestration
- **Humans Validate:** SQL queries, phenotype definitions, data quality, computational validity
- **Result:** 95% time savings on proof-of-concept runs against synthetic FHIR data (weeks → hours); 100% expert validation maintained at all 4 HITL gates

### 🛡️ Human-in-Loop Safety Gates

**4 routine gates + 1 escalation terminal.** No SQL query executes without informatician approval. See the [Human-in-Loop Safety](#human-in-loop-safety) section for the per-gate table, criticality ratings, and the safety guarantee.

### 📊 SQL-on-FHIR v2 Implementation

- **ViewDefinitions**: Standards-compliant FHIR analytics
- **Performance**: 10–100× speedup from materialized views; up to ~1100× on the repeated-query cache-hit path
- **Dual Runners**: PostgreSQL (fast) + In-Memory (flexible)
- **Query Optimization**: Automatic SNOMED/LOINC/ICD-10 code resolution

### 🔐 HIPAA Security Baseline (Sprint 6.1)

- **Encryption-at-rest**: Tier 1 ePHI columns (`initial_request`, inclusion/exclusion criteria, phenotype SQL) wrapped in `FernetEngine` — see [`docs/HIPAA_POSTURE.md`](docs/HIPAA_POSTURE.md)
- **Audit logging**: Default-deny Redis-queue audit pipeline; fail-closed on PHI routes
- **TLS enforcement**: 308 redirects + HSTS (1-year, includeSubDomains) gated by `ENVIRONMENT=production`
- **Input validation**: `PHIInputModel` base + typed primitives across 12 Tier 1 PHI/credential routers; PHI-safe 422 error responses
- **JWT auth + RBAC**: Split human/agent auth (researcher vs service tokens); admin gates on mutating analytics routes

### 💡 LLM Cost Discipline

The dominant cost lever turned out to be **caching architecture + scope discipline**, not provider switching. The actual story (corrected post-Sprint-8 series):

- **Scope:** 5 of 6 agents are procedural (no LLM). Only the **Requirements Agent** invokes LLMs — Sonnet for cohort-spec extraction (`extract_requirements`), Haiku for medical-concept extraction (`extract_medical_concepts`).
- **Caching sized to threshold:** Sonnet system prompts ~3,000 tokens, Haiku ~5,185 tokens — deliberately above Anthropic's prompt-caching thresholds (1,024 / 4,096). System prompts are byte-stable across calls.
- **Wire-level discipline:** caught a 6-month silent `langchain-anthropic` bug where `cache_control` was dropped for plain-string SystemMessage content — see [Engineering discipline](#engineering-discipline--what-the-sprint-8-series-taught) below for the lessons-distilled version.
- **Measured outcome:** 94.88% Sonnet hit rate / 100% Haiku hit rate after warmup. Median formal-portal cost: **$0.008 per request** ([ADR 0025](docs/decisions/0025-sprint-8-3-cost-ceilings-re-derived.md)).
- **`MultiLLMClient` exists** as fallback infrastructure (Anthropic primary; OpenAI/Ollama for non-critical paths) but provider routing is **not** the primary cost driver. Multi-provider routing was the original Sprint 8 hypothesis; Sprint 8.1–8.3 measurement falsified that framing.
- **LangSmith observability:** `@traceable` on all 6 agents + `MultiLLMClient.complete`; per-portal tagging (`portal:formal`, `portal:exploratory`) drives Cost Telemetry Service aggregation.

### 📱 Two Researcher Interfaces

**1. Exploratory Analytics Portal** (http://localhost:8501)
- Chat-based natural language queries
- Instant feasibility checks (no approvals for counts)
- Cohort size estimates in seconds
- Use case: "How many diabetes patients do we have?"

**2. Formal Request Portal** (http://localhost:8502)
- Form-based IRB-approved data requests
- Full approval workflow with human gates
- Multi-agent orchestration (6 agents)
- Use case: "Extract full dataset for IRB-2025-001"

---

## Quick Start

### Prerequisites

- **Python 3.9+**
- **Docker** + **docker-compose** — required for HAPI FHIR server (port 8080) and HAPI's internal Postgres (port 5433); `make docker-up` brings up the stack
- **Redis 6+** — speed layer + Sprint 6.1 audit pipeline queue; install via Homebrew (`brew install redis`) or run in Docker
- **Anthropic API key** ([get key](https://console.anthropic.com/)) — required for the Requirements Agent's LLM calls
- **LangSmith API key** (optional but recommended) — `LANGCHAIN_API_KEY` env var enables the Cost Telemetry dashboard and `@traceable` observability
- **`ENCRYPTION_KEY_PRIMARY`** env var — required at startup when `ENVIRONMENT=production` (Sprint 6.1 Phase 3b fail-closed gate); see [`docs/HIPAA_POSTURE.md`](docs/HIPAA_POSTURE.md) for the Fernet key generation procedure
- **PostgreSQL** (optional for the application schema; SQLite works for dev. HAPI's Postgres at :5433 is separate and required.)

### Installation (3 Steps)

```bash
# 1. Clone and setup environment
git clone https://github.com/jagnyesh/researchflow.git
cd researchflow
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r config/requirements.txt

# 3. Configure API key
cp config/.env.example .env
# Edit .env and add: ANTHROPIC_API_KEY=sk-ant-api03-...
```

### Run Services

```bash
# Terminal 1: API Server
uvicorn app.main:app --reload --port 8000

# Terminal 2: Exploratory Analytics (Chat)
streamlit run app/web_ui/research_notebook.py --server.port 8501

# Terminal 3: Formal Request Portal (Forms)
streamlit run app/web_ui/researcher_portal.py --server.port 8502

# Terminal 4: Admin Dashboard (Approvals)
streamlit run app/web_ui/admin_dashboard.py --server.port 8503
```

### Access Points

| Service | URL | Purpose |
|---------|-----|---------|
| **Exploratory Analytics** | http://localhost:8501 | Chat-based feasibility checks |
| **Formal Request Portal** | http://localhost:8502 | IRB-approved data extractions |
| **Admin Dashboard** | http://localhost:8503 | Review approvals, monitor system |
| **API Server** | http://localhost:8000 | REST API endpoints |
| **API Docs** | http://localhost:8000/docs | Interactive Swagger UI |

---

## Performance

### Experimental Benchmarks

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Repeated Query Execution | 116.2s | 0.101s | ~1100× faster (cache-hit path; first-run queries see the 10-100× materialized-view speedup, not this number) |
| Workflow Turnaround | 2–3 weeks | 4–8 hours | **~95% faster** (proof-of-concept) |
| Per-request LLM cost (formal portal) | — | **$0.008 measured** | Sprint 8.3 median, n=30 bursty traffic |
| Anthropic prompt cache hit (Sonnet, after warmup) | 0% | **94.88%** | Sprint 8.2 wire-fix + Sprint 8.3 measurement |
| Anthropic prompt cache hit (Haiku, after warmup) | 0% | **100%** | post Sprint 8.2 prompt bulk-up |

### Lambda Architecture Performance

| Layer | Metric | Performance |
|-------|--------|-------------|
| **Batch** | Materialized view query | 5–15 ms |
| **Speed** | Real-time data latency | <1 minute |
| **Serving** | Materialized views vs live FHIR REST | **10–100× faster** (typical) |
| **Serving** | Repeated-query cache-hit path | **~1100× faster** (benchmark) |

**Caveats** (be aware before citing):
- The turnaround number is from proof-of-concept runs against Synthea-generated FHIR data, not from field measurement at scale with real research requests.
- The `$0.008` per-request cost is measured under **bursty traffic** (30 requests within Anthropic's 5-minute cache TTL via [`scripts/drive_qa_traffic.py`](scripts/drive_qa_traffic.py)). Sparse-traffic measurement (gaps > 5 min between requests) is filed as Sprint 8.5 candidate — sparse traffic would shift the median toward cache-create cost.
- The `1100×` is specifically the cache-hit path on a repeated query; first-run cohort queries see the 10–100× materialized-view speedup.

### Engineering discipline — what the Sprint 8 series taught

The Sprint 8 series (8.1–8.4, 2026-05-12 through 2026-05-14) was the project's most productive sprint for engineering rigor, even though no new features shipped. Three lessons:

1. **Wire-level tests, not wrapper tests.** A 6-month silent bug in `langchain-anthropic 1.0.1` was silently dropping `cache_control` markers for plain-string `SystemMessage` content. The existing tests asserted against the LangChain input shape and passed every CI run while the wrapper transmitted the wrong payload to Anthropic. Fix shipped in PR #45 with a `tests/test_prompt_optimization.py::TestPromptCachingWireLevel` integration test that mocks `anthropic.AsyncMessages.create` and asserts `cache_control` arrives in the outbound payload. ([ADR 0021](docs/decisions/0021-sprint-8-2-prompt-caching-bug.md))

2. **Manual math beats the aggregator.** The `CostTelemetryService` aggregator was over-counting per-request cost by 2.95× because LangSmith's `Run.input_tokens` already includes `cache_read_input_tokens`, but the formula was double-billing the cache-read portion. Caught by walking the LangSmith trace tree by hand and comparing against aggregator output (manual $0.007754 vs aggregator $0.022865). Sprint 8.4 shipped the one-line fix + a fixture test against real production trace data. ([ADR 0023](docs/decisions/0023-sprint-8-4-aggregator-cache-read-double-charge.md))

3. **Pre-commits defend against bias, not against information.** Sprint 6.3's spike applied a 4-criterion strict-gate framework to engine candidates and reached "GO Pathling" by literal rule-application. User-directed re-examination revealed the gate's premise (3/3 row-count match against HAPI oracle) was broken by an engine-independent view-def bug. Patching the view-def re-ran the gate at 3/3, and the override fired — verdict revised to "GO sqlonfhir" same-day. The pattern: rules should be updated when new information reveals their premise was based on wrong assumptions, not blindly enforced. ([ADR 0020](docs/decisions/0020-sprint-6-3-verdict-revision-go-sqlonfhir.md))

---

## Human-in-Loop Safety

### Critical Approval Gates

| Approval Type | Reviewer | Timeout | Purpose | Criticality |
|---------------|----------|---------|---------|-------------|
| **SQL Review** | Informatician | 24h | **Approve before execution** | 🚨 CRITICAL |
| Requirements | Informatician | 24h | Validate medical accuracy | High |
| Extraction | Admin | 12h | Authorize data access | High |
| QA Review | Informatician | 24h | Validate quality | High |
| Scope Change | Coordinator | 48h | Evaluate modifications | Medium |

### Safety Guarantee

**No SQL query executes without informatician approval.** Every query goes through:
1. Generated by Phenotype Agent (AI)
2. Submitted for human review
3. Approved/modified/rejected by informatician (Human)
4. Logged in complete audit trail
5. Only then executed against FHIR data

**LangSmith Observability Proof:** Traces show exactly which tasks AI completed autonomously (scheduling, routing, notifications) versus which required human validation (SQL queries, cohort definitions, data quality).

---

## API Documentation

### Quick Examples

#### Submit Research Request
```python
import requests

response = requests.post(
    "http://localhost:8000/research/submit",
    json={
        "researcher_name": "Dr. Smith",
        "researcher_email": "smith@hospital.org",
        "irb_number": "IRB-2025-001",
        "request": "Female patients over 50 with diabetes in past 2 years"
    }
)
request_id = response.json()["request_id"]
```

#### Approve SQL Query
```python
# Get pending approvals
approvals = requests.get(
    "http://localhost:8000/approvals/pending?approval_type=phenotype_sql"
).json()["approvals"]

# Approve SQL
requests.post(
    f"http://localhost:8000/approvals/{approvals[0]['id']}/respond",
    json={
        "decision": "approve",
        "reviewer": "informatician@hospital.org",
        "notes": "SQL validated against schema"
    }
)
```

#### Execute SQL-on-FHIR Query
```python
# Execute ViewDefinition
response = requests.post(
    "http://localhost:8000/analytics/execute",
    json={
        "view_name": "patient_demographics",
        "search_params": {"gender": "female"},
        "max_resources": 100
    }
)
results = response.json()
print(f"Found {results['total_count']} patients")
```

### Core Endpoints

```
# Workflow Management
POST   /research/submit           Submit research request
GET    /research/{request_id}     Get request status
GET    /research/active           List active requests

# Approval Workflow
GET    /approvals/pending         Get pending approvals
POST   /approvals/{id}/respond    Approve/reject/modify
POST   /approvals/scope-change    Request scope change

# SQL-on-FHIR Analytics
POST   /analytics/execute         Execute ViewDefinition
GET    /analytics/view-definitions List available views
GET    /analytics/schema/{name}   Get view schema

# Health & Monitoring
GET    /health                    System health check
GET    /health/metrics            System metrics
```

Complete API documentation: **http://localhost:8000/docs** (Swagger UI)

---

## Configuration

### Environment Variables

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-api03-your-key-here

# Optional: Multi-Provider LLM fallback (not the primary cost lever — see "LLM Cost Discipline" section above)
SECONDARY_LLM_PROVIDER=openai  # or ollama
OPENAI_API_KEY=sk-your-openai-key
OLLAMA_BASE_URL=http://localhost:11434
ENABLE_LLM_FALLBACK=true

# Database (SQLite for dev, PostgreSQL for production)
DATABASE_URL=sqlite+aiosqlite:///./dev.db
# Or: postgresql+asyncpg://user:pass@localhost/dbname

# LangSmith Observability
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_pt_your-key
LANGCHAIN_PROJECT=researchflow-production

# Performance
ENABLE_QUERY_CACHE=true
CACHE_TTL_SECONDS=300
MAX_CACHE_SIZE=1000
USE_SPEED_LAYER=true  # Enable Lambda Architecture speed layer

# Approval Timeouts (hours)
APPROVAL_TIMEOUT_SQL=24
APPROVAL_TIMEOUT_REQUIREMENTS=24
APPROVAL_TIMEOUT_EXTRACTION=12
```

See `config/.env.example` for complete configuration options.

---

## Testing

### Run Tests

```bash
# All tests
pytest

# With coverage
pytest --cov=app --cov-report=html

# Lambda Architecture tests (29 tests)
pytest tests/test_speed_layer_runner.py
pytest tests/test_hybrid_runner_speed_integration.py

# E2E tests
pytest tests/e2e/
```

### Test Results

- ✅ **29/29 Lambda Architecture tests** passing
- ✅ **85%+ test coverage** across core modules
- ✅ **100% pass rate** on integration tests
- ✅ **E2E workflows** validated with LangSmith tracing

---

## Documentation

### Essential Guides

- 📘 **[Setup Guide](docs/SETUP_GUIDE.md)** - Complete installation instructions
- 🔧 **[Quick Reference](docs/QUICK_REFERENCE.md)** - Common commands and tips
- 🏗️ **[Architecture Overview](docs/RESEARCHFLOW_README.md)** - Complete system design
- 🔬 **[SQL-on-FHIR v2](docs/SQL_ON_FHIR_V2.md)** - ViewDefinition implementation
- ⚡ **[Lambda Architecture](docs/MATERIALIZED_VIEWS_ARCHITECTURE.md)** - Batch + Speed + Serving layers
- 🛡️ **[Approval Workflow](docs/APPROVAL_WORKFLOW_GUIDE.md)** - Human-in-loop safety gates
- 📊 **[LangSmith Observability](docs/LANGSMITH_DASHBOARD_GUIDE.md)** - Workflow tracing & monitoring

### Architecture Analysis

- 🏛️ **[Lambda Architecture Comparison](docs/HealthLakeVsResearchFlowComparison.md)** — Complete implementation analysis
- 🧪 **[Testing Guide](docs/SQL_ON_FHIR_TESTING_GUIDE.md)** — Test data setup and execution

### Design Decisions (ADR log)

- 📜 **[ADR index — `docs/decisions/INDEX.md`](docs/decisions/INDEX.md)** — 27 architectural decision records, append-only, chronological + topic-grouped
- 🗺️ **[Architectural Map — `docs/architecture/05-24architecturereview.md`](docs/architecture/05-24architecturereview.md)** — Empirically-derived 8-section map of the live system (the canonical reference; supersedes the [05-15 snapshot](docs/architecture/05-15architecturereview.md) which is retained for historical chronology)
- 📌 **[`CONTEXT.md`](CONTEXT.md)** — what's true right now (active sprint, in-progress work, blockers)
- 📋 **[`BACKLOG.md`](BACKLOG.md)** — forward plan with decision gates

Notable ADRs:
- [0027 — Sprint 6.5 Lambda differential freshness routing](docs/decisions/0027-sprint-6-5-differential-freshness-routing.md)
- [0024 — Sprint 7.2 A2A FSM closeout](docs/decisions/0024-sprint-7-2-a2a-fsm-closeout.md)
- [0026 — Sprint 6.4 sqlonfhir integration](docs/decisions/0026-sprint-6-4-sqlonfhir-integration.md)
- [0023 — Sprint 8.4 aggregator double-charge fix](docs/decisions/0023-sprint-8-4-aggregator-cache-read-double-charge.md)
- [0021 — Sprint 8.2 the 6-month silent prompt-caching bug](docs/decisions/0021-sprint-8-2-prompt-caching-bug.md)
- [0020 — Sprint 6.3 verdict revision: GO sqlonfhir](docs/decisions/0020-sprint-6-3-verdict-revision-go-sqlonfhir.md)
- [0000 — Recurring workflow pattern (meta)](docs/decisions/0000-meta-recurring-workflow-pattern.md)

### All Documentation

See **[docs/README.md](docs/README.md)** for comprehensive documentation index organized by role:
- 👩‍🔬 **For Researchers** - Notebook guides, API examples
- 💻 **For Developers** - Architecture, implementation details
- ⚙️ **For DevOps** - Setup, monitoring, maintenance
- 🏗️ **For Architects** - Design decisions, performance analysis

---

## Current Status

### Development Metrics

| Metric | Value |
|--------|-------|
| **Lines of Code** | ~36,000 (application code under `app/`) |
| **AI Agents** | 6 specialized agents (1 LLM-using, 5 procedural) |
| **Database Tables** | 10 tables |
| **Workflow Nodes** | 17 nodes (LangGraph FSM) |
| **API Endpoints** | 25+ REST endpoints |
| **Test Files** | 88 test files |
| **Documentation** | 150+ markdown files, including 27 ADRs in `docs/decisions/` |

### Experimental Achievements

For headline performance numbers (speedup, turnaround, LLM cost) see the [Performance](#performance) section. The shipping milestones:

- 📊 **Lambda Architecture** (Batch + Speed + Serving) shipped — `HybridRunner` is now a production caller via `phenotype_agent` with three-mode `FreshnessAnnotation` routing (Sprint 6.5)
- 🛡️ **Human-in-Loop** — 4 routine HITL gates + 1 escalation terminal wired through LangGraph's `interrupt_after` mechanism

### Roadmap (Phase 2 nearly complete; Phases 3–4 ahead)

**Recently shipped (latest first):**
- ✅ Issue #51 fix (2026-05-18) — `_parse_age_details` range support; LLM's canonical `"between X and Y"` age format now emits SQL `BETWEEN` predicate ([PR #83](https://github.com/jagnyesh/researchflow/pull/83))
- ✅ Sprint 6.5b (2026-05-18) — `extraction_agent.py` dead-code cleanup; removed non-existent-table branches that the Sprint 6.5 honesty patch documented ([PR #81](https://github.com/jagnyesh/researchflow/pull/81), closes #79)
- ✅ Sprint 6.5 (2026-05-17) — Lambda differential freshness routing: `HybridRunner` gets its first production caller (`phenotype_agent`) with three-mode `FreshnessAnnotation` routing ([ADR 0027](docs/decisions/0027-sprint-6-5-differential-freshness-routing.md))
- ✅ Sprint 7.2 (2026-05-17) — A2A FSM retired: `app/orchestrator/` deleted (1,324 LOC); LangGraph is the only orchestrator ([ADR 0024](docs/decisions/0024-sprint-7-2-a2a-fsm-closeout.md))
- ✅ Sprint 6.4 (2026-05-15) — sqlonfhir engine integration for 3 zero-row materialized views ([ADR 0026](docs/decisions/0026-sprint-6-4-sqlonfhir-integration.md))
- ✅ Sprint 8 series (2026-05-12 through 2026-05-14) — cost telemetry verification, prompt-caching wire fix, aggregator double-charge fix, ceiling re-derivation ([ADRs 0018–0025](docs/decisions/INDEX.md))
- ✅ Sprint 6.3 (2026-05-14) — DuckDB-FHIR / sqlonfhir engine spike + verdict revision ([ADRs 0019–0020](docs/decisions/INDEX.md))
- ✅ Sprint 6.2 (2026-05-08) — Lambda Architecture transpiler harness + speed-layer wiring + materialized-views router hardening
- ✅ Sprint 6.1 (2026-05-08) — HIPAA security baseline (audit pipeline, input validation, TLS, encryption-at-rest)
- ✅ Sprint 7 — LangGraph migration finalized (singleton checkpointer + `@traceable` instrumentation on all 6 agents)

**Next (filed candidates):**
- 📅 **Sprint 6.5b expanded** ([#71](https://github.com/jagnyesh/researchflow/issues/71)) — `feasibility_service` + `extraction_agent` multi-view JOIN wiring through `HybridRunner` (needs API extension first)
- 📅 **Sprint 6.5c** ([#82](https://github.com/jagnyesh/researchflow/issues/82)) — defensive fall-through in `_build_demographic_clause` age-first branch (latent, confirmed not firing in stress test)
- 📅 **Sprint 6.6 candidate** — custom-path MV health-check oracles
- 📅 **Sprint 7.3 candidate** ([#65](https://github.com/jagnyesh/researchflow/issues/65)) — port 2 deferred A2A behavioral test files to LangGraph
- 📅 **Sprint 8.5** — sparse-traffic median cost measurement (current numbers are bursty-traffic only)
- 📅 **Sprint 8.6** — exploratory portal prompt caching (currently 0% cache hit rate)

**Phase 2 (clinical intelligence):**
- 📅 Sprint 9 — Temporal Reasoning Engine (clinical time windows: "HbA1c > 7 within 6mo before diabetes dx")
- 📅 Sprint 10 — Complex Cohort Logic (nested AND/OR/NOT, exclusion subqueries, phenotype-as-code)

**Phase 3 (production readiness):**
- 📅 Sprint 11 — Multi-Tenant Architecture (institution-scoped data, per-tenant audit logs)
- 📅 Sprint 12 — Performance Optimization

See [`BACKLOG.md`](BACKLOG.md) for the forward plan and [`docs/decisions/INDEX.md`](docs/decisions/INDEX.md) for the architectural-decision log.

---

## Known Limitations

**This is experimental software. Known limitations include:**

- ✋ **Not production-ready**: Requires security hardening before clinical deployment
- ✋ **Limited testing**: Tested with synthetic data only (Synthea FHIR generator + HAPI FHIR)
- ✋ **Single institution**: Not tested across multiple healthcare systems
- ✋ **Manual refresh**: Materialized views require manual/cron refresh
- ✋ **PII encryption deferred**: Tier 1 ePHI columns are encrypted at rest (Sprint 6.1 Phase 3b, FernetEngine — see [`docs/HIPAA_POSTURE.md`](docs/HIPAA_POSTURE.md)); researcher-PII encryption (`User.email`, `*.researcher_email`) is deferred to Phase 3b.1
- ✋ **Basic authentication**: JWT authentication not yet production-hardened
- ✋ **Streamlit dashboards have no auth** (Phase 3c, [#39](https://github.com/jagnyesh/researchflow/issues/39)): the 3 Streamlit ports (8501, 8502, 8503) bypass FastAPI's audit middleware + RBAC. Localhost bind is the only mitigation today.

**For demonstration and learning purposes only. Do not use with real patient data without proper security review.**

---

## What's Not Done Yet

Most portfolio READMEs hide their gaps. This section enumerates the architecture-vs-documentation gaps surfaced by the live architectural-map review ([`docs/architecture/05-24architecturereview.md`](docs/architecture/05-24architecturereview.md)) — what's known to be incomplete, and which sprint candidate closes it.

| Gap | Detail | Closing sprint |
|---|---|---|
| **HybridRunner partial wiring** | Sprint 6.5 wired `phenotype_agent` through `HybridRunner` with three-mode freshness routing. `feasibility_service` (3 sites) and `extraction_agent._execute_phenotype_query` still call `SQLonFHIRAdapter` directly because their multi-view JOIN shapes need an `execute_sql_with_view_hints` API extension. | **Sprint 6.5b expanded** ([#71](https://github.com/jagnyesh/researchflow/issues/71)) |
| **Streamlit dashboard auth** | 3 Streamlit ports have zero authentication. Anyone reaching the bound port can approve HITL escalations and scrape researcher PII. Today only `localhost` bind protects them. | **Phase 3c** ([#39](https://github.com/jagnyesh/researchflow/issues/39)) |
| **Exploratory portal cache_hit_rate = 0%** | The `QueryInterpreter` system prompt sits below Anthropic's caching threshold and/or doesn't use the content-block-array form that the Sprint 8.2 wire-fix requires for cache_control transmission. Same class of bug as Sprint 8.2's formal-portal prompt issue, not yet applied to QueryInterpreter. | **Sprint 8.6** candidate |
| **Cost telemetry calibrated for bursty traffic only** | The `$0.008/request` measurement and the rolling-30 cost-band gate ceilings are calibrated against 30 requests fired in 6-7 minutes (within Anthropic's 5-minute cache TTL). Sparse real-world traffic with gaps > 5 min would shift the median toward cache-create cost. | **Sprint 8.5** candidate |
| **HAPI FHIR Docker healthcheck broken** | The `docker inspect hapi-fhir-server` healthcheck reports `unhealthy` because the distroless image's healthcheck CMD invokes `/bin/sh`, which doesn't exist in distroless. The container serves traffic correctly (HAPI returns 200 on `/fhir/metadata`); only the healthcheck signal is broken. CI / monitoring would see HAPI as down even when it's up. | Cosmetic — fix when monitoring/CI matters |
| **`sql_generator.py:507` raw `FROM observation o`** | `_build_lab_value_criterion` emits SQL against the raw FHIR `observation` table that doesn't exist in HAPI. Same dead-code class as the Sprint 6.5b cleanup. Phenotypes that include a lab-value criterion would silently produce a 0-patient cohort. Currently masked because no test traffic hits this code path. | **Sprint 6.5b followup** ([#80](https://github.com/jagnyesh/researchflow/issues/80)) |

There's also one **latent bug preserved bug-for-bug** through Sprint 7.2's A2A retirement (will be fixed in a future sprint):
- **`research.py` queries `WHERE current_state IN ('delivered', 'complete')`** but LangGraph never writes the `'delivered'` state — terminal is `'complete'` only. LangGraph-completed rows are silently missing from those result sets. Sprint 7.2 preserved this behavior because it was outside the named scope of the migration close-out. Filed as [#53](https://github.com/jagnyesh/researchflow/issues/53).

---

## Troubleshooting

### Common Issues

**Missing Dependencies**
```bash
pip install aiosqlite fastapi uvicorn httpx sqlalchemy anthropic
pip install langchain langchain-anthropic langgraph langsmith
```

**Port Already in Use**
```bash
lsof -ti:8000 | xargs kill -9  # Kill process on port 8000
```

**Environment Variables Not Loading**
```bash
# Verify .env file exists
ls -la .env

# Test environment loading
python -c "import os; from dotenv import load_dotenv; load_dotenv(); print(os.getenv('ANTHROPIC_API_KEY'))"
```

**LangSmith Traces Not Appearing**
```bash
# Verify environment variables
echo $LANGCHAIN_TRACING_V2  # Should be "true"
echo $LANGCHAIN_API_KEY     # Should start with "lsv2_pt_"

# Wait 5-10 seconds for async upload, then refresh dashboard
```

For detailed troubleshooting, see **[docs/SETUP_GUIDE.md](docs/SETUP_GUIDE.md)** and **[docs/QUICK_REFERENCE.md](docs/QUICK_REFERENCE.md)**.

---

## Contributing

We welcome contributions! See **[CONTRIBUTING.md](CONTRIBUTING.md)** for guidelines.

### Development Setup

```bash
# Install development dependencies
pip install -r config/requirements-dev.txt

# Install pre-commit hooks
pre-commit install

# Run linters
black app/
flake8 app/
mypy app/
```

---

## License

MIT License - see **[LICENSE](LICENSE)** file for details.

---

## Acknowledgments

- Built with [FastAPI](https://fastapi.tiangolo.com/)
- LLM integration via [Anthropic Claude API](https://www.anthropic.com/)
- Orchestration by [LangGraph](https://github.com/langchain-ai/langgraph)
- Observability by [LangSmith](https://www.langchain.com/langsmith)
- SQL-on-FHIR v2 specification by [HL7 FHIR](https://hl7.org/fhir/)
- UI powered by [Streamlit](https://streamlit.io/)

**Developed with Claude Code using structured pre-implementation grilling discipline. See [ADR 0000](docs/decisions/0000-meta-recurring-workflow-pattern.md) for the documented meta-patterns that emerged across 22 sprints.**

---

For questions, issues, or collaboration requests, please use [GitHub Issues](https://github.com/jagnyesh/researchflow/issues).

**ResearchFlow**: An experiment in AI-human collaboration for clinical research. Built with AI to prove where AI belongs.
