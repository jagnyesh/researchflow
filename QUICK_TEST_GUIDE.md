# Quick Test Guide - AI Capabilities with LangSmith

**Goal**: Test Requirements Gathering, Feasibility Analysis, and SQL Generation with LangSmith tracing

---

## 🚀 Quick Start (5 minutes)

### 1. Start Services & Portals

```bash
# Option A: Start all portals at once
./scripts/test_with_langsmith.sh all

# Option B: Start one portal
./scripts/test_with_langsmith.sh exploratory  # Port 8503
# OR
./scripts/test_with_langsmith.sh formal       # Port 8501
```

### 2. Open LangSmith Dashboard

**URL**: https://smith.langchain.com/projects/researchflow-production

Keep this open in a separate browser tab to watch traces in real-time.

---

## 📊 Test 1: Exploratory Portal (Fast Testing)

**Portal**: http://localhost:8503

### Test Case: Diabetes + Hypertension Study

**Enter this query**:
```
Find female patients over 50 years old with type 2 diabetes
and hypertension who had a hospital admission in 2023
```

**What to Observe**:

1. **Requirements Gathering** (AI extracts needs):
   - ✅ Should parse: "female", "age > 50", "diabetes", "hypertension", "admission 2023"
   - ✅ Should structure requirements correctly
   - **LangSmith**: Look for `QueryInterpreter` or `RequirementsAgent` trace

2. **Feasibility Analysis** (AI provides counts):
   - ✅ Should show estimated cohort size (e.g., "~50 patients")
   - ✅ Should calculate feasibility score (0.0-1.0)
   - **LangSmith**: Look for `FeasibilityService` trace

3. **SQL Generation** (AI builds SQL-on-FHIR v2):
   - ✅ Should generate SQL with:
     - `WHERE p.gender = 'female'`
     - `WHERE age > 50`
     - `WHERE condition codes IN (diabetes codes)`
     - `WHERE condition codes IN (hypertension codes)`
     - `WHERE encounter date BETWEEN 2023-01-01 AND 2023-12-31`
   - **LangSmith**: Look for SQL generation trace with query text

### LangSmith Verification

In LangSmith dashboard:
1. Filter by last 5 minutes
2. You should see traces for:
   - `extract_requirements` or `interpret_query`
   - `calculate_feasibility` or `validate_feasibility`
   - `generate_sql` or `generate_phenotype_sql`

3. Click each trace to see:
   - **Input**: Your natural language query
   - **Output**: Structured requirements, feasibility score, SQL
   - **Latency**: How long each step took
   - **Tokens**: Claude API token usage

---

## 📝 Test 2: Formal Request Portal (Full Workflow)

**Portal**: http://localhost:8501

### Test Case: Heart Failure Medication Study

**Fill Form**:

**Researcher Information**:
- Name: `Dr. Jane Smith`
- Email: `jsmith@hospital.edu`
- Department: `Cardiology`
- IRB Number: `IRB-2025-001`

**Data Request**:
```
I need patient demographics, medication records, and lab results
for heart failure patients on ACE inhibitors or ARBs who had
elevated BNP levels during 2023.
```

**Inclusion Criteria**:
```
- Age >= 65 years
- Diagnosis: Heart Failure (I50.x)
- Medication: ACE inhibitor OR ARB
- Lab: BNP > 100 pg/mL
- Date: 2023-01-01 to 2023-12-31
```

**Exclusion Criteria**:
```
- Age < 18 years
- Pregnant patients
- End-stage renal disease
```

**Time Period**:
- Start Date: `2023-01-01`
- End Date: `2023-12-31`

**Data Elements** (select):
- ✓ Demographics (age, gender, race)
- ✓ Diagnoses (ICD codes)
- ✓ Medications (prescriptions)
- ✓ Lab Results (LOINC codes)

**PHI Level**: `De-identified (HIPAA Safe Harbor)`

**Submit Request**

### What to Observe

**In Portal**:
1. Request ID created (e.g., `REQ-20251103-ABC123`)
2. Status updates in sidebar:
   - `new_request` → `requirements_gathering` → `feasibility_validation` → ...

**In LangSmith**:
1. **Phase 1: Requirements Gathering**
   - Trace: `RequirementsAgent.execute_task`
   - Input: Form data + natural language description
   - Output: Structured requirements JSON

2. **Phase 2: Feasibility Analysis**
   - Trace: `PhenotypeAgent.execute_task` → `validate_feasibility`
   - Input: Structured requirements
   - Output:
     - Cohort size estimate
     - Feasibility score (0.0-1.0)
     - Whether request is feasible

3. **Phase 3: SQL Generation**
   - Trace: `PhenotypeAgent` → `generate_phenotype_sql`
   - Input: Requirements JSON
   - Output: SQL-on-FHIR v2 ViewDefinition

