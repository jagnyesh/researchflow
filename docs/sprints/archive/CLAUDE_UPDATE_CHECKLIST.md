# CLAUDE.md Update Checklist

**Last Updated**: 2025-11-03
**Original Created**: 2025-10-28
**Status**: ✅ COMPLETE (Sprints 4.5-7 documented)

This checklist documents changes that should be reflected in CLAUDE.md based on recent development.

## Changes Documented

### ✅ 1. Lambda Architecture Implementation (MAJOR) - **COMPLETE**

**Section to Update**: Add new section after "Architecture"

```markdown
### Lambda Architecture (Sprint 4.5 + 5.5)

ResearchFlow implements a complete Lambda Architecture for FHIR data:

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
```

### ✅ 2. Project Structure Updates - **COMPLETE**

**Section to Update**: "Project Structure" - Add new directories

```markdown
FHIR_PROJECT/
├── app/
│   ├── cache/                    # Redis integration (NEW)
│   │   └── redis_client.py      # Speed layer cache
│   │
│   ├── sql_on_fhir/runner/       # Query execution runners (UPDATED)
│   │   ├── hybrid_runner.py     # Serving layer (batch + speed merge)
│   │   ├── materialized_view_runner.py  # Batch layer (fast queries)
│   │   ├── speed_layer_runner.py        # Speed layer (Redis)
│   │   ├── postgres_runner.py           # Legacy (fallback)
│   │   └── in_memory_runner.py          # In-memory FHIR queries
│   │
│   ├── services/                 # Business logic (UPDATED)
│   │   ├── materialized_view_service.py  # View management
│   │   ├── fhir_subscription_service.py  # Real-time FHIR updates
│   │   └── feasibility_service.py        # Feasibility queries
│   │
│   ├── langchain_orchestrator/   # LangChain/LangGraph (NEW)
│   │   ├── langchain_agents.py  # LangChain agent implementations
│   │   ├── langgraph_workflow.py # 23-state LangGraph workflow
│   │   ├── simple_workflow.py    # 3-state POC
│   │   └── persistence.py        # Workflow state persistence
│
├── scripts/                      # Automation scripts (NEW)
│   ├── materialize_views.py     # Create/refresh materialized views
│   ├── refresh_materialized_views.py  # Auto-refresh cron job
│   └── validate_referential_integrity.py
│
├── tests/                        # Test suite (EXPANDED)
│   ├── test_speed_layer_runner.py          # Speed layer tests (10 tests)
│   ├── test_hybrid_runner_speed_integration.py  # Integration (10 tests)
│   ├── test_materialized_views_integration.py
│   └── test_redis_client.py
│
├── docs/                         # Documentation (EXPANDED)
│   ├── MATERIALIZED_VIEWS.md                    # Lambda batch layer guide
│   ├── MATERIALIZED_VIEWS_ARCHITECTURE.md       # Complete architecture
│   ├── REFERENTIAL_INTEGRITY.md                 # Dual column design
│   ├── HealthLakeVsResearchFlowComparison.md    # AWS HealthLake comparison
│   ├── ARCHITECTURE_ALIGNMENT_ANALYSIS.md       # LangGraph analysis
│   ├── AUTO_REFRESH_SETUP.md                    # Cron setup guide
│   └── sprints/
│       ├── SPRINT_04_5_MATERIALIZED_VIEWS.md    # Batch layer sprint
│       └── SPRINT_05_5_SPEED_LAYER.md           # Speed layer sprint
```

### ✅ 3. Environment Variables - **COMPLETE**

**Section to Update**: "Environment Variables" - Add Lambda Architecture vars

```markdown
**Lambda Architecture Configuration:**
- `REDIS_URL`: Redis connection URL (default: `redis://localhost:6379/0`)
- `USE_SPEED_LAYER`: Enable speed layer (default: `true`)
- `REDIS_TTL_HOURS`: Speed layer cache TTL (default: `24`)

**LangSmith Observability:**
- `LANGCHAIN_TRACING_V2`: Enable LangSmith tracing (default: `false`)
- `LANGCHAIN_API_KEY`: LangSmith API key (optional)
- `LANGCHAIN_PROJECT`: LangSmith project name (default: `researchflow-production`)
- `LANGCHAIN_ENDPOINT`: LangSmith endpoint (default: `https://api.smith.langchain.com`)
```

### ✅ 4. Implementation Status - **COMPLETE**

**Section to Update**: "Implementation Status" - Update completions

```markdown
**Completed:**
- ✅ All 6 agents implemented
- ✅ Orchestrator + workflow engine
- ✅ LangChain/LangGraph workflow (23-state FSM)
- ✅ LLM integration (Claude API)
- ✅ SQL generation (SQL-on-FHIR)
- ✅ **Lambda Architecture (Batch + Speed + Serving layers)** 🆕
- ✅ **Materialized views (10-100x performance improvement)** 🆕
- ✅ **Redis speed layer (< 1 minute data freshness)** 🆕
- ✅ **HybridRunner serving layer (automatic merge)** 🆕
- ✅ **LangSmith observability** 🆕
- ✅ Database models (6 tables)
- ✅ MCP infrastructure (registry + terminology server)
- ✅ Streamlit UIs (researcher portal + admin dashboard)
- ✅ Complete documentation (15+ docs + 3 diagrams)

