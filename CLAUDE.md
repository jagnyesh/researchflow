# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**ResearchFlow** is an AI-powered multi-agent system that automates clinical research data requests from natural language to delivery. Built on FastAPI with a multi-agent architecture, it reduces data request turnaround from weeks to hours.

### Core Components
- **6 Specialized AI Agents**: Requirements, Phenotype, Calendar, Extraction, QA, Delivery
- **Dual Orchestration**: Custom orchestrator (production) + LangGraph workflow (migration target, 75% complete) 🆕
- **Lambda Architecture**: Batch layer (materialized views) + Speed layer (Redis) + Serving layer (hybrid runner) 🆕
- **Multi-Provider LLM Integration**: Claude API (primary) with optional secondary providers (OpenAI, Ollama) for non-critical tasks
- **SQL-on-FHIR**: Automated phenotype SQL generation and execution (v1 + v2)
- **MCP Infrastructure**: Model Context Protocol servers for external system integration
- **Streamlit UIs**: Researcher Portal and Admin Dashboard
- **LangSmith Observability**: Full workflow tracing and debugging 🆕
- **Security Hardening**: Parameterized SQL, pre-commit hooks, CI/CD security scanning 🆕

## Quick Start

### Local Development (without Docker)
```bash
# Setup
python3 -m venv .venv
source .venv/bin/activate
pip install -r config/requirements.txt

# Add API keys to .env
cp config/.env.example .env
# Edit .env and add:
#   ANTHROPIC_API_KEY=sk-ant-api03-...
#   REDIS_URL=redis://localhost:6379/0  🆕
#   USE_SPEED_LAYER=true                🆕
#   LANGCHAIN_TRACING_V2=true           🆕 (optional)
#   LANGCHAIN_API_KEY=lsv2_pt_...       🆕 (optional)

# Install pre-commit hooks (security) 🆕
pip install pre-commit
pre-commit install

# Start Redis (for Speed Layer) 🆕
redis-server

# Create materialized views (Batch Layer) 🆕
python scripts/materialize_views.py

# Run Researcher Portal
streamlit run app/web_ui/researcher_portal.py --server.port 8501

# Run Admin Dashboard
streamlit run app/web_ui/admin_dashboard.py --server.port 8502

# Run API server
make run
# or: uvicorn app.main:app --reload --port 8000

# Run tests (including Lambda Architecture + LangGraph tests)
make test
# or: pytest -v

# Run security scanning 🆕
pre-commit run --all-files
bandit -r app/
```

### Docker Development
```bash
# Start all services (app + postgres + mock FHIR server)
make docker-up
# or: docker-compose -f config/docker-compose.yml up --build
```

Ports:
- Researcher Portal: http://localhost:8501
- Admin Dashboard: http://localhost:8502
- API Server: http://localhost:8000
- Mock FHIR: http://localhost:8080
- Postgres: 5432

## Project Structure

