# CLAUDE.md Update Checklist (2025-10-28)

This checklist documents changes that should be reflected in CLAUDE.md based on recent development.

## Changes to Document

### ✅ 1. Lambda Architecture Implementation (MAJOR)

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

### ✅ 2. Project Structure Updates

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

### ✅ 3. Environment Variables

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

### ✅ 4. Implementation Status

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

### ✅ 5. Testing Section

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

### ✅ 6. Documentation Section

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

### ✅ 7. Quick Start Updates

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

## Update Priority

### 🔴 **HIGH PRIORITY** (Do Before Next Major Commit):
1. ✅ Lambda Architecture section
2. ✅ Project Structure (new directories)
3. ✅ Environment Variables (Redis, LangSmith)
4. ✅ Implementation Status (completions)

### 🟡 **MEDIUM PRIORITY** (Can wait):
5. ✅ Documentation section (new docs)
6. ✅ Testing section (new tests)

### 🟢 **LOW PRIORITY** (Nice to have):
7. ✅ Quick Start (Redis setup)

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

**Created**: 2025-10-28
**Sprint**: 5.5 (Speed Layer)
**Next Review**: Before merging feature branch to main
