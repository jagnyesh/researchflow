# ResearchFlow Database Architecture

**Date**: 2025-11-04
**Status**: ⚠️ **MISALIGNED** - Local dev uses SQLite, but should use PostgreSQL

---

## 🎯 **Executive Summary**

ResearchFlow currently uses **3 separate databases**:
1. **HAPI FHIR PostgreSQL** (patient/FHIR data) - ✅ Correct
2. **ResearchFlow SQLite** (workflow state) - ⚠️ **Should be PostgreSQL**
3. **LangGraph Checkpointer SQLite** (workflow snapshots) - ✅ OK for now

**Critical Finding**: SQLite was recommended for Python 3.13 compatibility, but **you're on Python 3.11.12**, so PostgreSQL should be used everywhere.

---

## 📊 **Current Database Inventory**

### **Database 1: HAPI FHIR PostgreSQL** ✅

**Type**: PostgreSQL 15
**Location**: Docker container `hapi-postgres`
**Port**: 5433 (host) → 5432 (container)
**Connection String**: `postgresql://hapi:hapi@localhost:5433/hapi`
**Environment Variable**: `HAPI_DB_URL`
**Status**: ✅ Running (8 days uptime)

**Stores**:
- **FHIR Resources**: All FHIR R4 resource types
  - Patient (105 patients) - Demographics, identifiers, extensions
  - Condition (423 conditions) - Diagnoses, clinical status, severity
  - Observation (1,245+ observations) - Lab results, vital signs, assessments
  - Medication, Procedure, Encounter, etc.
- **HAPI Schema Tables**:
  - `hfj_resource` - Resource metadata (ID, type, version, FHIR ID)
  - `hfj_res_ver` - Resource version content (JSON storage)
  - `hfj_spidx_string`, `hfj_spidx_token`, `hfj_spidx_date` - Search indexes
  - `hfj_res_link` - Resource references
- **Materialized Views** (Sprint 4.5 - `sqlonfhir` schema):
  - `patient_demographics` - 105 rows
  - `condition_simple` - 423 rows
  - `observation_labs` - 1,245 rows
  - `medication_requests`, `procedure_history`, etc.

**Code Access**:
- `app/clients/hapi_db_client.py` - Direct asyncpg connection pool
- `app/sql_on_fhir/runner/postgres_runner.py` - ViewDefinition execution
- `app/sql_on_fhir/runner/materialized_view_runner.py` - Materialized view queries

**Performance**:
- Materialized views: 5-15ms queries (10-100x faster than REST API)
- Direct asyncpg: Connection pooling (5-20 connections)
- Indexes: Search parameter indexes for fast FHIR queries

---

### **Database 2: ResearchFlow Application Database** ⚠️

**Current Type**: SQLite (⚠️ **Should be PostgreSQL**)
**Location**: `/Users/jagnyesh/Development/FHIR_PROJECT/dev.db`
**Size**: 380 KB
**Connection String**: `sqlite+aiosqlite:///./dev.db`
**Environment Variable**: `DATABASE_URL`
**Status**: ⚠️ **Misaligned** with Docker (uses PostgreSQL)

**Stores** (from `app/database/models.py`):
1. **`research_requests`** - Main request tracking
   - Fields: id, researcher_email, researcher_name, irb_number, request_type
   - State: current_state (15 possible states)
   - Timestamps: created_at, updated_at, submitted_at, delivered_at

2. **`requirements_data`** - Structured requirements
   - Fields: request_id (FK), inclusion_criteria, exclusion_criteria, data_elements
   - JSON storage: time_period, phi_level, structured_data

3. **`feasibility_reports`** - Cohort size + validation
   - Fields: request_id (FK), cohort_size_estimate, feasibility_score, generated_sql
   - Timestamps: generated_at

4. **`agent_executions`** - Agent execution logs
   - Fields: request_id (FK), agent_id, state_before, state_after, result
   - Tracking: retry_count, execution_time_ms, error_message

5. **`escalations`** - Human-in-the-loop cases
   - Fields: request_id (FK), escalation_type, escalation_reason, assigned_to
   - Status: status (pending/resolved/rejected), resolved_at

6. **`approvals`** - Approval workflow tracking
   - Fields: request_id (FK), approval_type (requirements/phenotype/extraction/qa)
   - Fields: submitted_by, reviewed_by, status, review_notes
   - Timestamps: submitted_at, reviewed_at

7. **`data_deliveries`** - Delivery metadata
   - Fields: request_id (FK), delivery_location, delivery_format, file_list
   - Metadata: delivered_by, download_count, expiration_date

