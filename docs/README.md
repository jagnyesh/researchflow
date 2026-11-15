# ResearchFlow Documentation

Welcome to the ResearchFlow documentation! This guide helps you navigate the extensive documentation for understanding, installing, and operating the ResearchFlow AI-powered clinical research data automation system.

---

## 🚀 Quick Start

**New to ResearchFlow?** Start here:

1. **[../README.md](../README.md)** - Project overview and key features
2. **[SETUP_GUIDE.md](SETUP_GUIDE.md)** - Installation instructions (3 steps)
3. **[QUICK_REFERENCE.md](QUICK_REFERENCE.md)** - Common commands and troubleshooting

---

## 📚 Documentation by Role

### 👩‍🔬 For Researchers
1. [RESEARCH_NOTEBOOK_GUIDE.md](RESEARCH_NOTEBOOK_GUIDE.md) - Interactive notebook interface
2. [API_EXAMPLES.md](API_EXAMPLES.md) - API usage examples
3. [QUICK_REFERENCE.md](QUICK_REFERENCE.md) - Commands and tips

### 💻 For Developers
1. [RESEARCHFLOW_README.md](RESEARCHFLOW_README.md) - Full system architecture
2. [SQL_ON_FHIR_V2.md](SQL_ON_FHIR_V2.md) - FHIR analytics implementation
3. [TEXT_TO_SQL_FLOW.md](TEXT_TO_SQL_FLOW.md) - Natural language to SQL
4. [../CLAUDE.md](../CLAUDE.md) - AI development context
5. [../CONTRIBUTING.md](../CONTRIBUTING.md) - Contribution guidelines

### ⚙️ For DevOps
1. [SETUP_GUIDE.md](SETUP_GUIDE.md) - Installation guide
2. [AUTO_REFRESH_SETUP.md](AUTO_REFRESH_SETUP.md) - Materialized view refresh
3. [implementation/HEALTHCHECK_COMPLETE.md](implementation/HEALTHCHECK_COMPLETE.md) - Health monitoring

### 🏗️ For System Architects
1. [architecture/ArchitectureAnalysis.md](architecture/ArchitectureAnalysis.md) - Architecture analysis
2. [MATERIALIZED_VIEWS_ARCHITECTURE.md](MATERIALIZED_VIEWS_ARCHITECTURE.md) - Lambda architecture
3. [add_params.md](add_params.md) - Best practices for Text2SQL
4. [GAP_ANALYSIS_AND_ROADMAP.md](GAP_ANALYSIS_AND_ROADMAP.md) - Product roadmap

---

## 📖 Core Documentation

### Getting Started
- **[SETUP_GUIDE.md](SETUP_GUIDE.md)** - Complete installation guide
  - Prerequisites, API keys, Docker setup
  - Local development without Docker
  - Troubleshooting common issues

- **[QUICK_REFERENCE.md](QUICK_REFERENCE.md)** - Commands & quick tips
  - Running the application
  - Testing commands
  - Common workflows


### User Guides
- **[RESEARCHFLOW_README.md](RESEARCHFLOW_README.md)** - Full architecture guide
  - Overview of the original design
  - Database schema
  - API endpoints

- **[RESEARCH_NOTEBOOK_GUIDE.md](RESEARCH_NOTEBOOK_GUIDE.md)** - Notebook interface
  - Jupyter-style notebooks
  - Interactive data exploration
  - Visualization tools

- **[TEXT_TO_SQL_FLOW.md](TEXT_TO_SQL_FLOW.md)** - Natural language workflow
  - Requirements extraction
  - SQL generation
  - Feasibility checking

- **[API_EXAMPLES.md](API_EXAMPLES.md)** - API usage
  - HTTP request examples
  - Response formats
  - Error handling

- **[API_AND_CONFIGURATION.md](API_AND_CONFIGURATION.md)** - API and configuration reference
  - Endpoints and example calls
  - Environment variables
  - Tests and fixes for common errors


### Technical Implementation
- **[SQL_ON_FHIR_V2.md](SQL_ON_FHIR_V2.md)** - FHIR analytics
  - ViewDefinition system
  - Materialized views
  - Query optimization

- **[MATERIALIZED_VIEWS.md](MATERIALIZED_VIEWS.md)** - Performance optimization
  - View management
  - Refresh strategies

- **[MATERIALIZED_VIEWS_ARCHITECTURE.md](MATERIALIZED_VIEWS_ARCHITECTURE.md)** - Lambda architecture
  - Batch layer (materialized views)
  - Speed layer (Redis cache)
  - Serving layer (HybridRunner)


