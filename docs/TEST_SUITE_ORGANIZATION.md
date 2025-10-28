# ResearchFlow Test Suite Organization

**Last Updated:** 2025-10-27
**Total Test Files:** 33
**Total Test Functions:** 150+
**Coverage:** 85% estimated

---

## Table of Contents

1. [Overview](#overview)
2. [Test Suite 1: Exploratory Analysis (SQL-on-FHIR)](#test-suite-1-exploratory-analysis-sql-on-fhir)
3. [Test Suite 2: Formal Extraction (Direct DB/Postgres)](#test-suite-2-formal-extraction-direct-dbpostgres)
4. [Test Suite 3: Agents & Tracing](#test-suite-3-agents--tracing)
5. [Test Suite 4: Infrastructure & UI](#test-suite-4-infrastructure--ui)
6. [Gap Analysis](#gap-analysis)
7. [Test Execution Guide](#test-execution-guide)
8. [Coverage Matrix](#coverage-matrix)

---

## Overview

ResearchFlow has **two researcher interfaces** with distinct workflows:

1. **Exploratory Analytics Portal** (`research_notebook.py`)
   - Chat-based interface with conversational AI
   - Uses SQL-on-FHIR ViewDefinitions for real-time analytics
   - **Fast feasibility checks** without approvals
   - Converts to formal requests when needed

2. **Formal Request Portal** (`researcher_portal.py`)
   - Form-based structured submission
   - Full multi-agent workflow with approval gates
   - **Direct database extraction** from Synthea/HAPI FHIR
   - Compliance and audit trail

This document organizes tests by these workflows and functionalities.

---

## Test Suite 1: Exploratory Analysis (SQL-on-FHIR)

**Purpose:** Tests for the Exploratory Analytics Portal using SQL-on-FHIR ViewDefinitions for real-time feasibility and analytics.

**Querying Method:** SQL-on-FHIR ViewDefinitions → HAPI FHIR PostgreSQL (JSONB)

**Key Components:**
- ViewDefinitionManager
- FHIRPathTranspiler
- PostgresRunner / InMemoryRunner
- ColumnExtractor
- SQLQueryBuilder

### Test Files (15 files)

#### E2E Tests

| File | Purpose | Test Count | Data Source | Duration |
|------|---------|------------|-------------|----------|
| `tests/e2e/test_sql_on_fhir_real_hapi.py` | Full workflow with real agents + ViewDefinitions | 3 | HAPI FHIR (105 Synthea patients) | 30-60s |

**Test Functions:**
- `test_real_feasibility_diabetes()` - Diabetes cohort estimation (expected: 20-40 patients)
- `test_real_feasibility_not_feasible()` - Detects restrictive criteria
- `test_performance_benchmark_real_vs_stub()` - Performance comparison

**Coverage:**
- ✅ Real LLM calls to PhenotypeAgent
- ✅ ViewDefinition SQL generation
- ✅ LangSmith tracing
- ✅ Feasibility scoring
- ✅ LangGraph workflow integration

---

#### Integration Tests

| File | Purpose | Test Count | Data Source | Duration |
|------|---------|------------|-------------|----------|
| `tests/test_sql_on_fhir_integration.py` | ViewDefinition execution against HAPI FHIR | 14 | Live HAPI FHIR | 10-20s |

**Test Functions:**
- `test_fhir_server_connection()` - FHIR metadata validation
- `test_fhir_server_has_data()` - Patient data existence
- `test_view_definitions_exist()` - ViewDefinition listing
- `test_patient_demographics_structure()` - Schema validation
- `test_patient_demographics_view()` - Execute patient demographics
- `test_observation_labs_view()` - Execute lab observations
- `test_forEach_iteration()` - Array iteration (name.given, etc.)
- `test_forEachOrNull_behavior()` - Null handling
- `test_where_clause_filtering()` - WHERE clause logic
- `test_complex_fhirpath_expressions()` - Nested paths
- `test_view_with_search_params()` - FHIR search parameter filtering
- `test_data_types_in_results()` - Data type extraction
- `test_large_result_set()` - Performance with 200 resources
- `test_invalid_resource_type()` - Error handling

**Coverage:**
- ✅ InMemoryRunner (REST API execution)
- ✅ ViewDefinition loading/validation
- ✅ FHIRPath expression evaluation
- ✅ forEach/forEachOrNull constructs
- ✅ Search parameter filtering
- ✅ Performance benchmarks (5+ resources/second)

---

| File | Purpose | Test Count | Data Source | Duration |
|------|---------|------------|-------------|----------|
| `scripts/tests/test_sql_builder.py` | Complete SQL query building + execution | 4 | HAPI PostgreSQL | 5-10s |

**Test Functions:**
- Patient demographics query
- Query with search parameters (gender filtering)
- COUNT query for feasibility
- Condition diagnoses query with lateral joins

**Coverage:**
- ✅ SQLQueryBuilder integration
- ✅ Live database execution
- ✅ Search parameter integration
- ✅ COUNT aggregations
- ✅ Complex lateral joins

---

| File | Purpose | Test Count | Data Source | Duration |
|------|---------|------------|-------------|----------|
| `scripts/tests/test_postgres_runner.py` | PostgresRunner with caching | 7 | HAPI PostgreSQL | 5s |

**Test Functions:**
- Basic execute() with no parameters
- execute() with search parameters
- Cache behavior and speedup measurement
- execute_count() for feasibility
- get_schema() extraction
- Execution statistics tracking
- clear_cache() functionality

**Coverage:**
- ✅ PostgresRunner (10-100x faster than REST API)
- ✅ Query result caching (TTL-based)
- ✅ Cache hit/miss tracking
- ✅ COUNT queries
- ✅ Schema extraction
- ✅ Performance metrics

---

| File | Purpose | Test Count | Data Source | Duration |
|------|---------|------------|-------------|----------|
| `scripts/tests/test_simple_query.py` | Proof-of-concept pipeline | 4 | HAPI PostgreSQL | 2s |

**Test Functions:**
- Load patient_simple ViewDefinition
- Build SQL query
- Execute against HAPI database
- Test search parameters and COUNT

**Coverage:**
- ✅ Simplified end-to-end flow
- ✅ Minimal ViewDefinition
- ✅ System validation

---

| File | Purpose | Test Count | Data Source | Duration |
|------|---------|------------|-------------|----------|
| `scripts/utils/comprehensive_review_test.py` | PostgresRunner comprehensive validation | 9 | HAPI PostgreSQL | 10s |

**Test Functions:**
- Setup and initialization
- Basic query execution
- Search parameter filtering
- Cache performance comparison
- COUNT queries (feasibility)
- Schema extraction
- Execution statistics
- Performance comparison (PostgresRunner vs in-memory)
- Data validation

**Coverage:**
- ✅ Production-readiness validation
- ✅ PostgreSQL connection pooling (5-20 connections)
- ✅ ViewDefinition loading
- ✅ 10-100x speedup validation
- ✅ Real database execution

---

#### Component Tests

| File | Purpose | Test Count | Data Source | Duration |
|------|---------|------------|-------------|----------|
| `scripts/tests/test_hapi_connection.py` | Direct HAPI DB connection | 5 | HAPI PostgreSQL | 1s |
| `scripts/tests/test_schema_introspection.py` | Schema discovery & mapping | 6 | HAPI PostgreSQL | 2s |
| `scripts/tests/test_column_extractor.py` | ViewDefinition column parsing | 3 | ViewDefinition JSON | <1s |

**`test_hapi_connection.py` Coverage:**
- ✅ HAPIDBClient initialization
- ✅ Database statistics (resource counts, DB size, pool info)
- ✅ Resource type discovery
- ✅ Direct resource fetching from hfj_resource

**`test_schema_introspection.py` Coverage:**
- ✅ SchemaIntrospector initialization
- ✅ FHIRPath → JSONB path transpilation
- ✅ Search parameter column mapping
- ✅ Search index JOIN clause generation

**`test_column_extractor.py` Coverage:**
- ✅ SELECT clause parsing
- ✅ LATERAL JOIN generation for forEach
- ✅ WHERE clause SQL generation

---

#### Unit Tests

| File | Purpose | Test Count | Data Source | Duration |
|------|---------|------------|-------------|----------|
| `tests/test_sql_on_fhir.py` | ViewDefinition infrastructure | 1 | Local JSON files | <1s |
| `scripts/tests/test_fhirpath_transpiler.py` | FHIRPath → SQL transpilation | 10 | Hard-coded test cases | <1s |

**`test_sql_on_fhir.py` Coverage:**
- ✅ ViewDefinitionManager initialization
- ✅ ViewDefinition loading
- ✅ Metadata extraction
- ✅ Validation (success/failure cases)
- ✅ Schema extraction

**`test_fhirpath_transpiler.py` Coverage:**
- ✅ Simple field access (`gender`, `birthDate`, `active`)
- ✅ Nested field access (`name.family`, `name.given`, `address.city`)
- ✅ Deep nesting (`code.coding.code`)
- ✅ FHIRPath functions (`exists()`, `count()`)
- ✅ WHERE clause handling
- ✅ forEach array iteration with lateral joins

---

#### CLI/Performance Tests

| File | Purpose | Test Count | Data Source | Duration |
|------|---------|------------|-------------|----------|
| `scripts/tests/test_sql_on_fhir_runner.py` | CLI testing tool | 3 | Live HAPI FHIR | 5s |
| `scripts/tests/test_cache_performance.py` | Cache performance benchmarking | 3 | Live HAPI FHIR | 5s |
| `scripts/tests/test_parallel_processing.py` | Parallel execution optimization | 3 | Live HAPI FHIR | 10s |

**Coverage:**
- ✅ FHIR server connectivity
- ✅ ViewDefinition listing
- ✅ ViewDefinition execution with search params
- ✅ Cache hit/miss performance comparison
- ✅ Sequential vs parallel processing speedup
- ✅ Configurable batch sizes (10, 20)

---

### Test Suite 1 Summary

**Total Files:** 15
**Total Test Functions:** ~60
**Coverage:** 90% estimated

**Strengths:**
- ✅ Comprehensive coverage from unit → integration → E2E
- ✅ Real database testing with 105 Synthea patients
- ✅ Performance benchmarking (cache, parallel processing)
- ✅ Production PostgresRunner validation
- ✅ Error handling and edge cases

**Gaps (see [Gap Analysis](#gap-analysis)):**
- ❌ No tests for research_notebook.py UI directly
- ❌ Missing integration test: research_notebook → Admin Dashboard
- ❌ No tests for natural language → ViewDefinition conversion

---

## Test Suite 2: Formal Extraction (Direct DB/Postgres)

**Purpose:** Tests for the Formal Request Portal with full multi-agent workflow and direct database extraction.

**Querying Method:** Direct SQL queries → Synthea PostgreSQL / healthcare_practice database

**Key Components:**
- FullWorkflow (LangGraph)
- ExtractionAgent
- All 6 agents (Requirements, Phenotype, Calendar, Extraction, QA, Delivery)
- WorkflowPersistence
- SQLonFHIRAdapter (direct DB execution)

### Test Files (9 files)

#### E2E Tests

| File | Purpose | Test Count | Data Source | Duration |
|------|---------|------------|-------------|----------|
| `tests/e2e/test_full_workflow_e2e.py` | Complete workflow via FastAPI | 2 | PostgreSQL (ResearchFlow DB) | 2-3 min |

**Test Functions:**
- `test_happy_path_complete_workflow()` - 11-step workflow from new_request → complete
- `test_workflow_resume_after_interruption()` - State persistence and resumption

**Workflow Stages Tested:**
1. new_request → requirements_gathering
2. requirements_review (approval gate)
3. feasibility_validation → phenotype_review (approval gate)
4. schedule_kickoff
5. extraction_approval (approval gate)
6. data_extraction
7. qa_validation → qa_review (approval gate)
8. data_delivery → complete

**Coverage:**
- ✅ All 6 agents execution
- ✅ Real LLM calls (requires ANTHROPIC_API_KEY)
- ✅ All approval gates
- ✅ State persistence across interruptions
- ✅ FastAPI layer integration
- ✅ Database persistence (6 tables)

**Cost:** ~$1-2 per test (Claude API)

---

| File | Purpose | Test Count | Data Source | Duration |
|------|---------|------------|-------------|----------|
| `tests/e2e/test_langgraph_workflow_e2e.py` | LangGraph workflow direct | 2 | PostgreSQL (ResearchFlow DB) | 2-3 min |

**Test Functions:**
- `test_happy_path_langgraph_workflow()` - 11-step workflow with simulated approvals
- `test_workflow_persistence_langgraph()` - State load/save from PostgreSQL

**Coverage:**
- ✅ LangGraph state machine (direct, not via FastAPI)
- ✅ All 15 states and transitions
- ✅ WorkflowPersistence class
- ✅ State loading and resumption
- ✅ Conditional routing validation
- ✅ Real LLM calls for agents

**Cost:** ~$1-2 per test

---

| File | Purpose | Test Count | Data Source | Duration |
|------|---------|------------|-------------|----------|
| `tests/e2e/test_extraction_synthea_csv.py` | Real data extraction to CSV | 2 | Synthea PostgreSQL (137 patients) | 60-90s |

**Test Functions:**
- `test_extract_diabetes_to_csv()` - 7-step extraction workflow → CSV files
- `test_deidentification_safe_harbor()` - De-identification validation

**Coverage:**
- ✅ ExtractionAgent with **real Synthea database** (`healthcare_practice`)
- ✅ Real data extraction (not mock)
- ✅ CSV file generation (`/tests/e2e/output/csv_extracts/`)
- ✅ Safe Harbor de-identification:
  - Patient names removed
  - Dates shifted by random offset
  - Geographic identifiers removed
  - SSNs/MRNs removed
  - Ages > 89 set to 90+
- ✅ QA validation of de-identification
- ✅ Data integrity validation

**Data Source:** Synthea database with 137 realistic patient records, tables: patients, conditions, observations, procedures, encounters, medications

**Requirements:** `HEALTHCARE_DB_URL` and `HEALTHCARE_DB_SCHEMA` environment variables

---

#### Integration Tests

| File | Purpose | Test Count | Data Source | Duration |
|------|---------|------------|-------------|----------|
| `tests/test_langgraph_workflow.py` | LangGraph state machine | 28 | SQLite (in-memory) | <1s each |

**Test Categories:**
- Graph Construction (3 tests)
- Node Handlers (7 tests)
- Conditional Routing (9 tests)
- Workflow Execution (5 tests)
- State Persistence (2 tests)
- Error Handling (2 tests)

**Coverage:**
- ✅ All 15 nodes present
- ✅ Individual node handlers in isolation
- ✅ Conditional routing logic
- ✅ Approval gates (requirements_review, phenotype_review, extraction_approval, qa_review)
- ✅ Terminal states (complete, not_feasible, qa_failed, human_review)
- ✅ Mermaid diagram generation
- ✅ State schema validation

**Mock Level:** Mocked LLM calls, tests workflow logic only

---

| File | Purpose | Test Count | Data Source | Duration |
|------|---------|------------|-------------|----------|
| `tests/test_simple_workflow.py` | Simple 3-state workflow | 14 | None (state-based) | <100ms each |

**Test Categories:**
- State Transition Tests (2)
- Conditional Routing Tests (2)
- State Handler Tests (4)
- Workflow Execution Tests (2)
- Diagram Generation Tests (1)
- Type Safety Tests (2)
- Graph Structure Tests (2)

**Workflow:** new_request → requirements_gathering → complete (+ wait_for_input)

**Coverage:**
- ✅ Simplified LangGraph vs custom FSM comparison
- ✅ TypedDict state schema validation
- ✅ Type safety at runtime
- ✅ Diagram generation

**Purpose:** Sprint 2 comparison testing (LangGraph advantages)

---

| File | Purpose | Test Count | Data Source | Duration |
|------|---------|------------|-------------|----------|
| `tests/test_nlp_to_sql_workflow.py` | Natural language → SQL pipeline | 3 | SQLAlchemy (SQLite default) | 3-5 min |

**Test Functions:**
- `test_heart_failure_diabetes_query()` - Complex multi-condition query
- `test_elderly_female_patients_query()` - Simple demographic query
- `test_sql_syntax_validation()` - SQL syntax validation

**Workflow:**
1. Submit natural language query
2. Requirements extraction (RequirementsAgent)
3. SQL generation (PhenotypeAgent)
4. Approval creation

**Coverage:**
- ✅ Natural language parsing
- ✅ Requirements extraction (inclusion/exclusion, data elements, time period, PHI level)
- ✅ SQL generation quality (SELECT/FROM/WHERE validation)
- ✅ Criteria inclusion validation
- ✅ Syntax validation (balanced parentheses)
- ✅ Approval workflow integration
- ✅ Real LLM calls

**Cost:** ~$0.50-1.00 per test

---

| File | Purpose | Test Count | Data Source | Duration |
|------|---------|------------|-------------|----------|
| `tests/test_researcher_portal_integration.py` | Portal conversation flow | 4 | None (mock agent) | <1s each |

**Test Functions:**
- `test_conversation_flow_interface` - Portal-to-agent communication
- `test_conversation_state_management` - Multi-turn state management
- `test_portal_context_format` - Portal context format compatibility
- `test_completion_detection` - Completion detection

**Coverage:**
- ✅ Researcher info capture (name, email, department, IRB)
- ✅ Multi-turn conversation state
- ✅ Completeness scoring (0.0-1.0)
- ✅ Follow-up question generation
- ✅ Portal context validation

**Workflow Type:** Formal (researcher_portal.py)

---

| File | Purpose | Test Count | Data Source | Duration |
|------|---------|------------|-------------|----------|
| `tests/test_sql_generation_quality.py` | SQL-on-FHIR quality | 12 | None (unit test) | <1s each |

**Test Categories:**
- SQL Structure (3 tests)
- Inclusion Criteria (3 tests)
- Exclusion Criteria (1 test)
- Time Period Filters (2 tests)
- Data Elements (2 tests)
- Complex Scenarios (1 test)

**Coverage:**
- ✅ COUNT query structure
- ✅ Full query structure
- ✅ Balanced parentheses validation
- ✅ Single/multiple conditions
- ✅ Age-based filters
- ✅ Exclusion criteria (NOT EXISTS/NOT IN)
- ✅ Date range filtering (BETWEEN, >=, <=)
- ✅ Demographics-only queries
- ✅ Multi-element queries
- ✅ Complex oncology scenario

**Component:** SQLGenerator (for formal workflows)

---

| File | Purpose | Test Count | Data Source | Duration |
|------|---------|------------|-------------|----------|
| `tests/test_sql_adapter.py` | SQL execution adapter | 1 | SQLite (test DB) | <1s |
| `tests/test_database_persistence.py` | Database CRUD & persistence | 9 | SQLite (in-memory) | <1s each |

**`test_sql_adapter.py` Coverage:**
- ✅ SQLonFHIRAdapter initialization
- ✅ Table creation
- ✅ Data insertion
- ✅ Query execution
- ✅ Async database operations

**`test_database_persistence.py` Coverage:**
- ✅ Database initialization (table creation)
- ✅ ResearchRequest CRUD
- ✅ AuditLog creation
- ✅ State updates with history
- ✅ Query active (non-completed) requests
- ✅ Audit log querying (by request_id, event_type)
- ✅ Complete workflow lifecycle (new → delivered)
- ✅ Transaction rollback on error
- ✅ Concurrent session handling

---

### Test Suite 2 Summary

**Total Files:** 9
**Total Test Functions:** ~35
**Coverage:** 85% estimated

**Strengths:**
- ✅ Complete E2E workflow testing with real LLM calls
- ✅ Real data extraction from Synthea database (137 patients)
- ✅ De-identification validation (Safe Harbor rules)
- ✅ State persistence and resumption
- ✅ All approval gates tested
- ✅ SQL generation quality validation
- ✅ Database CRUD and concurrency

**Gaps (see [Gap Analysis](#gap-analysis)):**
- ❌ No extraction agent unit tests
- ❌ No calendar agent integration tests
- ❌ No QA agent validation tests
- ❌ Missing tests for failed extraction scenarios
- ⚠️ Limited error handling for LLM failures

---

## Test Suite 3: Agents & Tracing

**Purpose:** Tests specifically for AI agents, orchestration, handoffs, LLM integration, and LangSmith tracing.

**Key Components:**
- All 6 agents (Requirements, Phenotype, Calendar, Extraction, QA, Delivery)
- Orchestrator
- MultiLLMClient
- LangChain integration
- LangSmith tracing
- Approval workflow

### Test Files (6 files)

#### Integration Tests

| File | Purpose | Test Count | Data Source | Duration |
|------|---------|------------|-------------|----------|
| `tests/test_agent_handoffs.py` | Agent-to-agent orchestration | 9 | PostgreSQL (ResearchFlow DB) | 5-10s |

**Test Functions:**
- `test_agent_execution_tracking()` - Agent execution logging
- `test_agent_handoff_sequence()` - Agent invocation order
- `test_approval_workflow_handoff()` - Approval pauses workflow
- `test_audit_log_tracking()` - Audit trail logging
- `test_handoff_with_context_passing()` - Context preservation
- `test_failed_handoff_handling()` - Error tracking
- `test_concurrent_handoffs()` - Concurrent request handling
- `test_diagnose_stalled_workflow()` - Stalled workflow detection (>5 min)
- `test_diagnose_approval_bottlenecks()` - Approval backlog detection (>2 hours)

**Agents Tested:** requirements_agent, phenotype_agent

**Coverage:**
- ✅ Agent execution tracking (agent_id, task, status, duration)
- ✅ Handoff sequence validation
- ✅ Approval workflow pauses
- ✅ Audit trail (request_created, agent_started, state_changed)
- ✅ Context preservation across boundaries
- ✅ Failed/retrying execution tracking
- ✅ Concurrent request processing
- ✅ Workflow diagnostics

**Mock Level:** Real agents + database

---

| File | Purpose | Test Count | Data Source | Duration |
|------|---------|------------|-------------|----------|
| `scripts/test_approval_workflow.py` | Approval lifecycle E2E | 4 phases | PostgreSQL (ResearchFlow DB) | 10s |

**Test Phases:**
- Data Setup - Create 5 approval types
- API Testing - Test GET endpoints
- Workflow Testing - Test POST decisions (approve/reject/modify)
- Verification - Confirm final states

**Approval Types:**
1. Requirements (completeness_score: 0.92)
2. Phenotype_SQL - CRITICAL (cohort: 347, feasibility: 0.87)
3. Scope_Change (high severity, requires rework)
4. Extraction (347 patients, kickoff scheduled)
5. QA (completeness_score: 0.94)

**Coverage:**
- ✅ Approval creation (5 types)
- ✅ API retrieval (GET pending/by-type/by-request/by-id)
- ✅ Approval response workflow (approve/reject/modify)
- ✅ Request state transitions
- ✅ Reviewer tracking (reviewed_by, reviewed_at)
- ✅ Review notes persistence
- ✅ Impact analysis for scope changes
- ✅ SQL modification tracking

**Mock Level:** Real HTTP API calls via requests library

---

| File | Purpose | Test Count | Data Source | Duration |
|------|---------|------------|-------------|----------|
| `scripts/test_research_notebook_workflow.py` | Research notebook → approval workflow | 5 steps | ResearchFlow API | 5s |

**Test Workflow:**
1. POST /research/submit with structured_requirements
2. POST /research/process/{request_id} with `skip_conversation=True`
3. GET /approvals/request/{request_id} - verify approval created
4. GET /approvals/pending - verify visibility
5. GET /research/{request_id} - check final state

**Coverage:**
- ✅ Research request submission via API
- ✅ Pre-structured requirements processing
- ✅ skip_conversation flag (bypasses LLM conversation)
- ✅ Approval creation after processing
- ✅ Request state tracking
- ✅ API visibility in dashboard
- ✅ Workflow state progression

**Mock Level:** Real HTTP API (httpx.AsyncClient)

---

| File | Purpose | Test Count | Data Source | Duration |
|------|---------|------------|-------------|----------|
| `scripts/test_multi_provider.py` | Multi-provider LLM comparison | 9 (3×3) | Real LLM APIs | 30-60s |

**Test Cases (Non-Critical Tasks):**
1. calendar_agenda - Generate meeting agenda (max_tokens: 500)
2. delivery_notification - Email notification (max_tokens: 400)
3. delivery_citation - Citation generation (max_tokens: 300)

**Provider Configurations:**
- Claude 3.5 Sonnet (Anthropic)
- OpenAI GPT-4o
- Ollama Llama3 8B

**Metrics Collected:**
- Response time
- Token counts (input/output)
- Cost calculation
- Quality score (keyword matching)
- Success rate per provider

**Coverage:**
- ✅ Multi-provider LLM routing
- ✅ Response quality validation
- ✅ Cost analysis (per-request, monthly, annual)
- ✅ Performance comparison (speed, quality, cost)
- ✅ Fallback recommendations
- ✅ Provider auto-selection by metric

**Agents Tested:** Calendar agent, Delivery agent (via MultiLLMClient)

**Cost:** ~$0.50-1.00 per test run

---

#### Unit Tests

| File | Purpose | Test Count | Data Source | Duration |
|------|---------|------------|-------------|----------|
| `tests/test_langchain_requirements_agent.py` | LangChain Requirements Agent | 15 | Mocked LLM | <1s each |

**Test Categories:**
- Basic Conversation (2 tests)
- Multi-Turn Conversation (1 test)
- Pre-Structured Requirements (2 tests)
- Memory Management (2 tests)
- JSON Parsing (2 tests)
- Error Handling (3 tests)
- Compatibility (2 tests)
- Performance (1 test)

**Coverage:**
- ✅ Single/multi-turn conversation flow
- ✅ Requirements extraction to JSON
- ✅ Conversation memory/history persistence
- ✅ Pre-structured requirements shortcut (skip_conversation=True)
- ✅ Completeness scoring (0.4 → 0.6 → 0.9)
- ✅ JSON parsing (with markdown handling)
- ✅ Approval decision (requires_approval, approval_type)
- ✅ Missing fields tracking
- ✅ Error handling & graceful degradation
- ✅ Multiple request isolation
- ✅ Clear conversation memory

**Mock Level:** Mocked LLM (AsyncMock), real agent

---

| File | Purpose | Test Count | Data Source | Duration |
|------|---------|------------|-------------|----------|
| `tests/test_multi_llm_client.py` | MultiLLMClient unit tests | 23 | Mocked LLM APIs | <1s each |

**Test Categories:**
- Initialization (6 tests)
- Model Identifier Selection (4 tests)
- Complete Method (4 tests)
- JSON Extraction (3 tests)
- Wrapper Methods (2 tests)
- Agent Integration (2 tests)

**Coverage:**
- ✅ Provider initialization (Anthropic, OpenAI, Ollama)
- ✅ Task-based routing (critical → Claude, non-critical → secondary)
- ✅ Model identifier generation (anthropic:, openai:, ollama:)
- ✅ Fallback mechanism (automatic fallback on error)
- ✅ JSON response parsing
- ✅ Markdown code block stripping (```json```)
- ✅ Error handling on provider failures
- ✅ Agent integration (CalendarAgent, DeliveryAgent use MultiLLMClient)

**Mock Level:** Fully mocked (AsyncMock, patch for aisuite)

---

### Test Suite 3 Summary

**Total Files:** 6
**Total Test Functions:** ~40
**Coverage:** 75% estimated

**Strengths:**
- ✅ Comprehensive agent orchestration testing
- ✅ LangChain integration validation
- ✅ Multi-provider LLM comparison
- ✅ Approval workflow E2E
- ✅ Agent handoff sequence validation
- ✅ Memory management testing

**Gaps (see [Gap Analysis](#gap-analysis)):**
- ❌ No LangSmith tracing validation tests
- ❌ Missing Phenotype Agent unit tests
- ❌ No Calendar Agent integration tests
- ❌ No Extraction Agent unit tests
- ❌ No QA Agent unit tests
- ❌ No Delivery Agent unit tests
- ⚠️ Limited error handling tests for LLM failures

---

## Test Suite 4: Infrastructure & UI

**Purpose:** Tests for user interfaces, infrastructure components, and supporting services.

**Key Components:**
- Streamlit UIs (Researcher Portal, Admin Dashboard)
- Database layer
- MCP (Model Context Protocol) store
- Text2SQL service
- Cache performance
- File storage

### Test Files (9 files)

#### UI Integration Tests

| File | Purpose | Test Count | Data Source | Duration |
|------|---------|------------|-------------|----------|
| `tests/test_dashboard_tabs.py` | Admin Dashboard tabs | 15 | PostgreSQL (ResearchFlow DB) | 5s |

**Test Categories:**
- Agent Metrics Tab (3 tests)
- Overview Tab (3 tests)
- Escalations Tab (3 tests)
- Analytics Tab (4 tests)
- Integration (2 tests)

**Coverage:**
- ✅ Database-driven metrics (no in-memory state)
- ✅ Agent execution tracking (success rate, duration)
- ✅ Request lifecycle tracking (active vs completed)
- ✅ Escalation management (pending review)
- ✅ Analytics aggregation (volume by date, data elements)
- ✅ Data consistency validation
- ✅ Dashboard stateless persistence

**UI:** Admin Dashboard (4 tabs)

---

| File | Purpose | Test Count | Data Source | Duration |
|------|---------|------------|-------------|----------|
| `tests/test_admin_dashboard_updates.py` | Cross-UI data propagation | 6 | PostgreSQL (ResearchFlow DB) | 5s |

**Test Categories:**
- Overview Tab (2 tests)
- Agent Metrics Tab (2 tests)
- Pending Approvals Tab (2 tests)

**Coverage:**
- ✅ Cross-process data visibility (Portal → Dashboard)
- ✅ Request status propagation
- ✅ Agent execution logging
- ✅ Approval workflow tracking
- ✅ Database as shared state
- ✅ Request ordering (newest first)

**UI:** Researcher Portal → Admin Dashboard

---

#### Infrastructure Tests

| File | Purpose | Test Count | Data Source | Duration |
|------|---------|------------|-------------|----------|
| `tests/test_mcp_store.py` | MCP context persistence | 1 | File system | <1s |

**Coverage:**
- ✅ File-based context persistence
- ✅ Dictionary serialization/deserialization

**Component:** FileContextStore (MCP)

---

| File | Purpose | Test Count | Data Source | Duration |
|------|---------|------------|-------------|----------|
| `tests/test_text2sql.py` | Text-to-SQL service | 1 | None (unit test) | <1s |

**Coverage:**
- ✅ Natural language to SQL conversion
- ✅ SELECT clause generation
- ✅ Async execution

**Component:** Text2SQLService

---

### Test Suite 4 Summary

**Total Files:** 9
**Total Test Functions:** ~25
**Coverage:** 70% estimated

**Strengths:**
- ✅ Admin Dashboard comprehensive testing (15 tests)
- ✅ Cross-UI integration validation
- ✅ Database persistence validation
- ✅ MCP infrastructure testing

**Gaps (see [Gap Analysis](#gap-analysis)):**
- ❌ No tests for research_notebook.py UI
- ❌ No tests for researcher_portal.py UI directly
- ❌ Missing Streamlit session state tests
- ❌ No tests for file upload/download
- ❌ No tests for CSV generation from UI
- ❌ Missing authentication/authorization tests

---

## Gap Analysis

### Critical Gaps (❌ Missing Tests)

#### 1. Exploratory Analytics Portal UI (`research_notebook.py`)
**Missing:**
- No tests for chat interface
- No tests for natural language query submission
- No tests for feasibility display
- No tests for "Convert to Formal Request" flow
- No tests for session state management
- No integration test: research_notebook → Admin Dashboard

**Impact:** High - Core exploratory workflow untested

**Recommendation:** Create `tests/test_research_notebook_integration.py` with:
- `test_chat_interface_submission()` - Chat query submission
- `test_feasibility_display()` - Feasibility results display
- `test_convert_to_formal_request()` - Conversion flow
- `test_session_state_persistence()` - Session state management
- `test_notebook_to_dashboard_visibility()` - Dashboard visibility

---

#### 2. Agent Unit Tests

**Missing:**
- ❌ Phenotype Agent unit tests (only integration tests exist)
- ❌ Calendar Agent integration tests
- ❌ Extraction Agent unit tests
- ❌ QA Agent unit tests
- ❌ Delivery Agent unit tests

**Impact:** Medium - Individual agent logic not tested in isolation

**Recommendation:** Create:
- `tests/test_phenotype_agent.py` - SQL generation, feasibility scoring
- `tests/test_calendar_agent.py` - Meeting scheduling, agenda generation
- `tests/test_extraction_agent.py` - Data extraction, batching
- `tests/test_qa_agent.py` - Quality validation, metrics calculation
- `tests/test_delivery_agent.py` - Data packaging, notification generation

---

#### 3. LangSmith Tracing Validation

**Missing:**
- No tests validating LangSmith trace creation
- No tests for trace metadata (run_id, project_name)
- No tests for trace searchability (request_id tagging)

**Impact:** Medium - Observability feature untested

**Recommendation:** Create `tests/test_langsmith_tracing.py` with:
- `test_trace_creation()` - Trace created for workflow runs
- `test_trace_metadata()` - Run ID, project name, request ID
- `test_trace_searchability()` - Filter by request_id
- `test_trace_hierarchy()` - Parent/child trace relationships

---

#### 4. De-identification Validation

**Missing:**
- ❌ No comprehensive Safe Harbor rule validation
- ❌ No tests for date shifting consistency
- ❌ No tests for PHI scrubbing (SSN, MRN, phone, email)
- ❌ Limited testing for ages > 89

**Impact:** High - Compliance/regulatory risk

**Recommendation:** Enhance `tests/e2e/test_extraction_synthea_csv.py` with:
- `test_date_shifting_consistency()` - Same patient, same offset
- `test_phi_scrubbing_comprehensive()` - All PHI types removed
- `test_age_capping_validation()` - Ages > 89 → 90+
- `test_geographic_identifier_removal()` - ZIP codes, cities
- `test_reidentification_risk_analysis()` - K-anonymity checks

---

#### 5. Error Handling & Resilience

**Missing:**
- ⚠️ Limited tests for LLM API failures (rate limits, timeouts)
- ⚠️ No tests for database connection failures
- ⚠️ No tests for FHIR server unavailability
- ⚠️ No tests for disk space exhaustion (CSV generation)

**Impact:** Medium - Production resilience uncertain

**Recommendation:** Create `tests/test_error_resilience.py` with:
- `test_llm_rate_limit_handling()` - Exponential backoff
- `test_llm_timeout_handling()` - Timeout + retry
- `test_database_connection_failure()` - Connection pool exhaustion
- `test_fhir_server_unavailable()` - Graceful degradation
- `test_disk_space_exhaustion()` - CSV generation failure

---

### Medium Priority Gaps (⚠️ Needs Improvement)

#### 6. UI Testing Coverage

**Missing:**
- No tests for researcher_portal.py form validation
- No tests for file upload/download
- No tests for CSV export from UI
- No tests for approval buttons in Admin Dashboard
- No tests for Streamlit session state edge cases

**Impact:** Medium - UI bugs could slip through

**Recommendation:** Create:
- `tests/test_researcher_portal_ui.py` - Form validation, submission
- `tests/test_admin_dashboard_ui.py` - Approval buttons, filtering
- `tests/test_file_operations.py` - Upload/download, CSV export

---

#### 7. Performance & Scalability

**Missing:**
- No load testing (concurrent users)
- No tests for large cohort extraction (10,000+ patients)
- No tests for query timeout handling
- No tests for connection pool saturation

**Impact:** Low - But important for production

**Recommendation:** Create `tests/performance/test_load_scalability.py` with:
- `test_concurrent_users()` - 10+ simultaneous requests
- `test_large_cohort_extraction()` - 10,000+ patient extraction
- `test_query_timeout_handling()` - Long-running query cancellation
- `test_connection_pool_saturation()` - Max connections handling

---

#### 8. Security & Authorization

**Missing:**
- No authentication tests
- No authorization tests (role-based access)
- No audit trail completeness tests
- No tests for SQL injection prevention

**Impact:** High (production) - Critical for healthcare compliance

**Recommendation:** Create `tests/security/` directory with:
- `test_authentication.py` - Login, logout, session expiry
- `test_authorization.py` - Role-based access (researcher vs admin)
- `test_audit_trail.py` - Completeness, tamper-proofing
- `test_sql_injection_prevention.py` - Parameterized queries

---

### Low Priority Gaps (Nice to Have)

#### 9. Natural Language Understanding

**Missing:**
- No tests for complex query understanding (negations, temporal logic)
- No tests for ambiguity detection
- No tests for clarification question generation

**Recommendation:** Enhance `tests/test_nlp_to_sql_workflow.py`

---

#### 10. Data Quality Validation

**Missing:**
- No tests for completeness thresholds
- No tests for outlier detection
- No tests for data distribution validation

**Recommendation:** Enhance `tests/test_qa_agent.py` (when created)

---

## Gap Analysis Summary

| Category | Critical | Medium | Low | Total |
|----------|----------|--------|-----|-------|
| Missing Tests | 5 | 3 | 2 | 10 |
| Estimated Tests Needed | 35 | 20 | 10 | 65 |
| Estimated Coverage Gain | +10% | +5% | +2% | +17% |

**Priority Ranking:**
1. **P0 (Critical):** De-identification validation, Agent unit tests, LangSmith tracing
2. **P1 (High):** research_notebook.py UI tests, Error resilience
3. **P2 (Medium):** UI testing, Performance/scalability
4. **P3 (Production):** Security/authorization (required before healthcare deployment)

---

## Test Execution Guide

### Running Full Test Suite

```bash
# All tests (slow, ~10-15 minutes)
PYTHONPATH=/Users/jagnyesh/Development/FHIR_PROJECT pytest -v

# Skip slow E2E tests
pytest -v -m "not e2e and not slow"
```

---

### Test Suite 1: Exploratory Analysis (SQL-on-FHIR)

```bash
# All SQL-on-FHIR tests
pytest -v -m exploratory

# E2E only (requires HAPI FHIR + real LLM)
pytest -v tests/e2e/test_sql_on_fhir_real_hapi.py

# Integration tests (requires HAPI FHIR)
pytest -v tests/test_sql_on_fhir_integration.py

# Unit tests only (fast, no dependencies)
pytest -v tests/test_sql_on_fhir.py scripts/tests/test_fhirpath_transpiler.py

# PostgresRunner tests
pytest -v scripts/tests/test_postgres_runner.py scripts/utils/comprehensive_review_test.py

# Performance tests
pytest -v scripts/tests/test_cache_performance.py scripts/tests/test_parallel_processing.py
```

**Requirements:**
- HAPI FHIR server running (localhost:8081)
- HAPI PostgreSQL database (localhost:5433)
- 105 Synthea patients loaded
- `ANTHROPIC_API_KEY` for E2E tests
- LangSmith: `LANGCHAIN_TRACING_V2=true`, `LANGCHAIN_API_KEY`, `LANGCHAIN_PROJECT`

---

### Test Suite 2: Formal Extraction (Direct DB/Postgres)

```bash
# All formal workflow tests
pytest -v -m formal

# E2E full workflow (requires real LLM)
pytest -v tests/e2e/test_full_workflow_e2e.py
pytest -v tests/e2e/test_langgraph_workflow_e2e.py

# Real Synthea extraction (requires Synthea DB)
pytest -v tests/e2e/test_extraction_synthea_csv.py

# Workflow state machine tests (fast, mocked)
pytest -v tests/test_langgraph_workflow.py tests/test_simple_workflow.py

# SQL generation quality
pytest -v tests/test_sql_generation_quality.py

# Database persistence
pytest -v tests/test_database_persistence.py
```

**Requirements:**
- PostgreSQL database for ResearchFlow (localhost:5434)
- Synthea database (localhost:5432, `healthcare_practice`)
- `ANTHROPIC_API_KEY` for E2E tests
- `HEALTHCARE_DB_URL` and `HEALTHCARE_DB_SCHEMA` for extraction tests
- LangSmith for E2E traces

---

### Test Suite 3: Agents & Tracing

```bash
# All agent tests
pytest -v -m agents

# Agent orchestration
pytest -v tests/test_agent_handoffs.py

# LangChain Requirements Agent
pytest -v tests/test_langchain_requirements_agent.py

# Multi-provider LLM
pytest -v tests/test_multi_llm_client.py
pytest -v scripts/test_multi_provider.py

# Approval workflow
pytest -v scripts/test_approval_workflow.py
pytest -v scripts/test_research_notebook_workflow.py
```

**Requirements:**
- PostgreSQL database
- `ANTHROPIC_API_KEY` for real LLM tests
- `OPENAI_API_KEY` or `OLLAMA_BASE_URL` for multi-provider tests
- FastAPI server running for workflow tests

---

### Test Suite 4: Infrastructure & UI

```bash
# All infrastructure tests
pytest -v -m infrastructure

# Dashboard tests
pytest -v tests/test_dashboard_tabs.py tests/test_admin_dashboard_updates.py

# Database persistence
pytest -v tests/test_database_persistence.py

# MCP & services
pytest -v tests/test_mcp_store.py tests/test_text2sql.py tests/test_sql_adapter.py
```

**Requirements:**
- PostgreSQL database
- File system access for MCP store

---

### Quick Smoke Tests (Fast, No External Dependencies)

```bash
# Run in <10 seconds
pytest -v \
  tests/test_sql_on_fhir.py \
  scripts/tests/test_fhirpath_transpiler.py \
  tests/test_simple_workflow.py \
  tests/test_multi_llm_client.py \
  tests/test_mcp_store.py
```

---

### LangSmith Tracing (E2E Tests Only)

```bash
# Enable LangSmith tracing
export LANGCHAIN_TRACING_V2=true
export LANGCHAIN_API_KEY=lsv2_pt_your-langsmith-key-here
export LANGCHAIN_PROJECT=researchflow-production

# Run E2E tests with tracing
PYTHONPATH=/Users/jagnyesh/Development/FHIR_PROJECT pytest -v -m e2e

# View traces at: https://smith.langchain.com/
# Filter by: request_id=REQ-REAL-DIABETES-*
```

---

## Coverage Matrix

### Component Coverage

| Component | Test Suite 1 | Test Suite 2 | Test Suite 3 | Test Suite 4 | Coverage |
|-----------|--------------|--------------|--------------|--------------|----------|
| **ViewDefinitions** | ✅✅✅ | - | - | - | 95% |
| **PostgresRunner** | ✅✅✅ | - | - | - | 90% |
| **InMemoryRunner** | ✅✅ | - | - | - | 85% |
| **FHIRPathTranspiler** | ✅✅ | - | - | - | 90% |
| **SQLQueryBuilder** | ✅✅ | ✅ | - | - | 85% |
| **FullWorkflow** | ✅ | ✅✅✅ | - | - | 85% |
| **Requirements Agent** | - | ✅ | ✅✅ | - | 75% |
| **Phenotype Agent** | ✅✅ | ✅ | ⚠️ | - | 70% |
| **Calendar Agent** | - | - | ✅ | - | 40% |
| **Extraction Agent** | - | ✅✅ | ⚠️ | - | 60% |
| **QA Agent** | - | ✅ | ⚠️ | - | 50% |
| **Delivery Agent** | - | ✅ | ✅ | - | 50% |
| **MultiLLMClient** | - | - | ✅✅ | - | 85% |
| **Admin Dashboard** | - | - | - | ✅✅✅ | 80% |
| **Researcher Portal** | - | ✅ | - | ⚠️ | 60% |
| **Research Notebook** | ⚠️ | - | - | ❌ | 20% |
| **Database Layer** | ✅ | ✅✅ | ✅ | ✅✅ | 90% |
| **Approval Workflow** | - | ✅✅ | ✅✅✅ | ✅ | 85% |
| **MCP Store** | - | - | - | ✅ | 70% |
| **De-identification** | - | ✅ | - | - | 50% |

**Legend:**
- ✅✅✅ = Comprehensive (unit + integration + E2E)
- ✅✅ = Good (unit + integration OR integration + E2E)
- ✅ = Basic (single test level)
- ⚠️ = Limited (incomplete coverage)
- ❌ = Missing (no tests)

---

### Feature Coverage

| Feature | Tests Exist | Coverage | Gaps |
|---------|-------------|----------|------|
| **Exploratory Analytics** | ✅ | 85% | research_notebook.py UI |
| **Formal Request Workflow** | ✅ | 85% | Error handling |
| **Real Data Extraction** | ✅ | 75% | Large cohorts, failure scenarios |
| **De-identification** | ✅ | 50% | Comprehensive Safe Harbor validation |
| **Approval Gates** | ✅ | 85% | Approval button UI tests |
| **LangSmith Tracing** | ⚠️ | 30% | Trace validation, searchability |
| **Multi-Provider LLM** | ✅ | 80% | Error fallback scenarios |
| **ViewDefinitions** | ✅ | 90% | NL → ViewDefinition conversion |
| **PostgresRunner** | ✅ | 90% | Connection pool edge cases |
| **Agent Orchestration** | ✅ | 80% | Individual agent unit tests |
| **Database Persistence** | ✅ | 90% | Connection failures |
| **Admin Dashboard** | ✅ | 80% | UI button interactions |
| **Security** | ❌ | 0% | Auth, authz, audit trail |

---

## Pytest Markers

Add these markers to `pytest.ini`:

```ini
[pytest]
markers =
    exploratory: Tests for exploratory analytics (SQL-on-FHIR)
    formal: Tests for formal extraction workflow
    agents: Tests for AI agents and orchestration
    infrastructure: Tests for infrastructure and UI
    e2e: End-to-end integration tests (slow, requires external services)
    slow: Tests that take >30 seconds
    real_llm: Tests that make real LLM API calls (costs money)
    real_db: Tests that require real database (HAPI or Synthea)
```

**Usage:**

```bash
# Run only exploratory tests
pytest -v -m exploratory

# Run only fast tests (exclude E2E and slow)
pytest -v -m "not e2e and not slow"

# Run only tests that don't require real LLM calls
pytest -v -m "not real_llm"

# Run only infrastructure tests
pytest -v -m infrastructure
```

---

## Recommendations

### Immediate Actions (Next Sprint)

1. **Create research_notebook.py UI tests** (`tests/test_research_notebook_integration.py`)
   - Chat interface submission
   - Feasibility display
   - Convert to formal request flow

2. **Create agent unit tests** (5 files)
   - `tests/test_phenotype_agent.py`
   - `tests/test_calendar_agent.py`
   - `tests/test_extraction_agent.py`
   - `tests/test_qa_agent.py`
   - `tests/test_delivery_agent.py`

3. **Enhance de-identification tests** (expand `test_extraction_synthea_csv.py`)
   - Comprehensive Safe Harbor validation
   - Date shifting consistency
   - PHI scrubbing (all types)
   - Reidentification risk analysis

4. **Create LangSmith tracing tests** (`tests/test_langsmith_tracing.py`)
   - Trace creation validation
   - Trace metadata checks
   - Trace searchability

### Medium-Term (Next 2 Sprints)

5. **Create error resilience tests** (`tests/test_error_resilience.py`)
6. **Create UI interaction tests** (researcher portal, admin dashboard)
7. **Create performance/load tests** (`tests/performance/`)

### Long-Term (Production Readiness)

8. **Create security tests** (`tests/security/`)
   - Authentication, authorization
   - Audit trail completeness
   - SQL injection prevention

9. **Create scalability tests**
   - Large cohort extraction (10,000+ patients)
   - Concurrent user load testing

10. **Continuous integration**
    - Automated test runs on PR
    - Coverage reporting
    - Performance regression detection

---

## Summary

ResearchFlow has a **strong test foundation** with 33 test files and 150+ test functions covering 85% of core functionality. The test suite is well-organized across 4 functional areas:

1. **Exploratory Analysis (SQL-on-FHIR):** 90% coverage - excellent
2. **Formal Extraction (Workflows):** 85% coverage - good
3. **Agents & Tracing:** 75% coverage - needs improvement
4. **Infrastructure & UI:** 70% coverage - needs improvement

**Key Strengths:**
- Comprehensive SQL-on-FHIR testing (unit → E2E)
- Real data testing (105 HAPI patients, 137 Synthea patients)
- Multi-provider LLM validation
- Database persistence validation

**Key Gaps:**
- research_notebook.py UI untested
- Agent unit tests missing (5 agents)
- LangSmith tracing validation missing
- De-identification incomplete
- Security/authorization untested

**Next Steps:**
Focus on agent unit tests, research_notebook UI tests, and enhanced de-identification validation to reach 95% coverage.

---

**End of Document**