```
FHIR_PROJECT/
├── app/                          # Application code
│   ├── agents/                   # 6 specialized AI agents
│   │   ├── base_agent.py        # Base class with retry logic, state mgmt
│   │   ├── requirements_agent.py # LLM-powered conversation
│   │   ├── phenotype_agent.py   # SQL generation + feasibility
│   │   ├── calendar_agent.py    # Meeting scheduling
│   │   ├── extraction_agent.py  # Multi-source data retrieval
│   │   ├── qa_agent.py          # Quality validation
│   │   └── delivery_agent.py    # Data packaging + delivery
│   │
│   ├── cache/                    # Redis speed layer 🆕
│   │   ├── redis_client.py      # Redis integration
│   │   └── cache_config.py      # Cache configuration
│   │
│   ├── langchain_orchestrator/   # LangGraph migration 🆕
│   │   ├── langgraph_workflow.py        # 23-state LangGraph FSM
│   │   ├── simple_workflow.py           # 3-state POC
│   │   ├── persistence.py               # AsyncSqliteSaver checkpointer
│   │   ├── agent_adapter.py             # BaseAgent ↔ LangGraph bridge
│   │   ├── approval_bridge.py           # DB approval sync
│   │   ├── request_facade.py            # Orchestrator-compatible API
│   │   ├── langchain_agents.py          # LangChain agent implementations
│   │   └── langchain_base_agent.py      # Base class
│   │
│   ├── orchestrator/             # Custom orchestration (production)
│   │   ├── orchestrator.py      # A2A message routing
│   │   └── workflow_engine.py   # 15-state workflow FSM
│   │
│   ├── sql_on_fhir/              # SQL-on-FHIR v2 (UPDATED) 🆕
│   │   ├── runner/               # Query execution runners
│   │   │   ├── hybrid_runner.py            # Serving layer (batch + speed merge)
│   │   │   ├── materialized_view_runner.py # Batch layer (fast queries)
│   │   │   ├── speed_layer_runner.py       # Speed layer (Redis)
│   │   │   ├── postgres_runner.py          # Legacy (fallback)
│   │   │   └── in_memory_runner.py         # In-memory FHIR queries
│   │   ├── query_builder/        # SQL builder
│   │   ├── transpiler/           # FHIRPath → SQL transpiler
│   │   ├── view_definitions/     # SQL-on-FHIR v2 ViewDefinitions
│   │   └── schema/               # FHIR schema introspection
│   │
│   ├── database/                 # Data models (6 tables)
│   │   └── models.py            # SQLAlchemy models
│   │
│   ├── utils/                    # Utilities
│   │   ├── llm_client.py        # Claude API wrapper (critical tasks)
│   │   ├── multi_llm_client.py  # Multi-provider LLM client (AI Suite)
│   │   └── sql_generator.py     # SQL-on-FHIR generation (parameterized) 🆕
│   │
│   ├── services/                 # Business logic (UPDATED) 🆕
│   │   ├── materialized_view_service.py  # View management
│   │   ├── fhir_subscription_service.py  # Real-time FHIR updates
│   │   ├── feasibility_service.py        # Feasibility queries
│   │   └── text2sql.py                   # Text2SQL service
│   │
│   ├── adapters/                 # Data access
│   │   └── sql_on_fhir.py       # SQL adapter (parameterized queries) 🆕
│   │
│   ├── mcp_servers/             # MCP infrastructure
│   │   ├── mcp_registry.py      # Central registry
│   │   └── terminology_server.py # SNOMED/LOINC/RxNorm
│   │
│   ├── web_ui/                   # Streamlit interfaces
│   │   ├── researcher_portal.py # Request submission + tracking
│   │   └── admin_dashboard.py   # Monitoring + escalations
│   │
│   ├── api/                      # FastAPI endpoints
│   │   ├── text2sql.py          # Text-to-SQL conversion
│   │   ├── sql_on_fhir.py       # SQL query execution
│   │   ├── mcp.py               # MCP endpoints
│   │   └── a2a.py               # OAuth2 token issuance
│   │
│   ├── mcp/                      # MCP implementation
│   │   └── store.py             # File-based context store
│   │
│   ├── a2a/                      # Authentication
│   │   └── auth.py              # JWT token issuance
│   │
│   ├── clients/                  # External client integrations 🆕
│   ├── components/               # Reusable UI components 🆕
│   └── main.py                   # FastAPI entry point
│
├── scripts/                      # Automation scripts 🆕
│   ├── materialize_views.py     # Create/refresh materialized views
│   ├── refresh_materialized_views.py  # Auto-refresh cron job
│   ├── validate_referential_integrity.py  # Data validation
│   ├── tests/                    # Test scripts
│   └── utils/                    # Utility functions
│
├── tests/                        # Test suite (EXPANDED) 🆕
│   ├── test_text2sql.py
│   ├── test_sql_adapter.py
│   ├── test_mcp_store.py
│   ├── test_speed_layer_runner.py          # Speed layer tests (10 tests) 🆕
│   ├── test_hybrid_runner_speed_integration.py  # Integration (10 tests) 🆕
│   ├── test_materialized_views_integration.py  # Batch layer tests 🆕
│   ├── test_redis_client.py                # Redis cache tests 🆕
│   ├── test_agent_adapter.py                # LangGraph adapter (24 tests) 🆕
│   ├── test_approval_bridge.py              # Approval bridge (24 tests) 🆕
│   ├── test_langgraph_persistence.py        # Persistence (7 tests) 🆕
│   ├── test_simple_workflow.py              # Simple workflow 🆕
│   ├── test_langgraph_workflow.py           # Full workflow 🆕
│   ├── e2e/                      # End-to-end tests 🆕
│   └── integration/              # Integration tests 🆕
│
├── docs/                         # Documentation (EXPANDED) 🆕
│   ├── sprints/                  # Sprint reports (20 files) 🆕
│   │   ├── SPRINT_04_5_MATERIALIZED_VIEWS.md    # Batch layer
│   │   ├── SPRINT_05_LANGSMITH_OBSERVABILITY.md # Observability
│   │   ├── SPRINT_05_5_SPEED_LAYER.md           # Speed layer
│   │   ├── SPRINT_06_5_LANGGRAPH_MIGRATION.md   # LangGraph (1,010 lines)
│   │   ├── SPRINT_06_6_LANGCHAIN_AGENT_COMPARISON.md
│   │   └── SPRINT_07_SECURITY_HARDENING.md      # Security (836 lines)
│   ├── misc_enhancements/        # Enhancement docs (80+ files) 🆕
│   ├── SETUP_GUIDE.md           # Complete setup instructions
│   ├── QUICK_REFERENCE.md       # Commands & key concepts
│   ├── RESEARCHFLOW_README.md   # Full architecture docs
│   ├── MATERIALIZED_VIEWS.md     # Lambda batch layer guide 🆕
│   ├── MATERIALIZED_VIEWS_ARCHITECTURE.md  # Complete architecture 🆕
│   ├── REFERENTIAL_INTEGRITY.md # Dual column design 🆕
│   ├── AUTO_REFRESH_SETUP.md    # Cron setup guide 🆕
│   ├── DIAGRAMS_README.md       # How to view diagrams
│   └── ResearchFlow PRD.md      # Requirements document
│
├── diagrams/                     # Architecture diagrams
│   ├── architecture.puml         # Complete system architecture
│   ├── sequence_flow.puml        # Sequence diagram (8 phases)
│   ├── components.puml           # Component relationships
│   └── *.png                     # Generated diagram images
│
├── config/                       # Configuration files
│   ├── .env.example             # Environment template
│   ├── requirements.txt         # Python dependencies
│   ├── docker-compose.yml       # Docker setup
│   └── Dockerfile               # Container definition
│
├── .pre-commit-config.yaml       # Pre-commit hooks 🆕
├── .secrets.baseline             # detect-secrets baseline 🆕
├── pyproject.toml                # Bandit + Black config (UPDATED) 🆕
├── .github/workflows/            # GitHub Actions (UPDATED)
│   ├── security.yml              # 4-job security scanning 🆕
│   ├── tests.yml
│   └── docs.yml
│
├── .env                          # Your API keys (gitignored)
├── CLAUDE.md                     # This file
├── README.md                     # Project overview
├── Makefile                      # Common commands
├── SECURITY_SETUP.md             # Security infrastructure guide 🆕
├── LANGSMITH_KEY_ROTATION_GUIDE.md  # API key rotation 🆕
└── LICENSE                       # MIT License
```