- **[REFERENTIAL_INTEGRITY.md](REFERENTIAL_INTEGRITY.md)** - Database design
  - Foreign key relationships
  - Data consistency
  - Schema evolution

### Operations
- **[AUTO_REFRESH_SETUP.md](AUTO_REFRESH_SETUP.md)** - Materialized view refresh
  - Cron job configuration
  - Manual refresh commands
  - Monitoring refresh jobs

- **[DIAGRAMS_README.md](DIAGRAMS_README.md)** - Architecture diagrams
  - PlantUML diagram generation
  - Online diagram viewers
  - Workflow visualization

---

## 🧪 Testing & Quality

### Testing Guides
See the [testing/](testing/) directory (E2E guide, manual script, LangGraph test plan).

### Test Results
- **[sprints/archive/SPRINT_05_5_TEST_RESULTS.md](sprints/archive/SPRINT_05_5_TEST_RESULTS.md)** - Lambda architecture
  - Performance benchmarks

- **[sprints/archive/E2E_TESTING_REPORT.md](sprints/archive/E2E_TESTING_REPORT.md)** - End-to-end tests
  - Full workflow validation
  - Integration test coverage


- **[implementation/TEST_RESULTS.md](implementation/TEST_RESULTS.md)** - Implementation tests
- **[implementation/APPROVAL_WORKFLOW_TEST_RESULTS.md](implementation/APPROVAL_WORKFLOW_TEST_RESULTS.md)** - Approval workflow tests

---

## 📋 Sprint Documentation

For current sprint state, blockers, and what's in flight, see **[../CONTEXT.md](../CONTEXT.md)** at repo root. For architectural decisions across sprints, see **[decisions/INDEX.md](decisions/INDEX.md)** (append-only ADR log, one file per decision). For upcoming work, see **[../BACKLOG.md](../BACKLOG.md)**.

### Sprint Template
- [sprints/SPRINT_TEMPLATE.md](sprints/SPRINT_TEMPLATE.md) — boilerplate for new sprint reports

### Historical sprint reports

Archived in **[sprints/archive/](sprints/archive/)**. The original master tracker lives there as `SPRINT_TRACKER_v1.md`. Don't load these into context unless researching a specific past decision; the distilled record is in [`decisions/INDEX.md`](decisions/INDEX.md).

---

## 🏗️ Architecture

- **[ARCHITECTURE.md](ARCHITECTURE.md)** - Reference for the current code
  - Workflow graph and approval gates
  - Data layers and the `HybridRunner` wiring statement
  - Known gaps


- **[architecture/ArchitectureAnalysis.md](architecture/ArchitectureAnalysis.md)** - Deep dive
  - Detailed component analysis
  - Data flow diagrams
  - Performance considerations


---

## 🔒 Security & Compliance

- **[../SECURITY.md](../SECURITY.md)** - Security policies
  - Vulnerability reporting
  - Security best practices
  - Responsible disclosure

- **[sprints/SPRINT_06_IMPLEMENTATION.md](sprints/SPRINT_06_IMPLEMENTATION.md)** - Security implementation
  - HIPAA compliance checklist
  - Authentication & authorization
  - SQL injection prevention
  - PHI audit logging
  - Encryption implementation

---

## 📊 Observability & Monitoring

- **[observability/](observability/)** - LangSmith observability and debugging guides

---

## 🚀 Implementation Reports

Feature completion reports documenting implementation details:

- **[implementation/PHASE1_COMPLETE.md](implementation/PHASE1_COMPLETE.md)** - Database persistence
- **[implementation/PHASE2_PHASE3_COMPLETE.md](implementation/PHASE2_PHASE3_COMPLETE.md)** - Performance & production hardening
- **[implementation/CACHING_COMPLETE.md](implementation/CACHING_COMPLETE.md)** - Query caching
- **[implementation/PARALLEL_PROCESSING_COMPLETE.md](implementation/PARALLEL_PROCESSING_COMPLETE.md)** - Parallel processing
- **[implementation/HEALTHCHECK_COMPLETE.md](implementation/HEALTHCHECK_COMPLETE.md)** - Health monitoring
- **[implementation/HUMAN_IN_LOOP_COMPLETE.md](implementation/HUMAN_IN_LOOP_COMPLETE.md)** - Human-in-loop approvals
- **[implementation/SETUP_COMPLETE.md](implementation/SETUP_COMPLETE.md)** - Setup completion
- **[implementation/QUICK_START_COMPLETE.md](implementation/QUICK_START_COMPLETE.md)** - Quick start verification