**Expected SQL Structure**:
```sql
-- Patient demographics
SELECT
  p.id as patient_id,
  EXTRACT(YEAR FROM AGE(NOW(), p.birthDate::date)) as age,
  p.gender,
  p.race
FROM patient p

-- Heart failure diagnosis
WHERE EXISTS (
  SELECT 1 FROM condition c
  WHERE c.patient_id = p.id
  AND c.code->>'code' LIKE 'I50%'  -- ICD-10 heart failure
)

-- ACE inhibitor or ARB medication
AND EXISTS (
  SELECT 1 FROM medication_request mr
  WHERE mr.patient_id = p.id
  AND mr.code IN (ACE_CODES or ARB_CODES)
  AND mr.status = 'active'
)

-- Elevated BNP lab result
AND EXISTS (
  SELECT 1 FROM observation o
  WHERE o.patient_id = p.id
  AND o.code->>'code' IN ('30934-4', '83107-3')  -- LOINC BNP codes
  AND CAST(o.value->>'value' AS FLOAT) > 100
  AND o.effectiveDateTime BETWEEN '2023-01-01' AND '2023-12-31'
)

-- Age filter
AND EXTRACT(YEAR FROM AGE(NOW(), p.birthDate::date)) >= 65
```

### LangSmith Workflow Trace

**If using LangGraph orchestrator** (`USE_LANGGRAPH_WORKFLOW=true`):

You'll see a beautiful workflow graph in LangSmith:

```
START → requirements_gathering → requirements_approval →
feasibility_validation → feasibility_approval →
schedule_kickoff → data_extraction → qa_validation →
data_delivery → END
```

Each node shows:
- ✅ Execution time
- ✅ Input/output state
- ✅ Checkpoints (for resumption)
- ✅ Errors (if any)

---

## 🔍 LangSmith Analysis

### Dashboard Views

1. **Traces View** (https://smith.langchain.com/projects/researchflow-production/traces)
   - Shows all traces in real-time
   - Filter by time, name, status
   - Click trace to see details

2. **Runs View**
   - Shows workflow runs
   - Group by agent type
   - See success/failure rates

3. **Feedback View**
   - Track errors
   - Add notes to traces

### Key Metrics to Check

| Metric | Target | How to Check |
|--------|--------|--------------|
| Requirements extraction | < 5 sec | Trace latency |
| Feasibility calculation | < 10 sec | Trace latency |
| SQL generation | < 3 sec | Trace latency |
| Complete workflow | < 60 sec | End-to-end trace |
| Token usage | < 10k tokens/request | Trace metadata |
| Error rate | 0% | Filter status=error |

### Example Queries in LangSmith

**Find slow SQL generations**:
```
name contains "generate_sql"
AND latency > 5000ms
```

**Find failed feasibility checks**:
```
name contains "feasibility"
AND status = "error"
```

**Find all workflow runs today**:
```
name = "research_request_workflow"
AND start_time > today
```

---

## ✅ Success Checklist

After running both tests, verify:

### Exploratory Portal
- [ ] Query interpreted correctly
- [ ] Feasibility score shown
- [ ] SQL generated and displayed
- [ ] Query executes without error
- [ ] LangSmith shows 3 traces (interpret, feasibility, SQL)

### Formal Portal
- [ ] Form submission successful
- [ ] Request ID created
- [ ] Workflow progresses through states
- [ ] All agents execute
- [ ] LangSmith shows complete workflow trace
- [ ] No errors in any trace

### LangSmith Dashboard
- [ ] All traces appear in real-time
- [ ] Token counts visible
- [ ] Execution times reasonable
- [ ] No error traces
- [ ] Workflow graph displays (if using LangGraph)

---

## 🐛 Common Issues

### Issue: Traces not appearing in LangSmith

**Check**:
```bash
# Verify env var
echo $LANGCHAIN_TRACING_V2  # Should be "true"

# Restart portal with explicit export
export LANGCHAIN_TRACING_V2=true
export LANGCHAIN_API_KEY=lsv2_pt_...
export LANGCHAIN_PROJECT=researchflow-production
streamlit run app/web_ui/research_notebook.py --server.port 8503
```

### Issue: SQL generation fails

**Check HAPI database connection**:
```bash
# Test connection
psql -U hapi -h localhost -p 5433 -d hapi -c "SELECT COUNT(*) FROM hfj_resource;"

# If connection fails, start HAPI
docker-compose -f config/docker-compose.yml up hapi-fhir hapi-db -d
```

### Issue: Portal shows "Error: No API key"

**Check .env**:
```bash
grep ANTHROPIC_API_KEY .env
# Should show: ANTHROPIC_API_KEY=sk-ant-...
```

---

## 📸 Screenshot Checklist

Capture these for documentation:

1. **Exploratory Portal**:
   - [ ] Query input
   - [ ] Feasibility results
   - [ ] Generated SQL

2. **Formal Portal**:
   - [ ] Form submission
   - [ ] Request status
   - [ ] Sidebar tracking

3. **LangSmith**:
   - [ ] Traces list
   - [ ] Detailed trace view
   - [ ] Workflow graph (if LangGraph)
   - [ ] Token usage stats

---

## 🎯 Next Steps

After successful testing:

1. **Document Results**:
   - Copy test results to `TEST_RESULTS_[DATE].md`
   - Note any issues or improvements
   - Share LangSmith trace URLs

2. **Production Readiness**:
   - If all tests pass with LangGraph
   - Consider enabling gradual rollout
   - See `docs/LANGGRAPH_MIGRATION_GUIDE.md`

3. **Performance Tuning**:
   - Review slow traces in LangSmith
   - Optimize prompt templates
   - Adjust cache settings

---

**Happy Testing!** 🚀

For detailed testing scenarios, see: `TEST_PLAN_LANGGRAPH.md`
For migration guide, see: `docs/LANGGRAPH_MIGRATION_GUIDE.md`