## Architecture

### Multi-Agent System

ResearchFlow uses 6 autonomous AI agents coordinated by a central orchestrator:

1. **Requirements Agent** (`app/agents/requirements_agent.py`)
   - Conversational LLM interaction with researcher
   - Extracts structured requirements (inclusion/exclusion criteria, data elements, PHI level)
   - Uses Claude API with medical domain prompting

2. **Phenotype Agent** (`app/agents/phenotype_agent.py`)
   - Generates SQL-on-FHIR queries from requirements
   - Executes feasibility checks (cohort size estimation)
   - Calculates feasibility score (0.0-1.0)

3. **Calendar Agent** (`app/agents/calendar_agent.py`)
   - Schedules kickoff meetings with stakeholders
   - Uses MultiLLMClient for intelligent agenda generation
   - Future: Integrates with external calendar systems via MCP

4. **Extraction Agent** (`app/agents/extraction_agent.py`)
   - Multi-source data retrieval (Epic, FHIR servers, data warehouse)
   - Applies de-identification based on PHI level
   - Handles large data volumes with batching

5. **QA Agent** (`app/agents/qa_agent.py`)
   - Automated quality validation (completeness, duplicates, PHI scrubbing)
   - Generates QA reports with metrics
   - Escalates issues to human review when needed