8. **`audit_logs`** - Compliance audit trail
   - Fields: request_id, event_type, event_data, user_id
   - Timestamps: timestamp, ip_address

9. **`materialized_view_metadata`** - View metadata tracking
   - Fields: view_name, last_refreshed, record_count, refresh_duration_ms

**Code Access**:
- `app/database/__init__.py` - SQLAlchemy async engine
- `app/database/models.py` - SQLAlchemy ORM models
- `app/orchestrator/orchestrator.py` - Workflow state management
- `app/web_ui/*.py` - Streamlit UI queries

**Issues with SQLite**:
- ❌ **Concurrency**: Comments in `.env` say "causes locks with concurrent access"
- ❌ **Docker mismatch**: Docker uses PostgreSQL, local uses SQLite
- ❌ **Production readiness**: SQLite not suitable for multi-user scenarios
- ❌ **Unnecessary**: asyncpg is already installed for HAPI access

---

### **Database 3: LangGraph Checkpointer** ✅

**Type**: SQLite (via `AsyncSqliteSaver`)
**Location**: `/Users/jagnyesh/Development/FHIR_PROJECT/data/langgraph_checkpoints.db`
**Size**: 0 bytes (created but not yet used)
**Connection**: Managed by LangGraph library
**Status**: 📋 Not yet active (`USE_LANGGRAPH_WORKFLOW=false`)

**Stores** (Sprint 6.5):
- **`checkpoints`** - Thread state snapshots
  - Fields: thread_id (request_id), checkpoint_id, parent_checkpoint_id
  - State: Full `FullWorkflowState` TypedDict (47 fields)
  - Timestamps: checkpoint_ns (nanoseconds)

- **`writes`** - Checkpoint write log
  - Fields: thread_id, checkpoint_id, task_id, idx, channel, value

**Code Access**:
- `app/langchain_orchestrator/persistence.py` - Checkpointer creation
- `app/langchain_orchestrator/langgraph_workflow.py` - Workflow with persistence

**Why SQLite is OK here**:
- ✅ Single-process workflow execution
- ✅ No concurrent writes (one request at a time per thread)
- ✅ File-based durability
- ✅ Async-safe with `AsyncSqliteSaver`

---

## 🗺️ **Database Architecture Diagram**

### **Current (As-Is)**:
```
┌──────────────────────────────────────────────────────────┐
│  ResearchFlow Application                                │
│                                                           │
│  ┌────────────────────────────────────────────────────┐ │
│  │  Streamlit UIs (Researcher Portal + Admin Dashboard)│ │
│  └─────────┬─────────────────────────┬────────────────┘ │
│            │                         │                   │
│            │                         │                   │
│  ┌─────────▼─────────┐     ┌────────▼────────────────┐ │
│  │  Orchestrator     │     │  Agents                 │ │
│  │  (Workflow Engine)│     │  (6 specialized agents) │ │
│  └─────────┬─────────┘     └────────┬────────────────┘ │
│            │                         │                   │
│            │ SQLAlchemy             │ asyncpg           │
│            │                         │                   │
│  ┌─────────▼─────────────────────────▼─────────────┐   │
│  │                                                   │   │
│  │  DATABASE LAYER                                  │   │
│  │                                                   │   │
│  │  ┌──────────────┐      ┌─────────────────────┐  │   │
│  │  │  SQLite      │      │  PostgreSQL         │  │   │
│  │  │  dev.db      │      │  (HAPI FHIR)        │  │   │
│  │  │  380 KB      │      │  localhost:5433     │  │   │
│  │  │              │      │                     │  │   │
│  │  │ ⚠️ ISSUE:    │      │ ✅ PATIENT DATA     │  │   │
│  │  │ - Locks      │      │  - 105 patients     │  │   │
│  │  │ - Dev only   │      │  - 423 conditions   │  │   │
│  │  │              │      │  - 1,245+ obs       │  │   │
│  │  │              │      │                     │  │   │
│  │  │ Contains:    │      │ Contains:           │  │   │
│  │  │ - Requests   │      │ - FHIR resources    │  │   │
│  │  │ - Approvals  │      │ - Materialized      │  │   │
│  │  │ - Audit logs │      │   views (sqlonfhir) │  │   │
│  │  └──────────────┘      └─────────────────────┘  │   │
│  │                                                   │   │
│  │  ┌─────────────────────────────────────────┐    │   │
│  │  │  LangGraph Checkpointer (SQLite)        │    │   │
│  │  │  data/langgraph_checkpoints.db          │    │   │
│  │  │  (not yet used)                         │    │   │
│  │  └─────────────────────────────────────────┘    │   │
│  │                                                   │   │
│  └───────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────┘
```

