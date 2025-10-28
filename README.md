# ResearchFlow

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-green.svg)](https://fastapi.tiangolo.com/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

**AI-Powered Clinical Research Data Automation System**

ResearchFlow is an intelligent multi-agent system that automates clinical research data requests from natural language to delivery, reducing turnaround time from weeks to hours while maintaining rigorous human oversight at critical decision points.

---

## Table of Contents

- [Executive Summary](#executive-summary)
- [Key Features](#key-features)
- [Architecture](#architecture)
- [Quick Start](#quick-start)
- [Installation](#installation)
- [Usage](#usage)
- [API Documentation](#api-documentation)
- [Human-in-Loop Approval Workflow](#human-in-loop-approval-workflow)
- [Performance](#performance)
- [Configuration](#configuration)
- [Testing](#testing)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [License](#license)
- [Citation](#citation)

---

## Executive Summary

ResearchFlow transforms the clinical research data request process through autonomous AI agents that handle requirements gathering, phenotype definition, data extraction, quality assurance, and delivery. The system integrates seamlessly with existing healthcare IT infrastructure while ensuring compliance through comprehensive human approval gates.

### Core Capabilities

| Capability | Description | Impact |
|------------|-------------|--------|
| **Natural Language Processing** | Converts researcher requests to structured requirements using Claude API | 95% reduction in back-and-forth communication |
| **SQL-on-FHIR v2** | Automated generation and validation of FHIR analytics queries | 10-100x faster than traditional methods |
| **Human Oversight** | Critical approval gates at SQL review, requirements, and QA stages | 100% validation before execution |
| **Multi-Source Integration** | Unified extraction from Epic, FHIR servers, and data warehouses | Single interface for heterogeneous sources |
| **Performance Optimization** | Query caching (1151x speedup) and parallel processing (1.5x speedup) | Near real-time analytics on large datasets |

---

## Key Features

### Multi-Agent Architecture

ResearchFlow employs seven specialized autonomous agents:

1. **Requirements Agent** - Conversational LLM-based requirements extraction
2. **Phenotype Agent** - SQL-on-FHIR query generation and feasibility analysis
3. **Calendar Agent** - Stakeholder meeting coordination
4. **Extraction Agent** - Multi-source data retrieval with de-identification
5. **QA Agent** - Automated quality validation and PHI scrubbing
6. **Delivery Agent** - Data packaging and distribution
7. **Coordinator Agent** - Approval workflow orchestration and stakeholder communication

### Human-in-Loop Approval Gates

**NEW in Version 2.0**: Critical safety checkpoints requiring human approval:

| Approval Type | Reviewer | Timeout | Purpose |
|---------------|----------|---------|---------|
| **Requirements Review** | Informatician | 24h | Validate medical accuracy |
| **SQL Review** | Informatician | 24h | **CRITICAL** - Approve before execution |
| **Extraction Approval** | Admin | 12h | Authorize data access |
| **QA Review** | Informatician | 24h | Validate quality results |
| **Scope Change** | Coordinator | 48h | Evaluate mid-workflow changes |

**Safety Guarantee**: SQL queries cannot execute without informatician approval.

### SQL-on-FHIR v2 Implementation

- **ViewDefinitions**: Standards-compliant FHIR analytics
- **Dual Runners**: PostgreSQL (in-database, fast) and In-Memory (flexible, REST API)
- **Automatic Generation**: Converts structured requirements to validated SQL
- **Feasibility Analysis**: Cohort size estimation before extraction

### Production Features

- **Database Persistence**: All state survives restarts; complete audit trail
- **Query Caching**: 1151x speedup on repeated queries
- **Parallel Processing**: 1.5x speedup using asyncio
- **Health Monitoring**: Production-ready endpoints for system observability
- **Scope Change Support**: Mid-workflow requirement modifications with impact analysis
- **Timeout Detection**: Proactive escalation of delayed approvals

### LangSmith Observability ⭐ NEW

**Sprint 5 Enhancement**: Complete workflow observability with LangSmith tracing

- **Workflow Tracing**: Monitor every execution from start to finish
- **Agent Performance**: Track execution time and success rate for all 6 agents
- **LLM Cost Tracking**: Monitor token usage, costs, and latency for Claude API calls
- **Error Debugging**: Full stack traces with request context for failed workflows
- **Smart Tagging**: Separate E2E test runs from production executions
- **Hierarchical Traces**: Workflow → Agent → LLM call hierarchy for deep visibility

**Dashboard**: Access real-time traces at [smith.langchain.com](https://smith.langchain.com)
**Guide**: See `docs/LANGSMITH_DASHBOARD_GUIDE.md` for complete usage instructions

---

## Architecture

### System Overview

```
┌──────────────────────────────────────────────────────────────┐
│                     User Interfaces                          │
│          (Researcher Portal | Admin Dashboard)               │
└────────────────────────┬─────────────────────────────────────┘
                         │
┌────────────────────────▼─────────────────────────────────────┐
│                   Orchestrator                                │
│      (A2A Communication | Workflow Engine | 20 States)        │
└────────────────────────┬─────────────────────────────────────┘
                         │
        ┌────────────────┼────────────────┐
        │                │                │
        ▼                ▼                ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ Requirements │──│  Phenotype   │──│   Calendar   │
│    Agent     │  │    Agent     │  │    Agent     │
└──────────────┘  └──────────────┘  └──────────────┘
        │                │                │
        ▼                ▼                ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│  Extraction  │──│      QA      │──│   Delivery   │
│    Agent     │  │    Agent     │  │    Agent     │
└──────────────┘  └──────────────┘  └──────────────┘
                         │
                         ▼
                ┌──────────────┐
                │ Coordinator  │
                │    Agent     │
                └──────────────┘
```

### Data Flow with Approval Gates

```
1. Requirements Extraction → [HUMAN REVIEW]
2. SQL Generation → [HUMAN APPROVAL] ← CRITICAL
3. Meeting Scheduling → [AUTHORIZATION]
4. Data Extraction
5. Quality Assurance → [HUMAN REVIEW]
6. Data Delivery
```

**Visual Diagrams**: Complete PlantUML diagrams available in `diagrams/` directory

---

## Quick Start

### Prerequisites

- Python 3.9 or higher
- Anthropic API key (Claude)
- PostgreSQL (optional, SQLite supported for development)

### Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/researchflow.git
cd researchflow

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r config/requirements.txt

# Configure environment
cp config/.env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
```

### Running Services

```bash
# Terminal 1: Start API server
uvicorn app.main:app --reload --port 8000

# Terminal 2: Start Exploratory Analytics Portal (Chat Interface)
streamlit run app/web_ui/research_notebook.py --server.port 8501

# Terminal 3: Start Formal Request Portal (Form-based)
streamlit run app/web_ui/researcher_portal.py --server.port 8502

# Terminal 4: Start Admin Dashboard
streamlit run app/web_ui/admin_dashboard.py --server.port 8503
```

### Access Points

| Service | URL | Purpose |
|---------|-----|---------|
| Exploratory Analytics Portal | http://localhost:8501 | Interactive SQL-on-FHIR analytics with chat interface |
| Formal Request Portal | http://localhost:8502 | Structured data requests with approval workflow |
| Admin Dashboard | http://localhost:8503 | Review approvals, monitor system |
| API Server | http://localhost:8000 | REST API endpoints |
| API Documentation | http://localhost:8000/docs | Interactive API docs |

---

## Two Researcher Interfaces

ResearchFlow provides two complementary interfaces for different research workflows:

### 1. 📊 Exploratory Analytics Portal (Chat Interface)

**URL**: http://localhost:8501
**File**: `app/web_ui/research_notebook.py`

**Purpose**: Quick, interactive exploration of available data using natural language queries

#### Features
- 💬 **Conversational AI** - Ask questions naturally, get instant answers
- ⚡ **Real-time SQL-on-FHIR Analytics** - Fast COUNT queries, no approvals needed
- 📈 **Feasibility Metrics** - Cohort size estimates, data availability scores
- 🔄 **Convert to Formal** - Option to proceed to full extraction workflow

#### Use Cases
- "How many patients with diabetes do we have?"
- "What's the age distribution of heart failure patients?"
- "Patients with HbA1c > 8% in the last year?"
- Exploring data availability before writing research protocol

#### Workflow
```
1. User asks natural language question
   ↓
2. AI interprets query (LLM-powered)
   ↓
3. Generates SQL-on-FHIR ViewDefinition
   ↓
4. Executes COUNT query against FHIR data
   ↓
5. Shows cohort size, feasibility metrics
   ↓
6. [Optional] User confirms → Submit to formal workflow
```

**Key Advantage**: Get answers in **seconds**, not weeks. No approvals required for counts.

**Start**: `streamlit run app/web_ui/research_notebook.py --server.port 8501`

---

### 2. 📋 Formal Request Portal (Structured Forms)

**URL**: http://localhost:8502
**File**: `app/web_ui/researcher_portal.py`

**Purpose**: Submit structured data requests with proper terminologies for full data extraction

#### Features
- 📝 **Form-based Submission** - Required fields (IRB, researcher info, data elements)
- 🔐 **Full Approval Workflow** - Informatician SQL review, extraction approval, QA review
- 🤖 **Multi-Agent Orchestration** - Requirements → Phenotype → Extraction → QA → Delivery
- 📊 **Compliance & Audit** - Complete audit trail, HIPAA-compliant de-identification

#### Use Cases
- "I need to extract diabetes patient data for IRB-2025-001 study"
- "Formal data request with specific terminologies (SNOMED, LOINC)"
- "Upload data request form with inclusion/exclusion criteria"
- "IRB-approved research requiring full dataset delivery"

#### Workflow
```
1. Fill form with researcher info, IRB, data request
   ↓
2. Submit to Orchestrator
   ↓
3. Requirements Agent extracts structured requirements
   ↓
4. Phenotype Agent generates SQL
   ↓
5. 🚨 CRITICAL: Informatician approval required
   ↓
6. Data Extraction → QA → Delivery
   ↓
7. Delivered data with documentation
```

**Key Requirement**: **Informatician must approve SQL** before execution (safety gate)

**Start**: `streamlit run app/web_ui/researcher_portal.py --server.port 8502`

---

### When to Use Which Interface?

| Scenario | Recommended Interface | Why? |
|----------|----------------------|------|
| "What data is available?" | 📊 Exploratory Analytics | Instant counts, no approvals |
| "Quick cohort size check" | 📊 Exploratory Analytics | Feasibility in seconds |
| "Need formal IRB-approved extraction" | 📋 Formal Request Portal | Full audit trail, compliance |
| "Upload data request with terminologies" | 📋 Formal Request Portal | Structured requirements |
| "Exploring before writing protocol" | 📊 Exploratory → 📋 Formal | Explore first, then formal request |
| "Delivery of full dataset" | 📋 Formal Request Portal | Requires approvals, de-identification, QA |

**Typical Researcher Workflow**:
1. **Explore** using chat interface → Get fast feasibility estimates
2. **Refine** research question based on available data
3. **Submit formal** request once IRB approved and criteria defined

---

## Usage

### Submitting a Research Request

```python
import requests

# Submit natural language request
response = requests.post(
    "http://localhost:8000/research/submit",
    json={
        "researcher_name": "Dr. Smith",
        "researcher_email": "smith@hospital.org",
        "irb_number": "IRB-2025-001",
        "request": "I need all female patients over 50 with diabetes diagnosed in the past 2 years"
    }
)

request_id = response.json()["request_id"]
```

### Approving SQL Queries

```python
# Get pending SQL approvals
approvals = requests.get(
    "http://localhost:8000/approvals/pending?approval_type=phenotype_sql"
).json()["approvals"]

# Review and approve
requests.post(
    f"http://localhost:8000/approvals/{approvals[0]['id']}/respond",
    json={
        "decision": "approve",
        "reviewer": "informatician@hospital.org",
        "notes": "SQL query validated against schema"
    }
)
```

### Requesting Scope Changes

```python
# Request mid-workflow scope change
requests.post(
    "http://localhost:8000/approvals/scope-change",
    json={
        "request_id": request_id,
        "requested_by": "researcher@hospital.org",
        "requested_changes": {
            "inclusion_criteria": ["Add: HbA1c > 7.0%"]
        },
        "reason": "PI requested broader cohort for statistical power"
    }
)
```

---

## API Documentation

### Core Endpoints

#### Workflow Management

```
POST   /research/submit           Submit new research request
GET    /research/{request_id}     Get request status
GET    /research/active           List active requests
```

#### Approval Workflow

```
GET    /approvals/pending              Get pending approvals
GET    /approvals/{approval_id}        Get approval details
POST   /approvals/{approval_id}/respond  Approve/reject/modify
POST   /approvals/scope-change         Request scope change
GET    /approvals/request/{request_id} Get all approvals for request
POST   /approvals/check-timeouts       Check for timed out approvals
```

#### Analytics

```
POST   /analytics/execute              Execute SQL-on-FHIR ViewDefinition
GET    /analytics/view-definitions     List available ViewDefinitions
GET    /analytics/schema/{view_name}   Get ViewDefinition schema
```

#### Health & Monitoring

```
GET    /health           System health check
GET    /health/ready     Readiness probe
GET    /health/metrics   System metrics
```

Complete API documentation available at `/docs` when server is running.

---

## Human-in-Loop Approval Workflow

### Critical SQL Approval Process

```
1. Phenotype Agent generates SQL query from requirements
2. System creates approval request (status: pending)
3. Coordinator Agent notifies informatician via email
4. Informatician reviews SQL in Admin Dashboard
5. Decision options:
   - Approve: SQL executes, workflow continues
   - Modify: SQL updated, then executes
   - Reject: Returns to Phenotype Agent with feedback
6. Complete audit trail logged
```

### Approval Data Structure

```json
{
  "approval_id": 42,
  "request_id": "REQ-20251012-ABC123",
  "approval_type": "phenotype_sql",
  "submitted_at": "2025-10-12T10:30:00Z",
  "timeout_at": "2025-10-13T10:30:00Z",
  "approval_data": {
    "sql_query": "SELECT patient_id, birth_date...",
    "estimated_cohort": 347,
    "feasibility_score": 0.87,
    "warnings": [],
    "recommendations": []
  }
}
```

### Timeout Handling

- Automatic escalation after configured timeout period
- Escalation records created with severity assessment
- Admin notifications for delayed approvals
- Configurable timeout periods per approval type

---

## Performance

### Benchmark Results

| Metric | Before Optimization | After Optimization | Improvement |
|--------|---------------------|--------------------|--------------|
| Repeated Query Execution | 116.2s | 0.101s | **1151x faster** |
| Resource Processing | 45.3s | 30.1s | **1.5x faster** |
| Cache Hit Rate | 0% | 95% | N/A |
| Workflow Turnaround | 2-3 weeks | 4-8 hours | **95% faster** |

### Scalability

- **Concurrent Requests**: Supports 100+ simultaneous workflows
- **Database**: Tested with 1M+ patient records
- **Cache Size**: Configurable, default 1000 queries
- **API Throughput**: 500+ requests/second

---

## Configuration

### Environment Variables

Create `.env` file from `.env.example`:

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-api03-your-key-here

# Database
DATABASE_URL=sqlite+aiosqlite:///./dev.db
# Or PostgreSQL: postgresql+asyncpg://user:pass@localhost/dbname

# LangSmith Observability (Sprint 5)
LANGCHAIN_TRACING_V2=true
LANGCHAIN_ENDPOINT=https://api.smith.langchain.com
LANGCHAIN_API_KEY=lsv2_pt_your-langsmith-key-here
LANGCHAIN_PROJECT=researchflow-production

# Performance
ENABLE_QUERY_CACHE=true
CACHE_TTL_SECONDS=300
MAX_CACHE_SIZE=1000

# Timeouts (hours)
APPROVAL_TIMEOUT_REQUIREMENTS=24
APPROVAL_TIMEOUT_SQL=24
APPROVAL_TIMEOUT_EXTRACTION=12
APPROVAL_TIMEOUT_QA=24
APPROVAL_TIMEOUT_SCOPE_CHANGE=48

# Agent Configuration
MAX_AGENT_RETRIES=3
AGENT_RETRY_DELAY_SECONDS=5

# Security
A2A_JWT_SECRET=your-secret-key-here
```

---

## Testing

### Run Test Suite

```bash
# All tests
pytest

# With coverage
pytest --cov=app --cov-report=html

# Specific test file
pytest tests/test_approval_workflow.py

# Integration tests
pytest tests/integration/
```

### Test Approval Workflow

```bash
# Run approval workflow test script
python scripts/test_approval_workflow.py
```

**Test Coverage**: 85%+ across core modules

---

## Troubleshooting

### Common Installation Issues

#### 1. Missing `aiosqlite` Module

**Error**: `ModuleNotFoundError: No module named 'aiosqlite'`

**Solution**:
```bash
# Install aiosqlite specifically
pip install aiosqlite==0.19.0

# Or install all dependencies
pip install -r config/requirements.txt
```

**Note**: If full installation fails on scipy (requires Fortran compiler), you can run the API server without it. Scipy is only needed for research notebook analytics.

#### 2. Mixed Python Version in Virtual Environment

**Error**: `ImportError: cannot import name 'Undefined' from 'pydantic.fields'`

**Cause**: Virtual environment has mixed Python 3.11 and 3.13 packages

**Solution - Recreate virtual environment**:
```bash
# Remove old venv
rm -rf .venv

# Create new venv with specific Python version
python3.11 -m venv .venv  # Or python3.13
source .venv/bin/activate

# Install core dependencies
pip install --upgrade pip
pip install aiosqlite fastapi uvicorn httpx sqlalchemy python-dotenv anthropic
pip install python-jose[cryptography] streamlit alembic asyncpg

# Install LangChain/LangGraph dependencies
pip install langchain langchain-anthropic langgraph langsmith
```

#### 3. Pydantic Version Conflicts

**Error**: `pydantic>=2.7.4 required but you have pydantic 1.10.12`

**Solution - Upgrade to compatible versions**:
```bash
pip install --upgrade fastapi pydantic uvicorn
```

**Note**: The requirements.txt may have outdated versions. Use the latest compatible versions:
- FastAPI: 0.100+
- Pydantic: 2.7+
- LangChain: 0.3+

#### 4. LangSmith Traces Not Appearing

**Error**: No traces showing up in LangSmith dashboard

**Solutions**:
1. Verify environment variables in `.env`:
   ```bash
   LANGCHAIN_TRACING_V2=true
   LANGCHAIN_API_KEY=lsv2_pt_...
   LANGCHAIN_PROJECT=researchflow-production
   ```

2. Test LangSmith connection:
   ```python
   from langsmith import Client
   client = Client()  # Should not raise errors
   ```

3. Wait 5-10 seconds for traces to appear (async upload)
4. Refresh dashboard page
5. Check firewall allows HTTPS to `api.smith.langchain.com`

### Database Issues

#### SQLite Permission Errors

**Error**: `PermissionError: [Errno 13] Permission denied: './dev.db'`

**Solution**:
```bash
# Ensure current directory is writable
chmod +w .

# Or use absolute path in .env
DATABASE_URL=sqlite+aiosqlite:////absolute/path/to/dev.db
```

#### PostgreSQL Connection Failures

**Error**: `could not connect to server: Connection refused`

**Solution**:
```bash
# Check PostgreSQL is running
psql -U postgres -c "SELECT 1"

# Verify connection string in .env
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/dbname
```

### Running the Server

#### Port Already in Use

**Error**: `Error: [Errno 48] Address already in use`

**Solution**:
```bash
# Find and kill process on port 8000
lsof -ti:8000 | xargs kill -9

# Or use a different port
uvicorn app.main:app --port 8001
```

#### Import Errors on Startup

**Error**: Various `ModuleNotFoundError` or `ImportError`

**Solution**:
```bash
# Verify you're in the virtual environment
which python  # Should show .venv/bin/python

# Reinstall dependencies
pip install --force-reinstall -r config/requirements.txt
```

### Getting Help

If issues persist:
1. Check [GitHub Issues](https://github.com/yourusername/researchflow/issues)
2. Review complete setup guide: `docs/SETUP_GUIDE.md`
3. Enable debug logging: `export LOG_LEVEL=DEBUG`
4. Test with minimal configuration (SQLite, no LangSmith)

---

## Documentation

### User Guides

- [Setup Guide](docs/SETUP_GUIDE.md) - Complete installation instructions
- [Research Notebook Guide](docs/RESEARCH_NOTEBOOK_GUIDE.md) - Researcher portal usage
- [Approval Workflow Guide](docs/APPROVAL_WORKFLOW_GUIDE.md) - Human-in-loop workflow
- [Quick Reference](docs/QUICK_REFERENCE.md) - Commands and key concepts
- **[LangSmith Dashboard Guide](docs/LANGSMITH_DASHBOARD_GUIDE.md)** ⭐ NEW - Observability & monitoring
- **[LangSmith Workflow Traces](docs/LANGSMITH_WORKFLOW_TRACES.md)** ⭐ NEW - All execution paths & trace patterns

### Technical Documentation

- [Architecture Overview](docs/RESEARCHFLOW_README.md) - Complete system architecture
- [SQL-on-FHIR v2](docs/SQL_ON_FHIR_V2.md) - ViewDefinition implementation
- [Text-to-SQL Flow](docs/TEXT_TO_SQL_FLOW.md) - LLM conversation processing
- [Implementation Summary](docs/IMPLEMENTATION_SUMMARY.md) - Complete feature list
- [Gap Analysis & Roadmap](docs/GAP_ANALYSIS_AND_ROADMAP.md) - Production readiness

### Implementation Reports

- [Phase 1: Database Persistence](docs/implementation/PHASE1_COMPLETE.md)
- [Phase 2-3: Performance Optimization](docs/implementation/PHASE2_PHASE3_COMPLETE.md)
- [Query Caching Implementation](docs/implementation/CACHING_COMPLETE.md)
- [Parallel Processing](docs/implementation/PARALLEL_PROCESSING_COMPLETE.md)
- [Human-in-Loop Enhancement](docs/implementation/HUMAN_IN_LOOP_COMPLETE.md)
- [Approval Workflow Test Results](docs/implementation/APPROVAL_WORKFLOW_TEST_RESULTS.md)

### Sprint Documentation

- [Sprint 5: LangSmith Observability](docs/sprints/SPRINT_05_LANGSMITH_OBSERVABILITY.md) - Sprint plan
- [Sprint 5: Progress Report](docs/sprints/SPRINT_05_PROGRESS_REPORT.md) - Implementation progress
- **[Sprint 5: Completion Summary](docs/sprints/SPRINT_05_COMPLETION_SUMMARY.md)** ⭐ NEW - Final deliverables

---

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

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

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## Citation

If you use ResearchFlow in your research, please cite:

```bibtex
@software{researchflow2025,
  title = {ResearchFlow: AI-Powered Clinical Research Data Automation},
  author = {Your Name},
  year = {2025},
  url = {https://github.com/yourusername/researchflow},
  version = {2.0}
}
```

---

## Acknowledgments

- Built with [FastAPI](https://fastapi.tiangolo.com/)
- LLM integration via [Anthropic Claude API](https://www.anthropic.com/)
- SQL-on-FHIR v2 specification by [HL7 FHIR](https://hl7.org/fhir/)
- UI powered by [Streamlit](https://streamlit.io/)

---

## Project Status

**Version**: 2.0.0
**Status**: Production-Ready with Human-in-Loop Enhancements
**Last Updated**: October 2025

### Statistics

- **15,000+** lines of production code
- **7** autonomous agents
- **8** database tables
- **20** workflow states
- **25+** API endpoints
- **85%+** test coverage

### Roadmap

**Short Term (1-2 weeks)**
- Enhanced approval UI in admin dashboard
- Email server integration via MCP

**Medium Term (1-2 months)**
- REDCap delivery integration
- Advanced analytics dashboard
- Multi-tenant support

**Long Term (3-6 months)**
- Machine learning for cohort optimization
- Real-time collaboration features
- Mobile app for approvals

---

For questions, issues, or feature requests, please use [GitHub Issues](https://github.com/yourusername/researchflow/issues).