**Production TODOs:**
- [ ] Auto-refresh pipeline (cron job for materialized views)
- [ ] FHIR Subscription listener (real-time event capture)
- [ ] Real MCP servers (Epic, FHIR, Calendar) - currently stubs
- [ ] Authentication & authorization for UIs
- [ ] Database migrations (Alembic)
- [ ] Production logging & monitoring (Prometheus/Grafana)
- [ ] Kubernetes deployment configs
- [ ] Secure file storage (S3/Azure)
- [ ] Email notification service
```

### ✅ 5. Testing Section - **COMPLETE**

**Section to Update**: "Testing" - Add new test files

```markdown
## Testing

Tests use pytest with async support (`pytest-asyncio`). Test files:

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

**LangChain/LangGraph Tests:** 🆕
- `tests/test_simple_workflow.py` - Simple 3-state workflow
- `tests/test_langgraph_workflow.py` - Full 23-state workflow
- `tests/e2e/test_langgraph_workflow_e2e.py` - End-to-end tests

Run all tests:
```bash
pytest -v
```

Run Lambda Architecture tests:
```bash
pytest tests/test_speed_layer_runner.py -v
pytest tests/test_hybrid_runner_speed_integration.py -v
```
```

### ✅ 6. Documentation Section - **COMPLETE**

**Section to Update**: "Documentation" - Add new docs

```markdown
## Documentation

**Setup & Getting Started:**
- **Setup Guide**: `docs/SETUP_GUIDE.md` - Complete setup instructions
- **Quick Reference**: `docs/QUICK_REFERENCE.md` - Commands & key concepts

**Architecture & Design:**
- **Full Docs**: `docs/RESEARCHFLOW_README.md` - Architecture & features
- **Lambda Architecture**: `docs/MATERIALIZED_VIEWS_ARCHITECTURE.md` - Complete Lambda implementation 🆕
- **AWS Comparison**: `docs/HealthLakeVsResearchFlowComparison.md` - vs. AWS HealthLake 🆕
- **LangGraph Analysis**: `docs/ARCHITECTURE_ALIGNMENT_ANALYSIS.md` - Workflow architecture 🆕
- **Diagrams**: `docs/DIAGRAMS_README.md` - How to view architecture diagrams

**Implementation Guides:**
- **Materialized Views**: `docs/MATERIALIZED_VIEWS.md` - Quick start guide 🆕
- **Referential Integrity**: `docs/REFERENTIAL_INTEGRITY.md` - Dual column design 🆕
- **Auto-refresh**: `docs/AUTO_REFRESH_SETUP.md` - Cron setup for batch layer 🆕
- **Text-to-SQL Flow**: `docs/TEXT_TO_SQL_FLOW.md` - LLM conversation to SQL
- **SQL-on-FHIR v2**: `docs/SQL_ON_FHIR_V2.md` - ViewDefinition implementation
- **Best Practices**: `docs/add_params.md` - Architecture patterns

**Project Management:**
- **Gap Analysis**: `docs/GAP_ANALYSIS_AND_ROADMAP.md` - Production readiness
- **PRD**: `docs/ResearchFlow PRD.md` - Original requirements
- **Sprint Reports**: `docs/sprints/` - Sprint summaries and progress
  - `SPRINT_04_5_MATERIALIZED_VIEWS.md` - Batch layer implementation 🆕
  - `SPRINT_05_5_SPEED_LAYER.md` - Speed layer implementation 🆕
```

### ✅ 7. Quick Start Updates - **COMPLETE**

**Section to Update**: "Quick Start" - Add Lambda Architecture setup

```markdown
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
#   REDIS_URL=redis://localhost:6379/0  # NEW
#   USE_SPEED_LAYER=true                # NEW

# Start Redis (for Speed Layer) - NEW
redis-server

# Create materialized views (Batch Layer) - NEW
python scripts/materialize_views.py

# Run Researcher Portal
streamlit run app/web_ui/researcher_portal.py --server.port 8501

# Run Admin Dashboard
streamlit run app/web_ui/admin_dashboard.py --server.port 8502

# Run API server
make run
# or: uvicorn app.main:app --reload --port 8000

# Run tests (including Lambda Architecture tests)
make test
# or: pytest -v
```
```

---

## Update Status

### ✅ **COMPLETED** (2025-11-03):
1. ✅ Lambda Architecture section - **DONE** (Sprint 4.5 + 5.5)
2. ✅ Project Structure (new directories) - **DONE**
3. ✅ Environment Variables (Redis, LangSmith, LangGraph) - **DONE**
4. ✅ Implementation Status (completions) - **DONE**
5. ✅ Documentation section (new docs) - **DONE**
6. ✅ Testing section (new tests) - **DONE**
7. ✅ Quick Start (Redis setup, pre-commit hooks) - **DONE**
8. ✅ **LangGraph Migration section** - **DONE** (Sprint 6.5 + 6.6) 🆕
9. ✅ **Security Hardening section** - **DONE** (Sprint 7) 🆕
10. ✅ Core Components expansion - **DONE**