### **Recommended (To-Be)**:
```
┌──────────────────────────────────────────────────────────┐
│  ResearchFlow Application                                │
│                                                           │
│  ┌────────────────────────────────────────────────────┐ │
│  │  Streamlit UIs (Researcher Portal + Admin Dashboard)│ │
│  └─────────┬─────────────────────────┬────────────────┘ │
│            │                         │                   │
│            │                         │                   │
│  ┌─────────▼─────────┐     ┌────────▼────────────────┐ │
│  │  Orchestrator     │     │  Agents                 │ │
│  │  (Workflow Engine)│     │  (6 specialized agents) │ │
│  └─────────┬─────────┘     └────────┬────────────────┘ │
│            │                         │                   │
│            │ SQLAlchemy             │ asyncpg           │
│            │                         │                   │
│  ┌─────────▼─────────────────────────▼─────────────┐   │
│  │                                                   │   │
│  │  UNIFIED POSTGRESQL LAYER                        │   │
│  │                                                   │   │
│  │  ┌──────────────────────────────────────────┐   │   │
│  │  │  PostgreSQL (ResearchFlow App)           │   │   │
│  │  │  localhost:5434                          │   │   │
│  │  │                                          │   │   │
│  │  │  ✅ WORKFLOW STATE                       │   │   │
│  │  │  - Research requests                     │   │   │
│  │  │  - Approvals                             │   │   │
│  │  │  - Audit logs                            │   │   │
│  │  │  - Feasibility reports                   │   │   │
│  │  │                                          │   │   │
│  │  │  Benefits:                               │   │   │
│  │  │  - No concurrency locks                  │   │   │
│  │  │  - Production-ready                      │   │   │
│  │  │  - Docker parity                         │   │   │
│  │  └──────────────────────────────────────────┘   │   │
│  │                                                   │   │
│  │  ┌──────────────────────────────────────────┐   │   │
│  │  │  PostgreSQL (HAPI FHIR)                  │   │   │
│  │  │  localhost:5433                          │   │   │
│  │  │                                          │   │   │
│  │  │  ✅ PATIENT DATA                         │   │   │
│  │  │  - 105 patients                          │   │   │
│  │  │  - 423 conditions                        │   │   │
│  │  │  - 1,245+ observations                   │   │   │
│  │  │                                          │   │   │
│  │  │  + Materialized Views (sqlonfhir)       │   │   │
│  │  │    - patient_demographics                │   │   │
│  │  │    - condition_simple                    │   │   │
│  │  │    - observation_labs                    │   │   │
│  │  └──────────────────────────────────────────┘   │   │
│  │                                                   │   │
│  │  ┌─────────────────────────────────────────┐    │   │
│  │  │  LangGraph Checkpointer (SQLite)        │    │   │
│  │  │  ✅ OK - Single-process workflow        │    │   │
│  │  └─────────────────────────────────────────┘    │   │
│  │                                                   │   │
│  └───────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────┘
```

---

## 🤔 **Why Was SQLite Recommended?**

### **Root Cause Analysis**

During the earlier session, SQLite was recommended for the following (flawed) reasoning:

**Assumption**: Python 3.13 compatibility issue with asyncpg
- asyncpg 0.28.0 doesn't compile on Python 3.13 (C API changes)
- Solution: Use SQLite to avoid asyncpg dependency

**Reality**: You're on **Python 3.11.12**, NOT Python 3.13!

```bash
$ python3 --version
Python 3.11.12
```

**Consequences**:
1. ❌ SQLite recommended unnecessarily
2. ❌ `.env` changed to SQLite URLs
3. ❌ `researcher_portal.py` changed to SQLite default
4. ❌ `admin_dashboard.py` changed to SQLite default
5. ✅ BUT: asyncpg is actually installed and working (`config/requirements.txt` line 5)

### **The Mistake**

The session started with this error:
```
ModuleNotFoundError: No module named 'asyncpg'
```

**Incorrect diagnosis**: "Python 3.13 is incompatible with asyncpg"
**Correct diagnosis**: "asyncpg wasn't installed yet" (it was later installed successfully)

### **Why SQLite Seemed to Work**

SQLite initially "solved" the problem because:
1. No asyncpg import needed
2. Streamlit loaded without errors
3. Tests passed (using in-memory SQLite)

