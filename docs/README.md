# ResearchFlow Documentation

Welcome to the ResearchFlow documentation! This guide helps you navigate the extensive documentation for understanding, installing, and operating the ResearchFlow AI-powered clinical research data automation system.

---

## 🚀 Quick Start

**New to ResearchFlow?** Start here:

1. **[../README.md](../README.md)** - Project overview and key features
2. **[SETUP_GUIDE.md](SETUP_GUIDE.md)** - Installation instructions (3 steps)
3. **[QUICK_REFERENCE.md](QUICK_REFERENCE.md)** - Common commands and troubleshooting
4. **[DEMO_GUIDE.md](DEMO_GUIDE.md)** - Walkthrough demo

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

- **[DEMO_GUIDE.md](DEMO_GUIDE.md)** - Interactive demo
  - Step-by-step walkthrough
  - Example research requests
  - Expected results

### User Guides
- **[RESEARCHFLOW_README.md](RESEARCHFLOW_README.md)** - Full architecture guide
  - Multi-agent system overview
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

- **[APPROVAL_WORKFLOW_GUIDE.md](APPROVAL_WORKFLOW_GUIDE.md)** - Human-in-loop workflow
  - Critical approval gates
  - SQL review process
  - Requirements validation

### Technical Implementation
- **[SQL_ON_FHIR_V2.md](SQL_ON_FHIR_V2.md)** - FHIR analytics
  - ViewDefinition system
  - Materialized views
  - Query optimization

- **[MATERIALIZED_VIEWS.md](MATERIALIZED_VIEWS.md)** - Performance optimization
  - 10-100x query speedup
  - View management
  - Refresh strategies

- **[MATERIALIZED_VIEWS_ARCHITECTURE.md](MATERIALIZED_VIEWS_ARCHITECTURE.md)** - Lambda architecture
  - Batch layer (materialized views)
  - Speed layer (Redis cache)
  - Serving layer (HybridRunner)

- **[MULTI_PROVIDER_LLM.md](MULTI_PROVIDER_LLM.md)** - LLM integration
  - Claude + OpenAI/Ollama setup
  - 60% cost reduction
  - Provider routing logic

- **[POSTGRES_RUNNER_IMPLEMENTATION.md](POSTGRES_RUNNER_IMPLEMENTATION.md)** - In-database runner
  - PostgreSQL implementation
  - Performance benchmarks
  - Query execution

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
- **[SQL_ON_FHIR_TESTING_GUIDE.md](SQL_ON_FHIR_TESTING_GUIDE.md)** - SQL testing
  - Test data setup (Synthea)
  - Writing SQL tests
  - Integration testing

- **[TEST_SUITE_ORGANIZATION.md](TEST_SUITE_ORGANIZATION.md)** - Test structure
  - Unit, integration, E2E tests
  - Test file organization
  - Running specific test suites

### Test Results
- **[sprints/SPRINT_05_5_TEST_RESULTS.md](sprints/SPRINT_05_5_TEST_RESULTS.md)** - Lambda architecture
  - 29 comprehensive tests
  - 100% pass rate
  - Performance benchmarks

- **[sprints/E2E_TESTING_REPORT.md](sprints/E2E_TESTING_REPORT.md)** - End-to-end tests
  - Full workflow validation
  - Integration test coverage

- **[TEST_EXECUTION_RESULTS.md](TEST_EXECUTION_RESULTS.md)** - Test summary
  - Overall statistics
  - Coverage reports
  - Failure analysis

- **[implementation/TEST_RESULTS.md](implementation/TEST_RESULTS.md)** - Implementation tests
- **[implementation/APPROVAL_WORKFLOW_TEST_RESULTS.md](implementation/APPROVAL_WORKFLOW_TEST_RESULTS.md)** - Approval workflow tests
- **[PRIORITY_0_TESTS_SUMMARY.md](PRIORITY_0_TESTS_SUMMARY.md)** - Priority 0 test results
- **[RESEARCHER_PORTAL_TESTING.md](RESEARCHER_PORTAL_TESTING.md)** - Portal testing

---

## 📋 Sprint Documentation

ResearchFlow follows an agile sprint model. Track our progress:

- **[sprints/SPRINT_TRACKER.md](sprints/SPRINT_TRACKER.md)** - Master tracker
  - 18 total sprints planned
  - 8 sprints completed (44.44%)
  - Current: Sprint 6 (Security Baseline)