6. **Delivery Agent** (`app/agents/delivery_agent.py`)
   - Packages data with documentation
   - Uses MultiLLMClient for personalized notifications and citations
   - Creates audit trail

### Orchestrator & Workflow

**Orchestrator** (`app/orchestrator/orchestrator.py`)
- Routes tasks between agents using A2A protocol
- Manages agent lifecycle and error handling
- Tracks all agent executions in database

**Workflow Engine** (`app/orchestrator/workflow_engine.py`)
- 15-state finite state machine
- Transition rules based on agent results
- States: new_request → requirements_gathering → feasibility_validation → schedule_kickoff → data_extraction → qa_validation → data_delivery → delivered → complete

### LangGraph Architecture Migration (Sprints 6.5 + 6.6) 🆕

**Status**: 75% complete (Phases 1-3.1 done, Phases 3.2-5 remaining)

ResearchFlow is migrating from custom imperative orchestrator to LangGraph declarative state machine for improved observability, durability, and maintainability.

**Dual Orchestration Systems**:
1. **Custom Orchestrator** (Production): `app/orchestrator/orchestrator.py`
   - Imperative routing with A2A protocol
   - Database-backed state (ResearchRequest table)
   - Used by Streamlit UIs

2. **LangGraph Workflow** (Migration Target): `app/langchain_orchestrator/langgraph_workflow.py`
   - Declarative StateGraph with 23 states
   - Type-safe state (FullWorkflowState TypedDict, 47 fields)
   - Checkpointer-based persistence (AsyncSqliteSaver)
   - LangSmith observability integration

**Architecture**:
```
┌────────────────────────────────────┐
│  Streamlit UIs                      │
└────────────┬───────────────────────┘
             │
     ┌───────▼──────────┐
     │ RequestFacade    │ ← Orchestrator-compatible API
     └───────┬──────────┘
             │
     ┌───────▼──────────┐
     │ LangGraph FSM    │ ← 23-state workflow
     │ (Checkpointer)   │
     └───┬───────┬──────┘
         │       │
   ┌─────▼──┐ ┌─▼────────┐
   │Adapter │ │ApprovalBridge│
   │(BaseAgent)│(DB sync) │
   └─────┬──┘ └─┬────────┘
         │      │
     ┌───▼──────▼───┐
     │  PostgreSQL  │
     └──────────────┘
```

**Key Files** (1,600+ lines):
- `app/langchain_orchestrator/langgraph_workflow.py` - 23-state FSM
- `app/langchain_orchestrator/persistence.py` - Checkpointer setup
- `app/langchain_orchestrator/agent_adapter.py` - BaseAgent ↔ LangGraph (400 lines)
- `app/langchain_orchestrator/approval_bridge.py` - DB approval sync (500 lines)
- `app/langchain_orchestrator/request_facade.py` - UI compatibility (700 lines)

**Why Adapter Pattern?**:
- Preserve 1,500+ lines of production agent logic
- Reduce migration risk (no business logic changes)
- 2-4 week timeline vs 2-3 months for full rewrite
- Easy rollback if issues arise

**Testing**: 48 tests, 100% passing
- `tests/test_agent_adapter.py` - 24 tests
- `tests/test_approval_bridge.py` - 24 tests
- `tests/test_langgraph_persistence.py` - 7 core tests

**Migration Roadmap**:
- ✅ Phase 1: Persistence & async fixes (COMPLETE)
- ✅ Phase 2: Agent & approval bridges (COMPLETE)
- ✅ Phase 3.1: Request facade (COMPLETE)
- 🔄 Phase 3.2: Streamlit UI integration (PAUSED)
- 📋 Phase 4-5: Deployment & cleanup (REMAINING)

**Environment Variables**:
- `USE_LANGGRAPH_WORKFLOW=false` - Feature flag (default: disabled)
- `LANGGRAPH_ROLLOUT_PCT=0` - Gradual rollout percentage

**Documentation**: `docs/sprints/SPRINT_06_5_LANGGRAPH_MIGRATION.md`

### Lambda Architecture (Sprints 4.5 + 5.5) 🆕