**But this introduced new problems**:
1. Concurrency issues (SQLite locking)
2. Docker/local environment mismatch
3. Fragmented architecture

---

## 📚 **Sprint Documentation Review**

### **No PostgreSQL Migration Found**

After reviewing all sprint documents in `docs/sprints/`, **there is NO documented plan** to migrate from SQLite to PostgreSQL for the ResearchFlow application database.

**Sprint 4.5** (Materialized Views):
- Focus: Create materialized views in HAPI PostgreSQL (`sqlonfhir` schema)
- Quote: *"Store materialized views in same PostgreSQL instance as HAPI FHIR"*
- **No mention** of ResearchFlow app database type

**Sprint 6.5** (LangGraph Migration):
- Focus: Replace custom orchestrator with LangGraph
- Persistence: Uses `AsyncSqliteSaver` for checkpointer
- Quote: *"Creates SQLite database at data/langgraph_checkpoints.db"*
- **No mention** of changing app database from SQLite to PostgreSQL

**Sprint 7** (Security Hardening):
- Focus: SQL injection prevention, pre-commit hooks
- Parameterized queries work with both SQLite and PostgreSQL
- **No database type preference**

### **Codebase Design Intent**

The codebase is **database-agnostic** by design:

```python
# app/database/__init__.py
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./dev.db")

# SQLAlchemy supports both
engine = create_async_engine(DATABASE_URL, echo=False)
```

**Interpretation**: The project was designed to support **both** SQLite (dev) and PostgreSQL (prod), **not** to mandate SQLite.

---

## 🎯 **Recommended Unified Strategy**

### **Option A: All PostgreSQL (RECOMMENDED)** ✅

**Configuration**:
```bash
# .env
DATABASE_URL=postgresql+asyncpg://researchflow:researchflow@localhost:5434/researchflow
HAPI_DB_URL=postgresql+asyncpg://hapi:hapi@localhost:5433/hapi
```

**Architecture**:
- **App database**: PostgreSQL (port 5434)
- **HAPI database**: PostgreSQL (port 5433)
- **Checkpointer**: SQLite (OK for single-process)

**Rationale**:
1. ✅ **Unified architecture**: Both PostgreSQL
2. ✅ **No concurrency issues**: PostgreSQL handles multi-user
3. ✅ **Docker parity**: Local dev = Production
4. ✅ **asyncpg already installed**: No new dependencies
5. ✅ **Better performance**: Connection pooling, indexes
6. ✅ **Production-ready**: Suitable for Streamlit multi-user scenarios

**Migration Steps**:
1. Start PostgreSQL container: `docker-compose up -d db`
2. Update `.env`: Uncomment PostgreSQL URLs
3. Initialize database: Run `app/database/init_db.py` (create if needed)
4. Optional: Migrate existing SQLite data (if valuable)
5. Update Streamlit UI defaults to use PostgreSQL
6. Test all workflows

**Benefits**:
- ✅ Single database technology stack
- ✅ Consistent tooling (asyncpg, PostgreSQL extensions)
- ✅ Easier ops (one DB backup strategy)
- ✅ Better monitoring (pg_stat views)

---

### **Option B: Mixed (SQLite for App, PostgreSQL for HAPI)**

**Configuration**:
```bash
# .env
DATABASE_URL=sqlite+aiosqlite:///./dev.db
HAPI_DB_URL=postgresql+asyncpg://hapi:hapi@localhost:5433/hapi
```

**Architecture**:
- **App database**: SQLite (file)
- **HAPI database**: PostgreSQL (port 5433)
- **Checkpointer**: SQLite (OK)

**Rationale**:
1. ✅ **Simplest local dev**: No PostgreSQL container for app
2. ✅ **Lightweight**: SQLite is fast for single-user
3. ⚠️ **Concurrency limits**: Streamlit multi-session locking
4. ⚠️ **Docker mismatch**: Prod uses PostgreSQL

**When to Use**:
- Solo development (no concurrent Streamlit sessions)
- Quick prototyping
- CI/CD testing (ephemeral databases)

**Not Recommended For**:
- ❌ Multi-user Streamlit deployments
- ❌ Production environments
- ❌ Heavy write workloads

---

### **Option C: All-PostgreSQL with Shared Instance**

**Configuration**:
```bash
# .env
DATABASE_URL=postgresql+asyncpg://researchflow:researchflow@localhost:5433/researchflow
HAPI_DB_URL=postgresql+asyncpg://hapi:hapi@localhost:5433/hapi
```

