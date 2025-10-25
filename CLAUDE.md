# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**ResearchFlow** is an AI-powered multi-agent system that automates clinical research data requests from natural language to delivery. Built on FastAPI with a multi-agent architecture, it reduces data request turnaround from weeks to hours.

### Core Components
- **6 Specialized AI Agents**: Requirements, Phenotype, Calendar, Extraction, QA, Delivery
- **Orchestrator**: Central A2A (Agent-to-Agent) coordinator with workflow state machine
- **Multi-Provider LLM Integration**: Claude API (primary) with optional secondary providers (OpenAI, Ollama) for non-critical tasks
- **SQL-on-FHIR**: Automated phenotype SQL generation and execution
- **MCP Infrastructure**: Model Context Protocol servers for external system integration
- **Streamlit UIs**: Researcher Portal and Admin Dashboard

## Quick Start

### Local Development (without Docker)
```bash
# Setup
python3 -m venv .venv
source .venv/bin/activate
pip install -r config/requirements.txt

# Add API key to .env
cp config/.env.example .env
# Edit .env and add ANTHROPIC_API_KEY=sk-ant-api03-...

# Run Researcher Portal
streamlit run app/web_ui/researcher_portal.py --server.port 8501

# Run Admin Dashboard
streamlit run app/web_ui/admin_dashboard.py --server.port 8502

# Run API server
make run
# or: uvicorn app.main:app --reload --port 8000

# Run tests
make test
# or: pytest -q
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
│   ├── orchestrator/             # Central coordination
│   │   ├── orchestrator.py      # A2A message routing
│   │   └── workflow_engine.py   # 15-state workflow FSM
│   │
│   ├── database/                 # Data models (6 tables)
│   │   └── models.py            # SQLAlchemy models
│   │
│   ├── utils/                    # Utilities
│   │   ├── llm_client.py        # Claude API wrapper (critical tasks)
│   │   ├── multi_llm_client.py  # Multi-provider LLM client (AI Suite)
│   │   └── sql_generator.py     # SQL-on-FHIR generation
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
│   ├── services/                 # Business logic
│   │   └── text2sql.py          # Text2SQL service
│   │
│   ├── adapters/                 # Data access
│   │   └── sql_on_fhir.py       # SQL adapter with sandboxing
│   │
│   ├── mcp/                      # MCP implementation
│   │   └── store.py             # File-based context store
│   │
│   ├── a2a/                      # Authentication
│   │   └── auth.py              # JWT token issuance
│   │
│   └── main.py                   # FastAPI entry point
│
├── docs/                         # Documentation
│   ├── SETUP_GUIDE.md           # Complete setup instructions
│   ├── QUICK_REFERENCE.md       # Commands & key concepts
│   ├── RESEARCHFLOW_README.md   # Full architecture docs
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
├── tests/                        # Test suite
│   ├── test_text2sql.py
│   ├── test_sql_adapter.py
│   └── test_mcp_store.py
│
├── .env                          # Your API keys (gitignored)
├── CLAUDE.md                     # This file
├── README.md                     # Project overview
├── Makefile                      # Common commands
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

**Other Optional:**
- `DATABASE_URL`: Database connection (default: `sqlite+aiosqlite:///./dev.db`)
- `A2A_JWT_SECRET`: JWT signing secret (default: `devsecret`)

See `config/.env.example` for complete list.

## Testing

Tests use pytest with async support (`pytest-asyncio`). Test files:
- `tests/test_text2sql.py` - Text2SQL service tests
- `tests/test_sql_adapter.py` - SQL adapter tests
- `tests/test_mcp_store.py` - MCP context store tests

## Implementation Status

**Completed:**
- ✅ All 6 agents implemented
- ✅ Orchestrator + workflow engine
- ✅ LLM integration (Claude API)
- ✅ SQL generation (SQL-on-FHIR)
- ✅ Database models (6 tables)
- ✅ MCP infrastructure (registry + terminology server)
- ✅ Streamlit UIs (researcher portal + admin dashboard)
- ✅ Complete documentation (5 docs + 3 diagrams)

**Production TODOs:**
- [ ] Real MCP servers (Epic, FHIR, Calendar) - currently stubs
- [ ] Authentication & authorization for UIs
- [ ] Database migrations (Alembic)
- [ ] Comprehensive test coverage
- [ ] Production logging & monitoring
- [ ] Kubernetes deployment configs
- [ ] Secure file storage (S3/Azure)
- [ ] Email notification service

## Documentation

- **Setup Guide**: `docs/SETUP_GUIDE.md` - Complete setup instructions
- **Quick Reference**: `docs/QUICK_REFERENCE.md` - Commands & key concepts
- **Full Docs**: `docs/RESEARCHFLOW_README.md` - Architecture & features
- **Diagrams**: `docs/DIAGRAMS_README.md` - How to view architecture diagrams
- **Text-to-SQL Flow**: `docs/TEXT_TO_SQL_FLOW.md` - LLM conversation to SQL explained
- **Gap Analysis**: `docs/GAP_ANALYSIS_AND_ROADMAP.md` - Production readiness & roadmap (8-month plan)
- **SQL-on-FHIR v2**: `docs/SQL_ON_FHIR_V2.md` - ViewDefinition implementation guide
- **Best Practices**: `docs/add_params.md` - Recommended architecture patterns for Text2SQL
- **PRD**: `docs/ResearchFlow PRD.md` - Original requirements

## Diagrams

View architecture diagrams in `diagrams/` folder:
- `architecture.puml` - Complete system with 24 data flow steps
- `sequence_flow.puml` - 8-phase chronological sequence
- `components.puml` - Component relationships

Generate PNGs: `plantuml diagrams/*.puml`

Or view online: http://www.plantuml.com/plantuml/uml/ (paste `.puml` contents)