ResearchFlow implements a complete Lambda Architecture for FHIR data queries.

**Batch Layer** (`app/sql_on_fhir/runner/materialized_view_runner.py`)
- Pre-computed materialized views in `sqlonfhir` schema
- Performance: 5-15ms queries (10-100x faster than on-the-fly SQL generation)
- Refresh: Manual/cron-based (nightly)
- Coverage: Historical data up to last refresh

**Speed Layer** (`app/sql_on_fhir/runner/speed_layer_runner.py`)
- Redis cache for recent FHIR updates (last 24 hours)
- Performance: < 1 minute latency for new data
- TTL: 24 hours
- Integration: `RedisClient` in `app/cache/redis_client.py`

**Serving Layer** (`app/sql_on_fhir/runner/hybrid_runner.py`)
- Intelligent query routing (batch vs. speed layer)
- Automatic merge and deduplication
- Statistics tracking (batch vs. speed query counts)
- Environment control: `USE_SPEED_LAYER=true/false`

**Benefits**:
- 10-100x query performance improvement
- Real-time data access (< 1 minute freshness)
- Seamless fallback to PostgresRunner if views don't exist
- Complete AWS HealthLake functional equivalence

**Documentation**:
- `docs/MATERIALIZED_VIEWS_ARCHITECTURE.md` - Complete architecture
- `docs/MATERIALIZED_VIEWS.md` - Quick start guide

### Security Hardening (Sprint 7) 🆕

**Status**: ✅ COMPLETE - Production-ready security posture achieved

**Critical Fixes**:

1. **SQL Injection Prevention** (30 vulnerabilities eliminated)
   - Parameterized queries using SQLAlchemy `text()` with bound parameters
   - All SQL generation returns `(sql, params)` tuples
   - Zero SQL injection risk after remediation

2. **Pre-Commit Hooks** (4 hooks installed)
   - `detect-secrets` (v1.5.0) - Prevents secrets from being committed
   - `bandit` (v1.8.6) - Security issue detection
   - `black` (v25.9.0) - Code formatting
   - `pre-commit-hooks` (v6.0.0) - Basic file checks

3. **GitHub Actions Security Scanning** (4-job workflow)
   - Secret scanning (TruffleHog)
   - Dependency scanning (Safety + pip-audit)
   - Code security (Bandit with SARIF reports)
   - CodeQL analysis

4. **Secret Exposure Remediation**
   - Exposed LangSmith API key removed from git history
   - Rotation guide created: `LANGSMITH_KEY_ROTATION_GUIDE.md`

**Parameterized SQL Pattern**:
```python
# BEFORE (VULNERABLE):
patient_ids = ["123", "456", "789"]
patient_id_list = "'" + "','".join(patient_ids) + "'"
sql = f"SELECT * FROM patient WHERE id IN ({patient_id_list})"
result = await sql_adapter.execute_sql(sql)  # ⚠️ SQL INJECTION RISK

# AFTER (SECURE):
patient_ids = ["123", "456", "789"]
patient_id_params = {f"pid_{i}": pid for i, pid in enumerate(patient_ids)}
patient_id_placeholders = ", ".join(f":{name}" for name in patient_id_params.keys())
params = patient_id_params.copy()
sql = f"SELECT * FROM patient WHERE id IN ({patient_id_placeholders})"
result = await sql_adapter.execute_sql(sql, params)  # ✅ SAFE
```

**Files Modified**:
- `app/adapters/sql_on_fhir.py` - Added `params` parameter
- `app/utils/sql_generator.py` - 8 methods return `(sql, params)` tuples
- `app/agents/extraction_agent.py` - Fixed 6 SQL statements
- `app/agents/phenotype_agent.py` - Updated all calls

**Security Infrastructure**:
- `.pre-commit-config.yaml` - Pre-commit hook configuration
- `.github/workflows/security.yml` - 4-job security scanning workflow
- `pyproject.toml` - Bandit and Black configuration
- `.secrets.baseline` - detect-secrets baseline

**Setup Pre-Commit Hooks**:
```bash
# Install pre-commit
pip install pre-commit

# Install hooks
pre-commit install

# Run manually
pre-commit run --all-files
```