### Completed Sprints
1. [SPRINT_01_REQUIREMENTS_AGENT.md](sprints/SPRINT_01_REQUIREMENTS_AGENT.md) - Requirements Agent
2. [SPRINT_02_SIMPLE_WORKFLOW.md](sprints/SPRINT_02_SIMPLE_WORKFLOW.md) - Simple Workflow
3. [SPRINT_03_FULL_WORKFLOW.md](sprints/SPRINT_03_FULL_WORKFLOW.md) - Full Multi-Agent Workflow
4. [SPRINT_04_5_MATERIALIZED_VIEWS.md](sprints/SPRINT_04_5_MATERIALIZED_VIEWS.md) - Materialized Views
5. [SPRINT_05_LANGSMITH_OBSERVABILITY.md](sprints/SPRINT_05_LANGSMITH_OBSERVABILITY.md) - LangSmith Observability
6. [SPRINT_05_5_SPEED_LAYER.md](sprints/SPRINT_05_5_SPEED_LAYER.md) - Lambda Architecture Speed Layer
7. [SPRINT_05_COMPLETION_SUMMARY.md](sprints/SPRINT_05_COMPLETION_SUMMARY.md) - Sprint 5 summary
8. [SPRINT_05_PROGRESS_REPORT.md](sprints/SPRINT_05_PROGRESS_REPORT.md) - Sprint 5 progress

### Current Sprint
- **[sprints/SPRINT_06_SECURITY_BASELINE.md](sprints/SPRINT_06_SECURITY_BASELINE.md)** - Security Baseline (3 weeks)
  - Week 1: Authentication & Authorization (JWT, RBAC)
  - Week 2: SQL Injection Prevention & Input Validation
  - Week 3: PHI Audit Logging & Encryption
  - Goal: HIPAA compliance

### Sprint Planning
- [SPRINT_03_STATE_MAPPING.md](sprints/SPRINT_03_STATE_MAPPING.md) - State mapping
- [SPRINT_04_DECISION.md](sprints/SPRINT_04_DECISION.md) - Sprint 4 decision
- [SPRINT_TEMPLATE.md](sprints/SPRINT_TEMPLATE.md) - Sprint template

---

## 🏗️ Architecture

- **[ARCHITECTURE_ALIGNMENT_ANALYSIS.md](ARCHITECTURE_ALIGNMENT_ANALYSIS.md)** - Architecture alignment
  - Design decisions
  - Component interactions
  - System boundaries

- **[architecture/ArchitectureAnalysis.md](architecture/ArchitectureAnalysis.md)** - Deep dive
  - Detailed component analysis
  - Data flow diagrams
  - Performance considerations

- **[DESIGN_SYSTEM.md](DESIGN_SYSTEM.md)** - UI design system
  - Color palette
  - Typography
  - Component library
  - Accessibility guidelines

---

## 🔒 Security & Compliance

- **[../SECURITY.md](../SECURITY.md)** - Security policies
  - Vulnerability reporting
  - Security best practices
  - Responsible disclosure

- **[sprints/SPRINT_06_SECURITY_BASELINE.md](sprints/SPRINT_06_SECURITY_BASELINE.md)** - Security implementation
  - HIPAA compliance checklist
  - Authentication & authorization
  - SQL injection prevention
  - PHI audit logging
  - Encryption implementation

---

## 📊 Observability & Monitoring

- **[LANGSMITH_DASHBOARD_GUIDE.md](LANGSMITH_DASHBOARD_GUIDE.md)** - LangSmith observability
  - Workflow tracing
  - Performance monitoring
  - Debugging workflows

- **[LANGSMITH_WORKFLOW_TRACES.md](LANGSMITH_WORKFLOW_TRACES.md)** - Trace examples
  - Sample traces
  - Trace analysis
  - Performance insights

- **[LANGSMITH_DIAGRAM_GENERATION_GUIDE.md](LANGSMITH_DIAGRAM_GENERATION_GUIDE.md)** - Diagram generation
  - LangGraph diagram export
  - Workflow visualization

---

## 🚀 Implementation Reports

Feature completion reports documenting implementation details:

- **[implementation/PHASE1_COMPLETE.md](implementation/PHASE1_COMPLETE.md)** - Database persistence
- **[implementation/PHASE2_PHASE3_COMPLETE.md](implementation/PHASE2_PHASE3_COMPLETE.md)** - Performance & production hardening
- **[implementation/CACHING_COMPLETE.md](implementation/CACHING_COMPLETE.md)** - Query caching (1151x speedup)
- **[implementation/PARALLEL_PROCESSING_COMPLETE.md](implementation/PARALLEL_PROCESSING_COMPLETE.md)** - Parallel processing
- **[implementation/HEALTHCHECK_COMPLETE.md](implementation/HEALTHCHECK_COMPLETE.md)** - Health monitoring
- **[implementation/HUMAN_IN_LOOP_COMPLETE.md](implementation/HUMAN_IN_LOOP_COMPLETE.md)** - Human-in-loop approvals
- **[implementation/SETUP_COMPLETE.md](implementation/SETUP_COMPLETE.md)** - Setup completion
- **[implementation/QUICK_START_COMPLETE.md](implementation/QUICK_START_COMPLETE.md)** - Quick start verification