**Architecture**:
- **Single PostgreSQL instance** (port 5433)
- **Two databases**: `researchflow` and `hapi`
- **Shared connection pool**: Efficient resource usage

**Rationale**:
1. ✅ **Resource efficient**: One PostgreSQL instance
2. ✅ **Simplified ops**: One database to manage
3. ✅ **Cross-database queries**: `JOIN` across databases (if needed)
4. ⚠️ **Coupling**: App and HAPI share infrastructure

**When to Use**:
- Resource-constrained environments
- Integrated analytics (JOINs across app + HAPI data)

---

## 📊 **Database Comparison Matrix**

| Feature | SQLite | PostgreSQL |
|---------|--------|------------|
| **Concurrency** | ❌ File-level locking | ✅ MVCC, row-level locks |
| **Multi-user** | ❌ Slow with >1 writer | ✅ Designed for multi-user |
| **Setup complexity** | ✅ Zero setup | ⚠️ Requires server |
| **Performance (small)** | ✅ Very fast | ✅ Fast |
| **Performance (large)** | ⚠️ Degrades | ✅ Scales well |
| **Transactions** | ✅ ACID | ✅ ACID |
| **Full-text search** | ⚠️ Limited FTS | ✅ Rich FTS, GIN indexes |
| **JSON queries** | ⚠️ Basic JSON1 | ✅ JSONB with indexes |
| **Backup** | ✅ Copy file | ⚠️ pg_dump/pg_restore |
| **Deployment** | ✅ Embedded | ⚠️ Separate process |
| **Production readiness** | ⚠️ Limited | ✅ Enterprise-grade |

---

## 🚀 **Final Recommendation**

### **Recommended Strategy: Option A (All PostgreSQL)** ⭐

**Why**:
1. **You're on Python 3.11.12** → asyncpg works perfectly
2. **HAPI already requires PostgreSQL** → Infrastructure exists
3. **SQLite has documented issues** → Comments warn about locks
4. **Docker uses PostgreSQL** → Match prod environment
5. **Production readiness** → Suitable for multi-user deployments

**Action Plan**:
1. ✅ **Update `.env`**: Uncomment PostgreSQL URLs
2. ✅ **Start containers**: `docker-compose up -d db`
3. ✅ **Initialize database**: Create tables with SQLAlchemy
4. ✅ **Update UI defaults**: Change admin_dashboard.py default
5. ✅ **Test workflows**: Verify all features work
6. ✅ **Update documentation**: Note PostgreSQL as standard

**Timeline**: 30-45 minutes

**Risk**: Low (asyncpg already installed, Docker ready)

---

## 📝 **Database Migration Checklist**

- [ ] Start PostgreSQL container (`docker-compose up -d db`)
- [ ] Verify connection (`psql -h localhost -p 5434 -U researchflow -d researchflow`)
- [ ] Update `.env` to PostgreSQL URLs
- [ ] Run database initialization script
- [ ] Migrate existing SQLite data (if needed)
- [ ] Update `admin_dashboard.py` default URL
- [ ] Update `researcher_portal.py` default URL (already done)
- [ ] Test Researcher Portal (submit request, view sidebar)
- [ ] Test Admin Dashboard (view requests, approvals)
- [ ] Test concurrent sessions (open 2+ browsers)
- [ ] Verify no "database locked" errors
- [ ] Commit changes to git
- [ ] Update documentation

---

## 🔗 **References**

- **Docker Compose**: `config/docker-compose.yml` (PostgreSQL services defined)
- **Database Models**: `app/database/models.py` (SQLAlchemy ORM)
- **HAPI Client**: `app/clients/hapi_db_client.py` (asyncpg connection pool)
- **Environment Config**: `.env` (current settings)
- **Sprint Docs**: `docs/sprints/archive/SPRINT_04_5_MATERIALIZED_VIEWS.md` (PostgreSQL materialized views)
- **LangGraph Persistence**: `app/langchain_orchestrator/persistence.py` (checkpointer)

---

## 🎯 **Bottom Line**

**Current State**: ResearchFlow uses SQLite for app database (380 KB, 9 tables)
**Patient Data**: Stored in HAPI FHIR PostgreSQL (105 patients, 1,600+ resources)
**Problem**: SQLite recommended unnecessarily due to mistaken Python 3.13 assumption
**Solution**: **Migrate to PostgreSQL** for app database (you're on Python 3.11.12, asyncpg works!)
**Benefit**: Unified PostgreSQL architecture, no concurrency issues, production-ready

**Recommendation**: **Use PostgreSQL for everything** (except LangGraph checkpointer, which is fine as SQLite).
