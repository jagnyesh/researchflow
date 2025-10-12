# ResearchFlow Documentation

Complete documentation for the ResearchFlow AI-powered clinical research data automation system.

## Table of Contents

### Getting Started
- [README.md](../README.md) - Project overview and introduction
- [SETUP_GUIDE.md](SETUP_GUIDE.md) - Complete installation and setup instructions
- [QUICK_REFERENCE.md](QUICK_REFERENCE.md) - Commands, key concepts, and quick tips
- [QUICKSTART_SQL_ON_FHIR.md](QUICKSTART_SQL_ON_FHIR.md) - Quick start guide for SQL-on-FHIR

### User Guides
- [RESEARCHFLOW_README.md](RESEARCHFLOW_README.md) - Full system architecture and features
- [RESEARCH_NOTEBOOK_GUIDE.md](RESEARCH_NOTEBOOK_GUIDE.md) - Interactive notebook user guide
- [API_EXAMPLES.md](API_EXAMPLES.md) - API usage examples
- [SQL_ON_FHIR_TESTING_GUIDE.md](SQL_ON_FHIR_TESTING_GUIDE.md) - Testing SQL-on-FHIR functionality
- [APPROVAL_WORKFLOW_GUIDE.md](APPROVAL_WORKFLOW_GUIDE.md) - **NEW** Human-in-loop approval workflow guide

### Technical Documentation
- [SQL_ON_FHIR_V2.md](SQL_ON_FHIR_V2.md) - SQL-on-FHIR v2 implementation guide
- [TEXT_TO_SQL_FLOW.md](TEXT_TO_SQL_FLOW.md) - LLM conversation to SQL explained
- [POSTGRES_RUNNER_IMPLEMENTATION.md](POSTGRES_RUNNER_IMPLEMENTATION.md) - In-database runner details
- [GAP_ANALYSIS_AND_ROADMAP.md](GAP_ANALYSIS_AND_ROADMAP.md) - Production readiness and 8-month roadmap
- [HUMAN_IN_LOOP_ENHANCEMENT_ROADMAP.md](HUMAN_IN_LOOP_ENHANCEMENT_ROADMAP.md) - **NEW** Human-in-loop implementation roadmap
- [add_params.md](add_params.md) - Best practices for Text2SQL architecture

### Architecture
- [architecture/](architecture/) - System architecture diagrams and analysis
 - `ArchitectureAnalysis.md` - Detailed architecture analysis
 - `architecture.puml` - PlantUML system diagram (24 data flows)
 - Diagram images (.png files)

### Implementation Reports
- [implementation/](implementation/) - Feature implementation completion reports
 - `PHASE1_COMPLETE.md` - Database persistence implementation
 - `PHASE2_PHASE3_COMPLETE.md` - Performance optimization and production hardening
 - `CACHING_COMPLETE.md` - Query caching (1151x speedup)
 - `PARALLEL_PROCESSING_COMPLETE.md` - Parallel processing (1.5x speedup)
 - `HEALTHCHECK_COMPLETE.md` - Health monitoring endpoints
 - `SETUP_COMPLETE.md` - Initial setup completion
 - `QUICK_START_COMPLETE.md` - Quick start verification
 - `TEST_RESULTS.md` - Test execution results

### Planning Documents
- [NEXT_STEPS.md](NEXT_STEPS.md) - Roadmap and future enhancements
- [ResearchFlow PRD.md](ResearchFlow PRD.md) - Original product requirements

### Diagrams
- [DIAGRAMS_README.md](DIAGRAMS_README.md) - How to view and generate diagrams

## Quick Start

1. **First Time Setup**: Read [SETUP_GUIDE.md](SETUP_GUIDE.md)
2. **Daily Usage**: See [QUICK_REFERENCE.md](QUICK_REFERENCE.md)
3. **For Researchers**: Check out [RESEARCH_NOTEBOOK_GUIDE.md](RESEARCH_NOTEBOOK_GUIDE.md)
4. **For Developers**: Review [RESEARCHFLOW_README.md](RESEARCHFLOW_README.md)

## System Overview

ResearchFlow is a multi-agent AI system that automates clinical research data requests:

- **6 AI Agents**: Requirements, Phenotype, Calendar, Extraction, QA, Delivery
- **SQL-on-FHIR v2**: Real-time analytics on FHIR data
- **Two Runners**: PostgreSQL (fast, in-database) + In-Memory (REST API)
- **LLM Integration**: Claude API for natural language processing
- **Web UIs**: Research Notebook + Admin Dashboard

## Key Features Implemented

[x] **Database Persistence** - State survives restarts with audit trail
[x] **Query Caching** - 1151x speedup for repeated queries
[x] **Parallel Processing** - 1.5x faster resource processing
[x] **Health Monitoring** - 3 production-ready endpoints
[x] **SQL-on-FHIR v2** - ViewDefinitions + dual runners
[x] **Natural Language Queries** - Interactive notebook interface
[x] **Human-in-Loop Approvals** - **NEW** Critical approval gates for SQL review, requirements validation, scope changes

## Services

| Service | Port | URL |
|---------|------|-----|
| Research Notebook | 8501 | http://localhost:8501 |
| Admin Dashboard | 8502 | http://localhost:8502 |
| API Server | 8000 | http://localhost:8000 |
| HAPI FHIR | 8081 | http://localhost:8081/fhir |
| PostgreSQL (HAPI) | 5433 | localhost:5433 |
| PostgreSQL (App) | 5432 | localhost:5432 |

## Documentation by Role

### For Researchers
1. [RESEARCH_NOTEBOOK_GUIDE.md](RESEARCH_NOTEBOOK_GUIDE.md)
2. [QUICK_REFERENCE.md](QUICK_REFERENCE.md)
3. [API_EXAMPLES.md](API_EXAMPLES.md)

### For Developers
1. [RESEARCHFLOW_README.md](RESEARCHFLOW_README.md)
2. [SQL_ON_FHIR_V2.md](SQL_ON_FHIR_V2.md)
3. [TEXT_TO_SQL_FLOW.md](TEXT_TO_SQL_FLOW.md)
4. [GAP_ANALYSIS_AND_ROADMAP.md](GAP_ANALYSIS_AND_ROADMAP.md)

### For DevOps
1. [SETUP_GUIDE.md](SETUP_GUIDE.md)
2. [implementation/HEALTHCHECK_COMPLETE.md](implementation/HEALTHCHECK_COMPLETE.md)
3. [implementation/PHASE2_PHASE3_COMPLETE.md](implementation/PHASE2_PHASE3_COMPLETE.md)

### For System Architects
1. [architecture/ArchitectureAnalysis.md](architecture/ArchitectureAnalysis.md)
2. [POSTGRES_RUNNER_IMPLEMENTATION.md](POSTGRES_RUNNER_IMPLEMENTATION.md)
3. [add_params.md](add_params.md)

## Troubleshooting

See the troubleshooting sections in:
- [SETUP_GUIDE.md](SETUP_GUIDE.md#troubleshooting)
- [SQL_ON_FHIR_V2.md](SQL_ON_FHIR_V2.md#troubleshooting)
- [QUICK_REFERENCE.md](QUICK_REFERENCE.md)

## License

MIT License - See [../LICENSE](../LICENSE)

## 🤝 Contributing

ResearchFlow is an AI-powered research automation platform. For contribution guidelines, see the main [README.md](../README.md).

---

**Last Updated**: October 2025
**Version**: 1.0 (Production-Ready)
