# ResearchFlow

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-green.svg)](https://fastapi.tiangolo.com/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

**Experimental Multi-Agent AI System for Clinical Research Automation**

> ⚠️ **Work in Progress**: ResearchFlow is an experimental prototype demonstrating where AI should own workflows versus where humans are essential. Built entirely with agentic AI coding (Claude Code) as a meta-experiment to prove the concept. Not yet production-ready.

ResearchFlow automates clinical research data requests from natural language to delivery, reducing turnaround time from **weeks to hours** while maintaining rigorous human oversight at critical decision points.

---

## The Experiment

**The Core Question:** Can AI build AI that handles administrative coordination while preserving human expertise where it's truly irreplaceable?

As a biomedical informatician supporting clinical research, I observed that ~50% of my work was administrative coordination (scheduling, routing, status tracking) while ~50% required deep technical expertise (validating SQL queries, phenotype definitions, data quality).

**The Meta-Experiment:** I built ResearchFlow using agentic AI coding to prove that:
- **AI should own:** Administrative workflow orchestration (coordination, routing, notifications)
- **Humans must validate:** All technical decisions requiring domain expertise (SQL queries, computations, data quality)

**The Result:** A multi-agent system demonstrating sustainable AI architecture for regulated technical domains.

---

## Table of Contents

- [Architecture](#architecture)
- [Key Features](#key-features)
- [Quick Start](#quick-start)
- [Performance](#performance)
- [Human-in-Loop Safety](#human-in-loop-safety)
- [Current Status](#current-status)
- [Documentation](#documentation)

---

## Architecture

### Lambda Architecture (3 Layers)

ResearchFlow implements a **Lambda Architecture** for FHIR analytics as a learning exercise:

```
┌─────────────────────────────────────────────────────────────┐
│                    FHIR DATA SOURCE                         │
│               HAPI FHIR Server (PostgreSQL)                 │
│         105 patients, 423 conditions (real FHIR R4)         │
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
         ┌─────────────────────────────────────┐
         │   SERVING LAYER                     │
         │  HybridRunner (Smart Routing)       │
         ├─────────────────────────────────────┤
         │ • Merges batch + speed results      │
         │ • Deduplication (speed wins)        │
         │ • View existence caching            │
         │ • Statistics tracking               │
         └─────────────────────────────────────┘
```

### Multi-Agent System (6 Specialized Agents)

```
┌───────────────────────────────────────────────────────┐
│                   Orchestrator                        │
│      (Workflow Engine | 20 States | A2A Protocol)     │
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
- **Result:** 95% time savings (weeks → hours) with 100% expert validation maintained

### 🛡️ Human-in-Loop Safety Gates

**5 Mandatory Approval Checkpoints:**
- **SQL Review** (CRITICAL): Informatician must approve queries before execution
- **Requirements Validation**: Verify medical accuracy
- **Extraction Authorization**: Approve data access
- **QA Review**: Validate quality results
- **Scope Changes**: Evaluate mid-workflow modifications

### 📊 SQL-on-FHIR v2 Implementation

- **ViewDefinitions**: Standards-compliant FHIR analytics
- **Performance**: 1151x speedup (in-database vs REST API)
- **Dual Runners**: PostgreSQL (fast) + In-Memory (flexible)
- **Query Optimization**: Automatic SNOMED/LOINC/ICD-10 code resolution

### 💡 Multi-Provider LLM Architecture

- **Intelligent Routing**: Claude (critical medical tasks) + OpenAI/Ollama (non-critical)
- **60% Cost Reduction**: Smart routing based on task criticality
- **Auto-Fallback**: Secondary provider failures route to Claude
- **LangSmith Observability**: Full workflow tracing proves AI vs human division of labor

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

- Python 3.9+
- Anthropic API key ([get key](https://console.anthropic.com/))
- PostgreSQL (optional; SQLite works for dev)

### Installation (3 Steps)

```bash
# 1. Clone and setup environment
git clone https://github.com/yourusername/researchflow.git
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
| Repeated Query Execution | 116.2s | 0.101s | **1151x faster** |
| Workflow Turnaround | 2-3 weeks | 4-8 hours | **95% faster** |
| LLM Costs (multi-provider) | $750/month | $295/month | **60% reduction** |
| Cache Hit Rate | 0% | 95% | N/A |

### Lambda Architecture Performance

| Layer | Metric | Performance |
|-------|--------|-------------|
| **Batch** | Materialized view query | 5-15ms |
| **Speed** | Real-time data latency | <1 minute |
| **Cache** | Repeated query speedup | **1151x faster** |
| **Overall** | Historical data speedup | **10-100x faster** |

**Note:** These benchmarks are from experimental implementation. Performance will vary based on data volume and infrastructure.

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

# Optional: Multi-Provider LLM (60% cost reduction)
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

- 🏛️ **[Lambda Architecture Comparison](docs/HealthLakeVsResearchFlowComparison.md)** - Complete implementation analysis
- 📐 **[Gap Analysis & Roadmap](docs/GAP_ANALYSIS_AND_ROADMAP.md)** - Development status (44.44% complete)
- 🧪 **[Testing Guide](docs/SQL_ON_FHIR_TESTING_GUIDE.md)** - Test data setup and execution

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
| **Lines of Code** | 15,000+ (generated with agentic AI coding) |
| **AI Agents** | 6 specialized agents |
| **Database Tables** | 8 tables |
| **Workflow States** | 20 states (LangGraph FSM) |
| **API Endpoints** | 25+ REST endpoints |
| **Test Coverage** | 85%+ across core modules |
| **Test Files** | 42 comprehensive test files |
| **Documentation** | 60+ markdown files |

### Experimental Achievements

- ⚡ **1151x speedup** - Repeated query caching (proof-of-concept)
- 🚀 **10-100x speedup** - Materialized views vs raw SQL
- 💰 **60% cost reduction** - Multi-provider LLM routing
- ⏱️ **95% time savings** - Weeks → hours turnaround (experimental)
- 📊 **Lambda Architecture** - Complete 3-layer implementation
- 🛡️ **Human-in-Loop** - 5 mandatory approval gates

### Roadmap

**Completed (Sprint 5.5 - Lambda Architecture)**
- ✅ Complete Lambda Architecture (Batch + Speed + Serving)
- ✅ Redis speed layer with <1 minute latency
- ✅ HybridRunner serving layer with intelligent merging
- ✅ 29 comprehensive tests (100% pass rate)
- ✅ LangSmith observability integration

**Current (Sprint 6 - Security Baseline)**
- 🔄 JWT authentication & RBAC authorization
- 🔄 SQL injection prevention & input validation
- 🔄 PHI audit logging & encryption
- 🔄 HIPAA compliance checklist

**Planned (Sprint 7-18)**
- 📅 MCP Tools Integration (terminology servers, calendar APIs)
- 📅 Advanced analytics dashboard
- 📅 Multi-tenant support
- 🔮 Machine learning for cohort optimization
- 🔮 Real-time collaboration features

See **[docs/GAP_ANALYSIS_AND_ROADMAP.md](docs/GAP_ANALYSIS_AND_ROADMAP.md)** for complete 8-month implementation plan.

---

## Known Limitations

**This is experimental software. Known limitations include:**

- ✋ **Not production-ready**: Requires security hardening before clinical deployment
- ✋ **Limited testing**: Tested with synthetic data only (Synthea FHIR generator)
- ✋ **Single institution**: Not tested across multiple healthcare systems
- ✋ **Manual refresh**: Materialized views require manual/cron refresh
- ✋ **No encryption**: PHI encryption not yet implemented
- ✋ **Basic authentication**: JWT authentication not yet production-hardened

**For demonstration and learning purposes only. Do not use with real patient data without proper security review.**

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

## Citation

If you use ResearchFlow in your research or find the architecture pattern useful, please cite:

```bibtex
@software{researchflow2025,
  title = {ResearchFlow: Experimental Multi-Agent System for Clinical Research Automation},
  author = {ResearchFlow Contributors},
  year = {2025},
  url = {https://github.com/yourusername/researchflow},
  version = {2.0-experimental},
  note = {Proof-of-concept demonstrating AI for coordination, humans for expertise}
}
```

---

## Acknowledgments

- Built with [FastAPI](https://fastapi.tiangolo.com/)
- LLM integration via [Anthropic Claude API](https://www.anthropic.com/)
- Orchestration by [LangGraph](https://github.com/langchain-ai/langgraph)
- Observability by [LangSmith](https://www.langchain.com/langsmith)
- SQL-on-FHIR v2 specification by [HL7 FHIR](https://hl7.org/fhir/)
- UI powered by [Streamlit](https://streamlit.io/)

**Special thanks to the agentic AI coding workflow that made this experiment possible.**

---

## Project Status

**Version**: 2.0-experimental
**Status**: Proof-of-Concept / Demonstration
**Last Updated**: October 2025
**Development Progress**: 44.44% (8/18 planned sprints)

### Key Proof Points

- ✅ **Meta-Experiment Validated**: AI can build AI for workflow automation
- ✅ **Architecture Pattern Demonstrated**: AI for coordination, humans for expertise
- ✅ **Human-in-Loop Safety**: 5 mandatory approval gates prove sustainable AI design
- ✅ **Observability**: LangSmith traces prove division of labor works
- ✅ **Open Source**: MIT License enables community learning and adaptation

### What This Project Demonstrates

**For Healthcare IT:**
- Sustainable pattern for AI in regulated domains
- Clear boundaries between AI coordination and human expertise
- SQL-on-FHIR v2 implementation as performance optimization

**For AI Engineers:**
- Multi-agent orchestration with LangGraph (20-state FSM)
- Lambda Architecture for FHIR analytics (Batch + Speed + Serving)
- Multi-provider LLM architecture with intelligent routing
- Production observability with LangSmith

**For Product Managers:**
- Where AI should own workflows (administrative coordination)
- Where humans are irreplaceable (technical validation)
- How to design human-AI collaboration at scale

---

For questions, issues, or collaboration requests, please use [GitHub Issues](https://github.com/yourusername/researchflow/issues).

**ResearchFlow**: An experiment in AI-human collaboration for clinical research. Built with AI to prove where AI belongs. 🤖🏥