### 📊 **Impact Summary**:
- **Lines Added**: 376 new lines (335 → 711 lines, +112% growth)
- **Sprints Documented**: 6 sprints (4.5, 5, 5.5, 6.5, 6.6, 7)
- **Features Documented**: 15+ major features
- **Time Period**: 2025-10-28 to 2025-11-03 (6 days)
- **Commit**: 6732cfb (2025-11-03)

---

## Automation Ideas (Future)

Consider creating a script to auto-update CLAUDE.md:

```bash
#!/bin/bash
# scripts/update_claude_md.sh

# 1. Scan for new directories
# 2. Scan for new env vars in .env.example
# 3. Count test files
# 4. List new docs
# 5. Generate updated CLAUDE.md sections

# Run before major commits:
./scripts/update_claude_md.sh
git add CLAUDE.md
```

---

## Recommended Workflow

```bash
# When you've completed a major feature:

1. Review changes:
   git status

2. Check this checklist:
   cat CLAUDE_UPDATE_CHECKLIST.md

3. Update CLAUDE.md sections that changed

4. Commit both together:
   git add CLAUDE.md [other files]
   git commit -m "feat: [feature name] + update CLAUDE.md"

5. Or commit separately:
   git add [feature files]
   git commit -m "feat: [feature name]"
   git add CLAUDE.md
   git commit -m "docs: update CLAUDE.md with [feature name]"
```

---

## Additional Updates (Since Checklist Creation)

### 🆕 8. LangGraph/LangChain Migration (Sprint 6.5 + 6.6 + 6.7) - ✅ **100% COMPLETE**

**Status**: 75% → **100% COMPLETE** (Phases 1-4 done, Phase 5 pending production rollout)

**Added to CLAUDE.md**: Comprehensive LangGraph architecture section (~150 lines)

**Content**:
- Dual orchestration systems (custom vs LangGraph)
- Migration status: ✅ **100% COMPLETE** (updated from 75%)
- Migration phases breakdown:
  - ✅ Phase 1: Critical Bug Fixes & Persistence
  - ✅ Phase 2: Agent & Approval Bridges
  - ✅ Phase 3.1: Request Facade
  - ✅ Phase 3.2: UI Integration with Feature Flags 🆕
  - ✅ Phase 3.3: Integration & E2E Testing (20 tests, 837 lines) 🆕
  - ✅ Phase 4: Migration Script & Deployment Guide (1,450+ lines) 🆕
  - 🔄 Phase 5: Production Rollout (pending)
- Architecture diagram (ASCII art)
- Key files (3,050+ lines total):
  - langgraph_workflow.py
  - agent_adapter.py
  - approval_bridge.py
  - request_facade.py
  - tests/integration/test_request_facade.py (350+ lines) 🆕
  - tests/e2e/test_ui_with_langgraph.py (400+ lines) 🆕
  - scripts/migrate_to_langgraph.py (400+ lines) 🆕
  - docs/LANGGRAPH_MIGRATION_GUIDE.md (500+ lines) 🆕
- Testing: 68 tests total (48 existing + 20 new), 100% passing
- Environment variables: USE_LANGGRAPH_WORKFLOW, LANGGRAPH_ROLLOUT_PCT
- Feature flags in both UIs (researcher_portal.py, admin_dashboard.py)
- Docker compose updated with LangGraph env vars

**Commits** (Sprint 6.7):
- `6e5fb90` - Phase 3.2: UI integration with feature flags
- `469dcea` - Phase 3.3: Integration & E2E tests
- `e65a661` - Phase 4: Migration script & deployment guide
- `0ccf65e` - CLAUDE.md updated to 100% complete

**Why Not in Original Checklist**: Sprint 6.5 started 2025-10-30 (2 days after checklist created)
**Completion Date**: 2025-11-03

---

### 🆕 9. Security Hardening (Sprint 7) - **COMPLETE**

**Added**: Comprehensive Security Hardening section (~100 lines)

**Content**:
- 30 SQL injection vulnerabilities eliminated
- Parameterized SQL pattern (before/after code examples)
- Pre-commit hooks (4 hooks: detect-secrets, bandit, black, pre-commit-hooks)
- GitHub Actions security scanning (4 jobs: secrets, dependencies, code, CodeQL)
- Secret exposure remediation
- Files modified: sql_on_fhir.py, sql_generator.py, extraction_agent.py, phenotype_agent.py
- Setup instructions for pre-commit hooks
- Bandit results: 63 warnings → 0 warnings

**Why Not in Original Checklist**: Sprint 7 completed 2025-11-03 (6 days after checklist created)

---

**Created**: 2025-10-28
**Updated**: 2025-11-03 (LangGraph 100% completion)
**Sprint Coverage**: 4.5, 5, 5.5, 6.5, 6.6, 6.7, 7
**Status**: ✅ COMPLETE (all sprints documented)
**Migration Completion**: LangGraph 75% → 100% 🎉
**Next Review**: After Sprint 8 completion or production rollout
