# LangGraph Testing Plan with LangSmith Tracing

**Date**: 2025-11-03
**Purpose**: Test core AI capabilities after LangGraph migration
**Tracing**: LangSmith enabled (https://smith.langchain.com/projects/researchflow-production)

---

## Pre-Test Setup

### 1. Verify LangSmith Configuration

```bash
# Check LangSmith env vars are set
grep LANGCHAIN .env

# Should show:
# LANGCHAIN_TRACING_V2=true
# LANGCHAIN_API_KEY=lsv2_pt_...
# LANGCHAIN_PROJECT=researchflow-production
```

### 2. Start Required Services

```bash
# Terminal 1: Start PostgreSQL databases (if not running)
docker-compose -f config/docker-compose.yml up db hapi-db redis -d

# Terminal 2: Start HAPI FHIR server (if not running)
docker-compose -f config/docker-compose.yml up hapi-fhir -d

# Verify services are healthy
docker-compose -f config/docker-compose.yml ps
```

### 3. Enable LangGraph Orchestrator (Optional - Test Both)

```bash
# Option A: Test with LEGACY orchestrator
export USE_LANGGRAPH_WORKFLOW=false

# Option B: Test with LANGGRAPH orchestrator
export USE_LANGGRAPH_WORKFLOW=true
```

---

## Test Scenario 1: Exploratory Portal (research_notebook.py)

**Goal**: Test requirements gathering + feasibility analysis + SQL generation in exploratory mode

### Start Portal

```bash
# Terminal 3
export LANGCHAIN_TRACING_V2=true
streamlit run app/web_ui/research_notebook.py --server.port 8503
```

**Access**: http://localhost:8503

### Test Steps

1. **Requirements Gathering Test**:
   - Enter natural language query:
     ```
     Find female patients over 50 with diabetes and hypertension
     who had a hospital admission in 2023
     ```
   - Submit query
   - **Verify in LangSmith**: `RequirementsAgent` trace appears
   - **Expected Output**: Structured requirements extracted

2. **Feasibility Analysis Test**:
   - Review feasibility score (0.0-1.0)
   - Check estimated cohort size
   - **Verify in LangSmith**: `PhenotypeAgent` trace with feasibility calculation
   - **Expected Output**: Cohort size estimate (e.g., "~150 patients")

3. **SQL Generation Test**:
   - View generated SQL query
   - Check SQL-on-FHIR v2 ViewDefinition
   - **Verify in LangSmith**: SQL generation trace
   - **Expected Output**: Valid SQL-on-FHIR query with:
     - Patient resource selection
     - Condition filters (diabetes, hypertension)
     - Date range filters (2023)
     - Gender filter (female)
     - Age calculation (> 50)

4. **Execute Query**:
   - Click "Run Query" or "Execute"
   - **Verify in LangSmith**: Query execution trace
   - **Expected Output**: Result set with matching patients

### LangSmith Validation

Visit: https://smith.langchain.com/projects/researchflow-production

**Check for traces**:
- ✅ `extract_requirements` - Requirements parsing
- ✅ `validate_feasibility` - Feasibility calculation
- ✅ `generate_phenotype_sql` - SQL generation
- ✅ Token usage per trace
- ✅ Execution time per step
- ✅ Any errors or warnings

---

## Test Scenario 2: Formal Request Portal (researcher_portal.py)

**Goal**: Test complete workflow from requirements → delivery with LangGraph

### Start Portal

```bash
# Terminal 4
export LANGCHAIN_TRACING_V2=true
streamlit run app/web_ui/researcher_portal.py --server.port 8501
```

**Access**: http://localhost:8501

### Test Steps (Full Workflow)

#### Step 1: Submit New Request

**Form Data**:
```
Researcher Information:
- Name: Dr. Test User
- Email: test@hospital.edu
- Department: Cardiology
- IRB Number: IRB-TEST-001

Study Criteria:
Inclusion Criteria:
- Age >= 65
- Diagnosed with heart failure
- Active medication for hypertension

Exclusion Criteria:
- Pregnant patients
- Age < 18

Time Period:
- Start Date: 2023-01-01
- End Date: 2023-12-31

Data Elements:
- Demographics (age, gender, race)
- Diagnoses (ICD codes)
- Medications (prescriptions)
- Lab Results (LOINC codes)

PHI Level:
- De-identified (HIPAA Safe Harbor)
```

**Submit Request**

**Verify in LangSmith**:
- ✅ New trace created with `request_id`
- ✅ `RequirementsAgent.execute_task` trace
- ✅ Structured requirements extraction

#### Step 2: Monitor Workflow Progress

**Check Status** (in sidebar):
- Current State: Should progress through:
  - `new_request` → `requirements_gathering` → `feasibility_validation` → ...

**Verify in LangSmith**:
- ✅ `PhenotypeAgent.execute_task` trace
- ✅ Feasibility calculation
- ✅ SQL generation

**Expected Phenotype SQL**:
```sql
SELECT
  p.id as patient_id,
  p.birthDate,
  p.gender
FROM patient p
WHERE
  -- Age >= 65
  EXTRACT(YEAR FROM AGE(NOW(), p.birthDate::date)) >= 65
  -- Has heart failure diagnosis
  AND EXISTS (
    SELECT 1 FROM condition c
    WHERE c.patient_id = p.id
    AND c.code->>'code' IN ('428.0', 'I50.0', 'I50.9')  -- Heart failure codes
  )
  -- Active hypertension medication
  AND EXISTS (
    SELECT 1 FROM medication_request mr
    WHERE mr.patient_id = p.id
    AND mr.status = 'active'
    -- Hypertension medication codes
  )
```

#### Step 3: Approval Workflow (If Enabled)

If workflow pauses at approval gate:

**Admin Dashboard**:
```bash
# Terminal 5
streamlit run app/web_ui/admin_dashboard.py --server.port 8502
```

**Access**: http://localhost:8502

- View pending approvals
- Approve requirements/phenotype
- **Verify in LangSmith**: Approval processing trace

#### Step 4: Complete Workflow

Monitor request until `complete` state

**Verify in LangSmith**:
- ✅ All 6 agents executed
- ✅ Complete workflow trace
- ✅ No errors
- ✅ Total execution time

---

## Test Scenario 3: LangGraph vs Legacy Comparison

**Goal**: Compare LangGraph orchestrator vs legacy orchestrator

### Test A: Legacy Orchestrator

```bash
export USE_LANGGRAPH_WORKFLOW=false
streamlit run app/web_ui/researcher_portal.py --server.port 8501
```

Submit test request, note:
- Execution time
- State transitions
- LangSmith trace structure

### Test B: LangGraph Orchestrator

```bash
export USE_LANGGRAPH_WORKFLOW=true
streamlit run app/web_ui/researcher_portal.py --server.port 8501
```

Submit same test request, compare:
- Execution time (should be similar)
- State transitions (23-state FSM)
- LangSmith trace structure (more detailed)
- Checkpointing (view in LangSmith)

**Expected Differences**:
- ✅ LangGraph shows detailed state graph
- ✅ Checkpoints visible in traces
- ✅ Better observability
- ✅ Same business logic results

---

## LangSmith Dashboard Analysis

### Key Metrics to Review

Visit: https://smith.langchain.com/projects/researchflow-production

1. **Traces**:
   - Filter by last hour
   - Group by agent type
   - Check execution times

2. **Feedback**:
   - Look for errors
   - Check success/failure rates

3. **Latency Analysis**:
   - Requirements gathering: < 5 seconds
   - Feasibility analysis: < 10 seconds
   - SQL generation: < 3 seconds

4. **Token Usage**:
   - Claude API calls
   - Token counts per request
   - Cost estimation

### Example Queries

**Find all requirements gathering calls**:
```
filter: name = "extract_requirements"
time: last 1 hour
```

**Find failed feasibility checks**:
```
filter: name = "validate_feasibility" AND status = "error"
```

**Find long-running SQL generations**:
```
filter: name = "generate_phenotype_sql" AND latency > 5000ms
```

---

## Success Criteria

### ✅ Requirements Gathering
- [ ] Natural language parsed correctly
- [ ] Structured requirements extracted
- [ ] LangSmith trace shows `RequirementsAgent`
- [ ] < 5 second execution time
- [ ] No errors

### ✅ Feasibility Analysis
- [ ] Cohort size estimated
- [ ] Feasibility score calculated (0.0-1.0)
- [ ] LangSmith trace shows `PhenotypeAgent`
- [ ] < 10 second execution time
- [ ] No errors

### ✅ SQL Generation
- [ ] Valid SQL-on-FHIR v2 query generated
- [ ] Query matches requirements
- [ ] Proper WHERE clause filters
- [ ] LangSmith trace shows SQL generation
- [ ] < 3 second execution time
- [ ] No errors

### ✅ Exploratory Portal
- [ ] Loads without errors
- [ ] Accepts natural language input
- [ ] Displays feasibility results
- [ ] Shows generated SQL
- [ ] Executes query successfully

### ✅ Formal Request Portal
- [ ] Form submission works
- [ ] Workflow progresses through states
- [ ] All agents execute correctly
- [ ] Request completes successfully
- [ ] LangSmith shows complete workflow

### ✅ LangGraph Integration
- [ ] Feature flag toggles correctly
- [ ] Both orchestrators work
- [ ] LangGraph shows better observability
- [ ] Checkpointing works
- [ ] No regressions in functionality

---

## Troubleshooting

### Issue: LangSmith traces not appearing

**Fix**:
```bash
# Verify env vars
echo $LANGCHAIN_TRACING_V2  # Should be "true"
echo $LANGCHAIN_API_KEY     # Should start with "lsv2_pt_"

# Restart Streamlit apps
pkill -f streamlit
# Re-export env vars and restart
```

### Issue: Portal won't start

**Fix**:
```bash
# Check database connection
psql -U researchflow -h localhost -p 5434 -d researchflow -c "SELECT 1;"

# Check HAPI FHIR
curl http://localhost:8081/fhir/metadata

# Check Redis
redis-cli ping
```

### Issue: SQL generation fails

**Fix**:
```bash
# Check HAPI database
psql -U hapi -h localhost -p 5433 -d hapi -c "SELECT COUNT(*) FROM patient;"

# Check ViewDefinition runner
grep VIEWDEF_RUNNER .env
# Should be: VIEWDEF_RUNNER=in_memory or postgres
```

---

## Test Results Template

```markdown
## Test Results - [DATE]

**Orchestrator**: [Legacy / LangGraph]
**LangSmith Project**: researchflow-production

### Test 1: Exploratory Portal
- Status: [PASS / FAIL]
- Query: [Natural language query]
- Cohort Size: [Number]
- Execution Time: [Seconds]
- LangSmith Trace: [URL]
- Issues: [None / Description]

### Test 2: Formal Request Portal
- Status: [PASS / FAIL]
- Request ID: [REQ-YYYYMMDD-XXXX]
- Final State: [complete / error / stuck]
- Execution Time: [Seconds]
- LangSmith Trace: [URL]
- Issues: [None / Description]

### Test 3: LangGraph Comparison
- Legacy Time: [Seconds]
- LangGraph Time: [Seconds]
- Performance: [Same / Better / Worse]
- Observability: [Improved / Same]
- Issues: [None / Description]

### LangSmith Metrics
- Total Traces: [Number]
- Success Rate: [Percentage]
- Avg Latency: [Milliseconds]
- Token Usage: [Total tokens]
- Errors: [Number]

### Overall Assessment
- ✅ Requirements Gathering: [PASS / FAIL]
- ✅ Feasibility Analysis: [PASS / FAIL]
- ✅ SQL Generation: [PASS / FAIL]
- ✅ Exploratory Portal: [PASS / FAIL]
- ✅ Formal Portal: [PASS / FAIL]
- ✅ LangGraph Integration: [PASS / FAIL]

### Recommendations
[Any improvements or issues to address]
```

---

**Ready to test!** Start with the exploratory portal for quick validation, then move to the formal portal for complete workflow testing.

**LangSmith Dashboard**: https://smith.langchain.com/projects/researchflow-production