---

## 🔬 Research & Evaluation

- **[LANGCHAIN_COMPARISON.md](LANGCHAIN_COMPARISON.md)** - LangChain vs custom agents
  - Evaluation criteria
  - Decision rationale
  - Migration considerations

- **[LANGCHAIN_EVALUATION.md](LANGCHAIN_EVALUATION.md)** - LangChain evaluation
  - Features analysis
  - Performance benchmarks
  - Integration complexity

- **[ResearchFlow PRD.md](ResearchFlow%20PRD.md)** - Original product requirements
  - User stories
  - Success criteria
  - MVP definition

---

## 📖 Planning & Roadmap

- **[GAP_ANALYSIS_AND_ROADMAP.md](GAP_ANALYSIS_AND_ROADMAP.md)** - Product roadmap
  - Current status (44.44% complete)
  - Future features
  - 8-month implementation plan

- **[HUMAN_IN_LOOP_ENHANCEMENT_ROADMAP.md](HUMAN_IN_LOOP_ENHANCEMENT_ROADMAP.md)** - Human-in-loop roadmap
  - Approval workflow enhancements
  - Implementation phases

- **[NEXT_STEPS.md](NEXT_STEPS.md)** - Next development steps
  - Planned features
  - Technical debt
  - Optimization opportunities

---

## 🗂️ Legacy & Historical

- **[legacy/](legacy/)** - Legacy documentation archive
  - Previous architecture versions
  - Deprecated features
  - Migration guides

---

## 📦 System Overview

ResearchFlow is a multi-agent AI system automating clinical research data requests:

### Components
- **6 AI Agents**: Requirements, Phenotype, Calendar, Extraction, QA, Delivery
- **SQL-on-FHIR v2**: Real-time analytics on FHIR data
- **Lambda Architecture**: Batch layer (materialized views) + speed layer (Redis) + serving layer
- **LLM Integration**: Claude API + optional OpenAI/Ollama
- **Web UIs**: Research Notebook (port 8501) + Admin Dashboard (port 8502)

### Key Features
- ✅ Database persistence with audit trail
- ✅ Query caching (1151x speedup)
- ✅ Parallel processing (1.5x faster)
- ✅ Health monitoring endpoints
- ✅ SQL-on-FHIR v2 with ViewDefinitions
- ✅ Natural language query interface
- ✅ Human-in-loop approval gates
- ✅ Multi-provider LLM routing (60% cost reduction)
- ✅ Lambda architecture (10-100x speedup)

### Services

| Service | Port | URL |
|---------|------|-----|
| Research Notebook | 8501 | http://localhost:8501 |
| Admin Dashboard | 8502 | http://localhost:8502 |
| API Server | 8000 | http://localhost:8000 |
| HAPI FHIR | 8081 | http://localhost:8081/fhir |
| PostgreSQL (HAPI) | 5433 | localhost:5433 |
| PostgreSQL (App) | 5432 | localhost:5432 |

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
│   ├── QUICK_REFERENCE.md
│   └── DEMO_GUIDE.md
├── Core Documentation/
│   ├── RESEARCHFLOW_README.md
│   ├── TEXT_TO_SQL_FLOW.md
│   └── API_EXAMPLES.md
├── Technical/
│   ├── SQL_ON_FHIR_V2.md
│   ├── MATERIALIZED_VIEWS_ARCHITECTURE.md
│   └── MULTI_PROVIDER_LLM.md
├── Testing/
│   ├── SQL_ON_FHIR_TESTING_GUIDE.md
│   └── TEST_SUITE_ORGANIZATION.md
├── Architecture/
│   └── architecture/
├── Sprints/
│   └── sprints/
└── Implementation/
    └── implementation/
```

---

## 📊 Project Status

- **Status**: Active Development (Sprint 6 - Security Baseline)
- **Completion**: 44.44% (8/18 sprints)
- **Test Coverage**: 29 comprehensive tests (100% pass rate)
- **Performance**: 10-100x speedup (materialized views), 1151x (caching)
- **Cost Optimization**: 60% LLM cost reduction
- **Documentation**: 60+ markdown files

---

## 📜 License

MIT License - See [../LICENSE](../LICENSE)

---

**Last Updated**: 2025-10-30
**Documentation Version**: 2.0
**Project Version**: Sprint 6 (Security Baseline)