---

## 🔬 Research & Evaluation


- **[ResearchFlow PRD.md](ResearchFlow%20PRD.md)** - Original product requirements
  - User stories
  - Success criteria
  - MVP definition

---

## 📖 Planning & Roadmap

- **[GAP_ANALYSIS_AND_ROADMAP.md](GAP_ANALYSIS_AND_ROADMAP.md)** - Product roadmap
  - Historical roadmap; current state is in [../CONTEXT.md](../CONTEXT.md)
  - Future features
  - 8-month implementation plan


---

## 🗂️ Legacy & Historical

- **[PROJECT_HISTORY.md](PROJECT_HISTORY.md)** - Project history
  - Why the docs say "workflow steps" and not "agents"
  - The four engineering arcs
  - What the Sprint 8 series taught, and the shipped log


---

## 📦 System Overview

ResearchFlow is a proof of concept for LLM-assisted clinical research data requests with human approval gates:

### Components
- **Five workflow steps**: Requirements, Phenotype, Extraction, QA, Delivery. The code calls each step an agent, and only Requirements calls an LLM.
- **SQL-on-FHIR v2**: Real-time analytics on FHIR data
- **Lambda Architecture**: Batch layer (materialized views) + speed layer (Redis) + serving layer
- **LLM Integration**: Claude API + optional OpenAI/Ollama
- **Web UIs**: Exploratory portal (port 8501), formal portal (port 8502), Admin Dashboard (port 8503)

### Services

| Service | Port | URL |
|---------|------|-----|
| Exploratory portal (Research Notebook) | 8501 | http://localhost:8501 |
| Formal portal (Researcher Portal) | 8502 | http://localhost:8502 |
| Admin Dashboard | 8503 | http://localhost:8503 |
| API Server | 8000 | http://localhost:8000 |
| HAPI FHIR | 8081 | http://localhost:8081/fhir |
| PostgreSQL (HAPI) | 5433 | localhost:5433 |
| PostgreSQL (App) | 5434 | localhost:5434 |

---

## 🤝 Contributing

ResearchFlow is an open-source AI-powered research automation platform.

- **[../CONTRIBUTING.md](../CONTRIBUTING.md)** - Contribution guidelines
  - Code style (Black formatter)
  - Pull request process
  - Issue templates

- **[../CLAUDE.md](../CLAUDE.md)** - AI development context
  - Project structure
  - Key components
  - Development workflow

- **[.github/ISSUE_TEMPLATE/](../.github/ISSUE_TEMPLATE/)** - Issue templates
  - Bug report template
  - Feature request template

- **[.github/PULL_REQUEST_TEMPLATE.md](../.github/PULL_REQUEST_TEMPLATE.md)** - PR template
  - PR checklist
  - Review guidelines

---

## 🎯 Troubleshooting

Common issues and solutions documented in:
- [SETUP_GUIDE.md](SETUP_GUIDE.md#troubleshooting)
- [SQL_ON_FHIR_V2.md](SQL_ON_FHIR_V2.md#troubleshooting)
- [QUICK_REFERENCE.md](QUICK_REFERENCE.md)

---

## 📝 Documentation Standards

When contributing documentation:

1. **Follow naming conventions**: `MY_DOC_NAME.md` (uppercase with underscores)
2. **Include standard sections**: Overview, Prerequisites, Instructions, Examples, Troubleshooting
3. **Keep docs current**: Update when code changes
4. **Use markdown features**: Code blocks, tables, links, images

---

## 🗺️ Quick Navigation

```
docs/
├── README.md (this file)
├── Getting Started/
│   ├── SETUP_GUIDE.md
│   └── QUICK_REFERENCE.md
├── Core Documentation/
│   ├── RESEARCHFLOW_README.md
│   ├── TEXT_TO_SQL_FLOW.md
│   └── API_EXAMPLES.md
├── Technical/
│   ├── SQL_ON_FHIR_V2.md
│   └── MATERIALIZED_VIEWS_ARCHITECTURE.md
├── Testing/
│   └── testing/
├── Architecture/
│   └── architecture/
├── Sprints/
│   └── sprints/
└── Implementation/
    └── implementation/
```

---

## 📊 Project Status

For current status, see [../CONTEXT.md](../CONTEXT.md). Plans are in [../BACKLOG.md](../BACKLOG.md). Several documents above predate the LangGraph migration; where they disagree with [ARCHITECTURE.md](ARCHITECTURE.md) or the code, those win.

---

## 📜 License

MIT License - See [../LICENSE](../LICENSE)