**Bandit Scan Results**:
- Before: 63 warnings (30 SQL injection, 20 false positives, 4 MD5, 7 misc)
- After: 0 warnings (30 documented suppressions with `# nosec`)

**Documentation**:
- `SECURITY_SETUP.md` - Pre-commit hooks setup guide
- `docs/sprints/SPRINT_07_SECURITY_HARDENING.md` - Complete sprint report

### Key Design Patterns

**Base Agent Pattern**: All agents inherit from `BaseAgent` class which provides:
- Retry logic with exponential backoff (3 retries max)
- State management (idle/working/failed/waiting)
- Human escalation workflow
- Task history tracking

**A2A Communication**: Agents communicate via orchestrator messages:
```python
{
    'agent_id': 'phenotype_agent',
    'task': 'validate_feasibility',
    'context': {...},
    'result': {...},
    'next_agent': 'calendar_agent',  # routing
    'next_task': 'schedule_kickoff'
}
```

**LLM Integration**: Multi-provider architecture with intelligent routing:
```python
# app/utils/llm_client.py - Critical medical tasks (Requirements, Phenotype agents)
class LLMClient:
    async def extract_requirements(self, conversation_history, current_requirements):
        # Prompt engineering for medical domain using Claude
        # Returns JSON with extracted_requirements, missing_fields, next_question

# app/utils/multi_llm_client.py - Non-critical tasks (Calendar, Delivery agents)
class MultiLLMClient:
    async def complete(self, prompt, task_type="general"):
        # Routes to Claude (critical) or secondary provider (non-critical)
        # Supports OpenAI, Ollama, or Claude via AI Suite
        # Auto-fallback to Claude on errors
```

**SQL Generation**: SQL-on-FHIR query builder:
```python
# app/utils/sql_generator.py
class SQLGenerator:
    def generate_phenotype_sql(self, requirements, count_only=False):
        # Builds SELECT, FROM, WHERE clauses
        # Handles inclusion/exclusion criteria, time periods
```

**Database Models** (6 tables in `app/database/models.py`):
- `ResearchRequest` - Main request tracking (15 states)
- `RequirementsData` - Structured requirements (JSON)
- `FeasibilityReport` - Cohort size + validation
- `AgentExecution` - Agent execution logs
- `Escalation` - Human-in-the-loop cases
- `DataDelivery` - Delivered data metadata

## Environment Variables

**Required:**
- `ANTHROPIC_API_KEY`: Claude API key (from Anthropic Console) - used for all critical medical tasks

**Optional Multi-Provider LLM Configuration:**
- `SECONDARY_LLM_PROVIDER`: Provider for non-critical tasks (options: `openai`, `ollama`, `anthropic`)
- `OPENAI_API_KEY`: OpenAI API key (only if using OpenAI as secondary provider)
- `OLLAMA_BASE_URL`: Ollama server URL (default: `http://localhost:11434`, only if using Ollama)
- `SECONDARY_LLM_MODEL`: Model name for secondary provider (e.g., `gpt-4o`, `llama3`)
- `ENABLE_LLM_FALLBACK`: Auto-fallback to Claude if secondary fails (default: `true`)

**Lambda Architecture Configuration:** 🆕
- `REDIS_URL`: Redis connection URL (default: `redis://localhost:6379/0`)
- `USE_SPEED_LAYER`: Enable speed layer (default: `true`)
- `REDIS_TTL_HOURS`: Speed layer cache TTL (default: `24`)

**LangSmith Observability:** 🆕
- `LANGCHAIN_TRACING_V2`: Enable LangSmith tracing (default: `false`)
- `LANGCHAIN_API_KEY`: LangSmith API key (optional, from https://smith.langchain.com/settings)
- `LANGCHAIN_PROJECT`: LangSmith project name (default: `researchflow-production`)
- `LANGCHAIN_ENDPOINT`: LangSmith endpoint (default: `https://api.smith.langchain.com`)

**LangGraph Migration:** 🆕
- `USE_LANGGRAPH_WORKFLOW`: Enable LangGraph orchestrator (default: `false`, feature flag)
- `LANGGRAPH_ROLLOUT_PCT`: Percentage of requests to route to LangGraph (default: `0`)

**Other Optional:**
- `DATABASE_URL`: Database connection (default: `sqlite+aiosqlite:///./dev.db`)
- `FHIR_SERVER_URL`: FHIR server URL (default: `http://localhost:8081/fhir`)
- `A2A_JWT_SECRET`: JWT signing secret (default: `devsecret`)

See `config/.env.example` for complete list.

## Testing

Tests use pytest with async support (`pytest-asyncio`).

**Test Organization**:
- `tests/` - Unit tests
- `tests/integration/` - Integration tests
- `tests/e2e/` - End-to-end tests
- `scripts/tests/` - Test scripts for runners

**Core Tests:**
- `tests/test_text2sql.py` - Text2SQL service tests
- `tests/test_sql_adapter.py` - SQL adapter tests
- `tests/test_mcp_store.py` - MCP context store tests

**Lambda Architecture Tests:** 🆕
- `tests/test_speed_layer_runner.py` - Speed layer tests (10 tests)
- `tests/test_hybrid_runner_speed_integration.py` - Integration tests (10 tests)
- `tests/test_materialized_views_integration.py` - Batch layer tests
- `tests/test_redis_client.py` - Redis cache tests
- `tests/test_referential_integrity.py` - Dual column integrity tests

**LangGraph Migration Tests:** 🆕
- `tests/test_agent_adapter.py` - Agent adapter (24 tests, 100% passing)
- `tests/test_approval_bridge.py` - Approval bridge (24 tests, 100% passing)
- `tests/test_langgraph_persistence.py` - Persistence (7 core tests)
- `tests/test_simple_workflow.py` - Simple 3-state workflow
- `tests/test_langgraph_workflow.py` - Full 23-state workflow
- `tests/e2e/test_langgraph_workflow_e2e.py` - End-to-end tests

**Security Tests:** 🆕
- SQL injection prevention tests (manual testing completed)
- Pre-commit hook tests (integrated in CI/CD)
- Bandit security scanning (0 warnings after remediation)

**Run All Tests:**
```bash
pytest -v
```

**Run Specific Test Suites:**
```bash
# Lambda Architecture tests
pytest tests/test_speed_layer_runner.py -v
pytest tests/test_hybrid_runner_speed_integration.py -v

# LangGraph tests
pytest tests/test_agent_adapter.py -v
pytest tests/test_approval_bridge.py -v

# Security scanning
pre-commit run --all-files
bandit -r app/
```

**Test Coverage**: ~70% (target: 90% for production)

## Implementation Status

**Completed:**
- ✅ All 6 agents implemented (BaseAgent-based)
- ✅ Custom orchestrator + workflow engine (15-state FSM)
- ✅ **LangGraph migration (75% complete - Phases 1-3.1 done)** 🆕
- ✅ **LangChain agent implementations** 🆕
- ✅ **Checkpointer-based persistence (AsyncSqliteSaver)** 🆕
- ✅ LLM integration (Claude API primary)
- ✅ Multi-provider LLM client (OpenAI, Ollama secondary)
- ✅ SQL generation (SQL-on-FHIR v1 + v2)
- ✅ **Lambda Architecture (Batch + Speed + Serving layers)** 🆕
- ✅ **Materialized views (10-100x performance improvement)** 🆕
- ✅ **Redis speed layer (< 1 minute data freshness)** 🆕
- ✅ **HybridRunner serving layer (automatic merge)** 🆕
- ✅ **LangSmith observability (full workflow tracing)** 🆕
- ✅ **Security hardening (30 SQL injection vulnerabilities eliminated)** 🆕
- ✅ **Pre-commit hooks (detect-secrets, bandit, black)** 🆕
- ✅ **GitHub Actions security scanning (4-job workflow)** 🆕
- ✅ **Parameterized SQL queries (zero SQL injection risk)** 🆕
- ✅ Database models (6 tables)
- ✅ MCP infrastructure (registry + terminology server)
- ✅ Streamlit UIs (researcher portal + admin dashboard)
- ✅ Complete documentation (120+ docs including 20 sprint reports)

**Production TODOs:**
- [ ] **Complete LangGraph migration (Phases 3.2-5)** 🆕
  - [ ] Streamlit UI integration with feature flag
  - [ ] Gradual rollout (10% → 50% → 100%)
  - [ ] Archive custom orchestrator to `app/legacy/`
- [ ] **Security enhancements** 🆕
  - [ ] Comprehensive security-specific tests
  - [ ] Penetration testing
  - [ ] Rate limiting and circuit breakers
- [ ] Auto-refresh pipeline (cron job for materialized views)
- [ ] FHIR Subscription listener (real-time event capture)
- [ ] Real MCP servers (Epic, FHIR, Calendar) - currently stubs
- [ ] Authentication & authorization for UIs
- [ ] Database migrations (Alembic)
- [ ] Production logging & monitoring (Prometheus/Grafana)
- [ ] Kubernetes deployment configs
- [ ] Secure file storage (S3/Azure)
- [ ] Email notification service

## Documentation

**Setup & Getting Started:**
- `docs/SETUP_GUIDE.md` - Complete setup instructions
- `docs/QUICK_REFERENCE.md` - Commands & key concepts
- `SECURITY_SETUP.md` - Pre-commit hooks and security scanning setup 🆕

**Architecture & Design:**
- `docs/RESEARCHFLOW_README.md` - Full architecture & features
- `docs/MATERIALIZED_VIEWS_ARCHITECTURE.md` - Complete Lambda implementation 🆕
- `docs/HealthLakeVsResearchFlowComparison.md` - vs. AWS HealthLake 🆕
- `docs/DIAGRAMS_README.md` - How to view architecture diagrams

**Implementation Guides:**
- `docs/MATERIALIZED_VIEWS.md` - Materialized views quick start 🆕
- `docs/REFERENTIAL_INTEGRITY.md` - Dual column design 🆕
- `docs/AUTO_REFRESH_SETUP.md` - Cron setup for batch layer 🆕
- `docs/TEXT_TO_SQL_FLOW.md` - LLM conversation to SQL explained
- `docs/SQL_ON_FHIR_V2.md` - ViewDefinition implementation guide
- `docs/add_params.md` - Recommended architecture patterns for Text2SQL

**Security:**
- `SECURITY_SETUP.md` - Pre-commit hooks installation & GitHub Actions 🆕
- `LANGSMITH_KEY_ROTATION_GUIDE.md` - API key rotation instructions 🆕
- `docs/sprints/SPRINT_07_SECURITY_HARDENING.md` - Complete security sprint 🆕

**Project Management:**
- `docs/GAP_ANALYSIS_AND_ROADMAP.md` - Production readiness & roadmap
- `docs/ResearchFlow PRD.md` - Original requirements
- `docs/sprints/SPRINT_TRACKER.md` - Sprint progress tracker

**Sprint Reports** (20 files in `docs/sprints/`): 🆕
- `SPRINT_01_REQUIREMENTS_AGENT.md` - Requirements agent implementation
- `SPRINT_02_SIMPLE_WORKFLOW.md` - Simple workflow POC
- `SPRINT_03_FULL_WORKFLOW.md` - Full workflow implementation
- `SPRINT_04_5_MATERIALIZED_VIEWS.md` - Batch layer (Lambda) 🆕
- `SPRINT_05_LANGSMITH_OBSERVABILITY.md` - LangSmith integration 🆕
- `SPRINT_05_5_SPEED_LAYER.md` - Speed layer (Lambda) 🆕
- `SPRINT_06_SECURITY_BASELINE.md` - Security planning
- `SPRINT_06_5_LANGGRAPH_MIGRATION.md` - LangGraph migration (1,010 lines) 🆕
- `SPRINT_06_6_LANGCHAIN_AGENT_COMPARISON.md` - Agent comparison 🆕
- `SPRINT_07_SECURITY_HARDENING.md` - Security hardening (836 lines) 🆕
- ... and more in `docs/sprints/`

**Additional Documentation** (80+ files in `docs/misc_enhancements/`):
- Architecture analysis, design system, demo guides, troubleshooting, etc.

## Diagrams

View architecture diagrams in `diagrams/` folder:
- `architecture.puml` - Complete system with 24 data flow steps
- `sequence_flow.puml` - 8-phase chronological sequence
- `components.puml` - Component relationships

Generate PNGs: `plantuml diagrams/*.puml`

Or view online: http://www.plantuml.com/plantuml/uml/ (paste `.puml` contents)
