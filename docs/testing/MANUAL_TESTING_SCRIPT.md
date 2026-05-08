# Manual Testing Script - LangGraph Migration Pre-Production Validation

**Purpose**: Validate LangGraph migration with real LLM calls before 10% production rollout
**Tester**: [Your Name]
**Date**: [Test Execution Date]
**Duration**: ~3 hours
**Estimated Cost**: $4.50-$9.10 (Claude API + LangSmith)

---

## Table of Contents

1. [Environment Setup](#environment-setup)
2. [Priority 1 Tests](#priority-1-tests-critical)
   - Test 1: Requirements Gathering
   - Test 2: Feasibility Analysis
   - Test 3: SQL Generation
3. [Priority 2 Tests](#priority-2-tests-high-priority)
   - Test 4: Both Researcher Portals
   - Test 5: LangSmith Tracing
4. [Results Documentation](#results-documentation)
5. [Troubleshooting](#troubleshooting)

---

## Environment Setup

### Prerequisites Checklist

Before starting tests, verify:

- [ ] Python 3.11 environment active (`python --version`)
- [ ] All dependencies installed (`pip list | grep -E "anthropic|langchain|langsmith"`)
- [ ] API keys configured in `.env`:
  ```bash
  ANTHROPIC_API_KEY=sk-ant-api03-...  # Required
  LANGCHAIN_TRACING_V2=true           # Required
  LANGCHAIN_API_KEY=lsv2_pt_...       # Required
  LANGCHAIN_PROJECT=researchflow-manual-test  # Recommended
  ```
- [ ] PostgreSQL database running (`ps aux | grep postgres`)
- [ ] HAPI FHIR server running (check http://localhost:8080/fhir/metadata)
- [ ] Redis running for speed layer (`redis-cli ping` → PONG)

### Step 1: Configure Feature Flags

```bash
cd /Users/jagnyesh/Development/FHIR_PROJECT

# Enable LangGraph workflow
export USE_LANGGRAPH_WORKFLOW=true
export LANGGRAPH_ROLLOUT_PCT=100  # Force 100% for testing

# Verify
echo "LangGraph enabled: $USE_LANGGRAPH_WORKFLOW"
echo "Rollout: $LANGGRAPH_ROLLOUT_PCT%"
```

### Step 2: Start Services

**Terminal 1 - Exploratory Analytics Portal**:
```bash
source .venv/bin/activate
streamlit run app/web_ui/research_notebook.py --server.port 8501
```

**Terminal 2 - Formal Request Portal**:
```bash
source .venv/bin/activate
streamlit run app/web_ui/researcher_portal.py --server.port 8502
```

**Terminal 3 - Admin Dashboard**:
```bash
source .venv/bin/activate
streamlit run app/web_ui/admin_dashboard.py --server.port 8503
```

### Step 3: Verify LangSmith Access

1. Open: https://smith.langchain.com/
2. Navigate to project: `researchflow-manual-test` (or your configured project)
3. Verify you can see traces (may be empty initially)
4. Keep this tab open for monitoring during tests

### Step 4: Verify Database Connection

```bash
# Test database connectivity
psql -h localhost -U researchflow -d researchflow -c "SELECT COUNT(*) FROM research_requests;"

# Should return a count (may be 0 if fresh database)
```

**Ready to Begin Testing** ✅

---

## Priority 1 Tests (CRITICAL)

### Test 1: Requirements Gathering with Real Claude API

**Test ID**: P1-T1
**Duration**: 30 minutes
**Estimated Cost**: $0.50-$1.00
**Objective**: Validate Requirements Agent extracts criteria accurately from natural language

---

#### Test 1.1: Simple Query - Single Condition

**Input Query**:
```
I need all patients with type 2 diabetes diagnosed in 2024
```

**Procedure**:
1. Open Exploratory Analytics Portal (http://localhost:8501)
2. In chat interface, type the query above
3. Click "Submit" or press Enter
4. **Wait for response** (5-10 seconds expected)
5. **Take screenshot** of response

**Expected Results**:
- ✅ Agent responds within 10 seconds
- ✅ Extracted requirements include:
  - Condition: "Type 2 Diabetes" (ICD-10: E11.* or SNOMED: 44054006)
  - Date range: 2024-01-01 to 2024-12-31
  - Data elements: Patient demographics + diagnosis codes
- ✅ No error messages displayed

**LangSmith Validation**:
1. Go to LangSmith dashboard
2. Filter: Last 5 minutes
3. Find trace for this query (search by "type 2 diabetes")
4. Verify trace contains:
   - Workflow execution step
   - RequirementsAgent LLM call
   - Prompt shows the user query
   - Response contains extracted requirements
5. **Take screenshot** of LangSmith trace

**Pass/Fail Criteria**:
- [ ] **PASS**: All criteria extracted correctly, response time < 10s, LangSmith trace visible
- [ ] **FAIL**: Missing criteria, error occurred, or no LangSmith trace

**If FAIL**: Document error, take screenshot, note in results section

---

#### Test 1.2: Complex Query - Multiple Conditions

**Input Query**:
```
Find female patients over 50 years old with both diabetes and hypertension
who had a hospital admission in 2023. I need de-identified data only.
```

**Procedure**:
1. In same Exploratory Portal session, type the complex query
2. Submit and wait for response
3. **Take screenshot** of response

**Expected Results**:
- ✅ Extracted requirements include ALL of:
  - Gender: Female
  - Age: > 50 years
  - Condition 1: Diabetes
  - Condition 2: Hypertension
  - Event: Hospital admission
  - Date range: 2023-01-01 to 2023-12-31
  - PHI level: De-identified
- ✅ Response shows extracted criteria in structured format
- ✅ Agent asks "Is this correct?" or similar confirmation

**LangSmith Validation**:
1. Find trace for this query in LangSmith
2. Verify prompt engineering handles multiple concepts
3. Check token usage (expect 1000-2000 tokens)
4. **Take screenshot** showing multi-concept extraction

**Pass/Fail Criteria**:
- [ ] **PASS**: All 7 criteria extracted, confirmation asked, trace complete
- [ ] **FAIL**: Any criteria missing, no confirmation, or error

---

#### Test 1.3: Ambiguous Query - Multi-Turn Conversation

**Input Query**:
```
I need diabetes patients
```

**Procedure**:
1. Submit the ambiguous query
2. **Expect**: Agent asks clarifying questions like:
   - "What type of diabetes? (Type 1, Type 2, or both?)"
   - "What date range?"
   - "What data elements do you need?"
3. **Respond** to each question:
   - Type: "Type 2"
   - Date: "Last 2 years"
   - Data: "Demographics and HbA1c lab results"
4. Continue conversation until agent has complete requirements
5. **Take screenshot** of full conversation

**Expected Results**:
- ✅ Agent asks 2-4 clarifying questions
- ✅ Each response is contextually relevant
- ✅ Final requirements summary includes all answered criteria
- ✅ Multi-turn conversation state maintained

**LangSmith Validation**:
1. Find trace showing conversation history
2. Verify each turn has separate LLM call
3. Check context includes previous messages
4. **Take screenshot** of conversation trace chain

**Pass/Fail Criteria**:
- [ ] **PASS**: Clarifying questions asked, context maintained, complete requirements
- [ ] **FAIL**: No questions, context lost, or conversation breaks

---

### Test 2: Feasibility Analysis Accuracy

**Test ID**: P1-T2
**Duration**: 20 minutes
**Estimated Cost**: $0.20-$0.50
**Objective**: Validate SQL generation and cohort size estimates

---

#### Test 2.1: Known Cohort - Accuracy Check

**Setup**: Query database for actual count
```sql
-- Run this BEFORE the test
SELECT COUNT(DISTINCT patient_id)
FROM conditions
WHERE code_system = 'http://snomed.info/sct'
AND code = '44054006'  -- Type 2 Diabetes
AND recorded_date >= '2024-01-01';

-- Note the actual count: ___________
```

**Input Query** (in Exploratory Portal):
```
How many patients have type 2 diabetes diagnosed in 2024?
```

**Procedure**:
1. Submit query and wait for feasibility result
2. Note the **estimated cohort size** from response
3. Compare to actual count from SQL query above
4. Calculate accuracy: `|estimated - actual| / actual * 100%`

**Expected Results**:
- ✅ Estimated count within ±15% of actual count
- ✅ Feasibility score displayed (0.0 to 1.0)
- ✅ SQL query shown in response (optional)
- ✅ Response time < 10 seconds

**LangSmith Validation**:
1. Find trace showing SQL generation
2. Verify generated SQL matches query intent
3. Check PhenotypeAgent execution
4. **Take screenshot** of SQL generation trace

**Pass/Fail Criteria**:
- [ ] **PASS**: Accuracy within ±15%, response time OK, SQL valid
- [ ] **FAIL**: Accuracy > 15% off, slow response, or SQL error

**Accuracy Calculation**:
```
Actual count: ___________
Estimated count: ___________
Difference: ___________ (|estimated - actual|)
Accuracy: ___________% (difference / actual * 100)

Pass if accuracy < 15%
```

---

#### Test 2.2: Empty Result - Zero Cohort

**Input Query**:
```
Find patients older than 200 years
```

**Expected Results**:
- ✅ Estimated cohort size = 0
- ✅ Feasibility score = 0.0
- ✅ Message indicates "No patients match criteria" or similar
- ✅ No SQL execution errors

**Pass/Fail Criteria**:
- [ ] **PASS**: Cohort = 0, feasibility = 0.0, no errors
- [ ] **FAIL**: Non-zero result, SQL error, or crash

---

#### Test 2.3: Large Cohort - Performance Check

**Input Query**:
```
Find all patients in the database
```

**Procedure**:
1. Submit query
2. **Start timer**
3. Wait for response
4. **Stop timer** when results displayed
5. Note response time

**Expected Results**:
- ✅ Estimated cohort size > 1000 (large number)
- ✅ Response time < 10 seconds
- ✅ System remains responsive (no freeze)
- ✅ Feasibility score displayed

**Performance Validation**:
- Response time: ___________ seconds
- Pass if < 10 seconds
- Warn if 10-20 seconds
- Fail if > 20 seconds

**Pass/Fail Criteria**:
- [ ] **PASS**: Large count returned, time < 10s, system responsive
- [ ] **FAIL**: Timeout, system freeze, or error

---

### Test 3: SQL Generation Quality

**Test ID**: P1-T3
**Duration**: 20 minutes
**Estimated Cost**: $0.30-$0.60
**Objective**: Validate SQL-on-FHIR v2 query generation for complex criteria

---

#### Test 3.1: Multi-Condition Query

**Input Query**:
```
Find patients with both diabetes and hypertension, aged between 45 and 65
```

**Procedure**:
1. Submit query via Exploratory Portal
2. **Copy generated SQL** from response (if displayed) or check LangSmith trace
3. Paste SQL into validation section below
4. Execute SQL manually to verify it runs

**Expected SQL Structure**:
```sql
-- Should contain elements like:
SELECT DISTINCT p.patient_id
FROM patient p
JOIN conditions c1 ON c1.patient_id = p.id  -- Diabetes
JOIN conditions c2 ON c2.patient_id = p.id  -- Hypertension
WHERE c1.code IN ('E11.9', '44054006')  -- Diabetes codes
  AND c2.code IN ('I10', '38341003')    -- Hypertension codes
  AND EXTRACT(YEAR FROM AGE(p.birth_date)) BETWEEN 45 AND 65;
```

**Validation Checklist**:
- [ ] SQL has 2+ JOIN clauses (one per condition)
- [ ] WHERE clause uses AND logic for multiple conditions
- [ ] Age calculation present (AGE() or date math)
- [ ] BETWEEN clause for age range (45-65)
- [ ] SQL executes without errors

**Manual Execution**:
```bash
# Copy generated SQL and test
psql -h localhost -U researchflow -d researchflow -c "
[PASTE GENERATED SQL HERE]
"

# Should return results or empty set (no errors)
```

**Pass/Fail Criteria**:
- [ ] **PASS**: All checklist items ✅, SQL executes, results returned
- [ ] **FAIL**: Missing clauses, SQL syntax error, or no results

---

#### Test 3.2: Date Range Filtering

**Input Query**:
```
Find patients admitted to hospital between January 1, 2023 and December 31, 2023
```

**Expected SQL Structure**:
```sql
-- Should contain date filtering like:
WHERE encounter_date >= '2023-01-01'
  AND encounter_date <= '2023-12-31'
-- OR
WHERE encounter_date BETWEEN '2023-01-01' AND '2023-12-31'
```

**Validation Checklist**:
- [ ] Date literals in ISO format (YYYY-MM-DD)
- [ ] Both start and end dates present
- [ ] Correct comparison operators (>=, <=, or BETWEEN)
- [ ] Timezone handling appropriate (UTC or local)
- [ ] SQL executes without errors

**Pass/Fail Criteria**:
- [ ] **PASS**: Date filtering correct, SQL executes
- [ ] **FAIL**: Wrong date format, missing dates, or error

---

#### Test 3.3: Exclusion Criteria

**Input Query**:
```
Find diabetic patients EXCEPT those who are pregnant
```

**Expected SQL Structure**:
```sql
-- Should use NOT EXISTS or LEFT JOIN with NULL:

-- Option 1: NOT EXISTS
SELECT DISTINCT p.patient_id
FROM patient p
JOIN conditions c ON c.patient_id = p.id
WHERE c.code IN ('E11.9', '44054006')  -- Diabetes
  AND NOT EXISTS (
    SELECT 1 FROM conditions c2
    WHERE c2.patient_id = p.id
    AND c2.code IN ('Z33.1', '77386006')  -- Pregnancy
  );

-- Option 2: LEFT JOIN with NULL check
SELECT DISTINCT p.patient_id
FROM patient p
JOIN conditions c1 ON c1.patient_id = p.id
LEFT JOIN conditions c2 ON c2.patient_id = p.id AND c2.code IN ('Z33.1', '77386006')
WHERE c1.code IN ('E11.9', '44054006')
  AND c2.id IS NULL;  -- Exclude if pregnancy record exists
```

**Validation Checklist**:
- [ ] Uses NOT EXISTS or LEFT JOIN + IS NULL pattern
- [ ] Exclusion logic syntactically correct
- [ ] Pregnancy codes included (ICD-10: Z33.* or SNOMED)
- [ ] SQL executes without errors
- [ ] Results exclude pregnant patients (verify with test data)

**Pass/Fail Criteria**:
- [ ] **PASS**: Exclusion logic correct, SQL executes, results accurate
- [ ] **FAIL**: Wrong exclusion pattern, SQL error, or incorrect results

---

## Priority 2 Tests (HIGH PRIORITY)

### Test 4: Both Researcher Portals End-to-End

**Test ID**: P2-T4
**Duration**: 40 minutes
**Estimated Cost**: $1.50-$3.00
**Objective**: Validate full workflow through both UIs with LangGraph

---

#### Test 4.1: Exploratory Analytics Portal (8501)

**Sub-Test 4.1.1: Simple Query**

1. Navigate to http://localhost:8501
2. Verify page loads without errors
3. Check browser console (F12) for JavaScript errors - **should be none**
4. Submit: "How many patients have diabetes?"
5. Verify:
   - [ ] Response appears within 10 seconds
   - [ ] Chart/visualization renders (if applicable)
   - [ ] Cohort size displayed
   - [ ] Export button visible (if applicable)

**Sub-Test 4.1.2: Complex Query with Visualization**

1. Submit: "Show me age distribution of diabetic patients by gender"
2. Verify:
   - [ ] Query processed successfully
   - [ ] Data table or chart displayed
   - [ ] Gender breakdown visible
   - [ ] Age ranges shown
3. **Take screenshot** of visualization

**Sub-Test 4.1.3: Chat History**

1. Submit 3-4 queries in sequence
2. Scroll up to see previous queries
3. Verify:
   - [ ] All queries and responses preserved
   - [ ] Chat history readable
   - [ ] Context maintained across queries

**LangSmith Validation (4.1)**:
1. Check LangSmith for last 3 traces
2. Verify all Exploratory Portal queries captured
3. **Take screenshot** showing trace list

**Pass/Fail Criteria (4.1)**:
- [ ] **PASS**: All queries work, no errors, traces visible
- [ ] **FAIL**: Any query fails, UI errors, or missing traces

---

#### Test 4.2: Formal Request Portal (8502)

**Full Workflow Test**: Submit → Approval → Delivery

**Step 1: Submit Research Request**

1. Navigate to http://localhost:8502
2. Verify "🎲 Selected for LangGraph" caption appears (confirms feature flag)
3. Fill out form:
   ```
   Researcher Name: Manual Test User
   Email: test@example.com
   Department: Data Science
   IRB Number: TEST-MANUAL-001

   Research Request:
   I need patient demographics and HbA1c lab results for patients
   with type 2 diabetes diagnosed in 2024. De-identified data only.
   ```
4. Click "Submit Request"
5. **Note the Request ID** (e.g., REQ-20251110-ABC123): ___________
6. Verify confirmation message appears

**Step 2: Monitor Workflow State**

1. Navigate to Admin Dashboard (http://localhost:8503)
2. Go to "Active Requests" tab
3. Find your request ID
4. Note current state: ___________
5. Refresh page every 30 seconds
6. Observe state transitions:
   - `new_request` → `requirements_gathering` → `requirements_approval` → ...
7. **Track states observed**:
   - [ ] new_request
   - [ ] requirements_gathering
   - [ ] requirements_approval (or feasibility_validation)
   - [ ] Other states: ___________

**Step 3: Approval Workflow** (if applicable)

1. In Admin Dashboard, go to "Pending Approvals" tab
2. If approval appears for your request:
   - Click "View Details"
   - Review extracted requirements
   - Click "Approve" (or appropriate action)
   - Verify state advances
3. If no approval appears:
   - Check if workflow auto-progressed (stub agents may skip)
   - Note behavior: ___________

**Step 4: Complete Workflow**

1. Monitor request until it reaches one of:
   - `complete`
   - `delivered`
   - `error` / `escalated` (document if this happens)
2. Total workflow duration: ___________ seconds/minutes
3. Final state: ___________

**LangSmith Validation (4.2)**:
1. Search LangSmith for your request ID
2. Verify hierarchical trace:
   - Top-level: FullWorkflow execution
   - Child traces: Agent executions (RequirementsAgent, PhenotypeAgent, etc.)
   - Leaf traces: Individual LLM calls
3. **Take screenshot** of trace hierarchy
4. Count total LLM calls: ___________
5. Sum token usage: ___________ tokens

**Pass/Fail Criteria (4.2)**:
- [ ] **PASS**: Request submitted, states transition, approval works, complete trace
- [ ] **FAIL**: Request fails, stuck state, no approvals, or missing traces

---

### Test 5: LangSmith Tracing at Scale

**Test ID**: P2-T5
**Duration**: 20 minutes
**Estimated Cost**: $2.00-$4.00
**Objective**: Validate observability with multiple concurrent requests

---

#### Test 5.1: Concurrent Request Handling

**Setup**: Prepare 5 test queries

1. Query 1: "Patients with diabetes in 2024"
2. Query 2: "Female patients over 60 with hypertension"
3. Query 3: "Diabetic patients with HbA1c > 7.0"
4. Query 4: "Patients admitted for heart failure in 2023"
5. Query 5: "All patients with cancer diagnosis"

**Procedure**:

1. Open 5 browser tabs, each with Exploratory Portal (http://localhost:8501)
2. **Start timer**
3. Quickly submit all 5 queries (within 30 seconds)
4. **Stop timer** when last response received
5. Total time for 5 queries: ___________ seconds

**Concurrent Execution Check**:
- Expected: 40-60 seconds total (some parallel processing)
- Red flag: > 100 seconds (indicates serial processing/blocking)

**LangSmith Validation**:

1. Navigate to LangSmith dashboard
2. Filter: Last 5 minutes
3. **Count traces**: Should see 5 workflow traces
4. Check trace capture time:
   - Traces should appear within 30 seconds of query execution
   - Note any delayed traces: ___________
5. Verify trace completeness:
   - [ ] All 5 queries have traces
   - [ ] Each trace has workflow + agent steps
   - [ ] Token usage displayed for each
   - [ ] Latency metrics visible
6. **Take screenshot** showing all 5 traces

**Performance Analysis**:

For each trace, record:

| Query | Trace ID | Tokens | Latency (ms) | Status |
|-------|----------|--------|--------------|--------|
| 1     |          |        |              |        |
| 2     |          |        |              |        |
| 3     |          |        |              |        |
| 4     |          |        |              |        |
| 5     |          |        |              |        |

**Pass/Fail Criteria**:
- [ ] **PASS**: All 5 traces visible, capture time < 30s, no performance degradation
- [ ] **FAIL**: Missing traces, delayed capture (> 1 min), or system slowdown

---

#### Test 5.2: Trace Completeness Check

**Objective**: Verify traces contain all expected data

For one of the 5 traces above, drill down and verify:

1. **Trace Metadata**:
   - [ ] Request ID present
   - [ ] Timestamp correct
   - [ ] Project name correct (`researchflow-manual-test`)

2. **Trace Hierarchy**:
   - [ ] Top level: Workflow run
   - [ ] Second level: Agent executions (Requirements, Phenotype, etc.)
   - [ ] Third level: LLM calls (Claude API)

3. **LLM Call Details** (click into one LLM call):
   - [ ] Prompt visible (can read full prompt text)
   - [ ] Response visible (can read full response)
   - [ ] Token count displayed (prompt + completion tokens)
   - [ ] Latency displayed (milliseconds)
   - [ ] Model name visible (e.g., "claude-3-5-sonnet-20241022")

4. **Error Handling** (if any errors occurred):
   - [ ] Error traces marked distinctly (red icon or error tag)
   - [ ] Error message visible in trace
   - [ ] Stack trace available (if applicable)

**Pass/Fail Criteria**:
- [ ] **PASS**: All trace elements present, readable, and complete
- [ ] **FAIL**: Missing metadata, incomplete hierarchy, or can't view LLM details

---

## Results Documentation

### Test Summary Table

| Test ID | Test Name | Status | Duration | Cost | Notes |
|---------|-----------|--------|----------|------|-------|
| P1-T1.1 | Simple Requirements | ⬜ PASS / ⬜ FAIL | _____ min | $_____ | |
| P1-T1.2 | Complex Requirements | ⬜ PASS / ⬜ FAIL | _____ min | $_____ | |
| P1-T1.3 | Ambiguous Requirements | ⬜ PASS / ⬜ FAIL | _____ min | $_____ | |
| P1-T2.1 | Known Cohort | ⬜ PASS / ⬜ FAIL | _____ min | $_____ | |
| P1-T2.2 | Empty Result | ⬜ PASS / ⬜ FAIL | _____ min | $_____ | |
| P1-T2.3 | Large Cohort | ⬜ PASS / ⬜ FAIL | _____ min | $_____ | |
| P1-T3.1 | Multi-Condition SQL | ⬜ PASS / ⬜ FAIL | _____ min | $_____ | |
| P1-T3.2 | Date Range SQL | ⬜ PASS / ⬜ FAIL | _____ min | $_____ | |
| P1-T3.3 | Exclusion SQL | ⬜ PASS / ⬜ FAIL | _____ min | $_____ | |
| P2-T4.1 | Exploratory Portal | ⬜ PASS / ⬜ FAIL | _____ min | $_____ | |
| P2-T4.2 | Formal Portal | ⬜ PASS / ⬜ FAIL | _____ min | $_____ | |
| P2-T5.1 | Concurrent Requests | ⬜ PASS / ⬜ FAIL | _____ min | $_____ | |
| P2-T5.2 | Trace Completeness | ⬜ PASS / ⬜ FAIL | _____ min | $_____ | |

**Overall Statistics**:
- Total tests executed: _____ / 13
- Tests passed: _____
- Tests failed: _____
- Pass rate: _____%
- Total duration: _____ hours
- Total cost: $_____

---

### Critical Findings

**Priority 1 Findings** (Blockers for 10% rollout):

1. **Issue**: ___________
   - Severity: 🔴 Critical / 🟡 High / 🟢 Low
   - Test ID: P1-___
   - Description: ___________
   - Impact: ___________
   - Recommendation: Fix before rollout / Accept risk

2. **Issue**: ___________
   - [Repeat for each critical issue]

**Priority 2 Findings** (Can be addressed during rollout):

1. **Issue**: ___________
   - [Same structure as above]

---

### Screenshots Collected

Attach screenshots to test results document:

- [ ] Screenshot 1: Test 1.1 - Simple requirements response
- [ ] Screenshot 2: Test 1.1 - LangSmith trace
- [ ] Screenshot 3: Test 1.2 - Complex requirements response
- [ ] Screenshot 4: Test 1.3 - Multi-turn conversation
- [ ] Screenshot 5: Test 4.1 - Exploratory portal visualization
- [ ] Screenshot 6: Test 4.2 - Formal portal workflow states
- [ ] Screenshot 7: Test 4.2 - LangSmith trace hierarchy
- [ ] Screenshot 8: Test 5.1 - Five concurrent traces in LangSmith
- [ ] Screenshot 9: Test 5.2 - Detailed LLM call trace

---

### Performance Metrics

**Response Times** (all in seconds):

| Metric | Target | Actual | Status |
|--------|--------|--------|--------|
| Simple query (T1.1) | < 10s | _____ | ⬜ PASS / ⬜ FAIL |
| Complex query (T1.2) | < 15s | _____ | ⬜ PASS / ⬜ FAIL |
| Feasibility analysis (T2.1) | < 10s | _____ | ⬜ PASS / ⬜ FAIL |
| Large cohort (T2.3) | < 10s | _____ | ⬜ PASS / ⬜ FAIL |
| Full workflow (T4.2) | < 3 min | _____ | ⬜ PASS / ⬜ FAIL |

**Cost Analysis**:

| Component | Estimated | Actual | Variance |
|-----------|-----------|--------|----------|
| Claude API calls | $4.00-$8.00 | $_____ | _____ |
| LangSmith traces | $0.50-$1.10 | $_____ | _____ |
| **Total** | **$4.50-$9.10** | **$_____** | **_____** |

**API Call Distribution**:

- Total Claude API calls: _____
- Average tokens per call: _____
- Total tokens consumed: _____
- Average cost per workflow: $_____

---

### Go/No-Go Recommendation

**Tester**: [Your Name]
**Date**: [Test Completion Date]

**Decision**: ⬜ GO - Proceed to 10% rollout / ⬜ NO-GO - Fix issues first

**Rationale**:

_[Explain your decision based on test results. Consider:]_

1. **Priority 1 Tests**: Did all critical tests pass?
   - Requirements gathering accuracy: ____%
   - Feasibility analysis accuracy: ____%
   - SQL generation quality: _____/3 tests passed

2. **Priority 2 Tests**: Are portals and observability working?
   - Exploratory portal: Working / Issues
   - Formal portal: Working / Issues
   - LangSmith tracing: 100% / ____% capture rate

3. **Performance**: Are response times acceptable?
   - Average query time: _____ seconds
   - Full workflow time: _____ minutes
   - Within targets: Yes / No

4. **Risks Identified**:
   - [List any concerns or risks]

5. **Mitigation Plan** (if NO-GO):
   - Issue 1: ___________
     - Fix: ___________
     - Owner: ___________
     - ETA: _____ days
   - Issue 2: ___________
     - [Repeat]

**Next Steps**:

If **GO**:
- [ ] Update `docs/testing/E2E_TESTING_REPORT.md` with results
- [ ] Share results with team for review
- [ ] Schedule 10% canary deployment (target date: _______)
- [ ] Prepare monitoring dashboards
- [ ] Review rollback procedures

If **NO-GO**:
- [ ] Create GitHub issues for each critical finding
- [ ] Assign owners and due dates
- [ ] Re-test after fixes deployed
- [ ] Document lessons learned

---

## Troubleshooting

### Common Issues and Solutions

#### Issue: "ANTHROPIC_API_KEY not found"

**Symptom**: Error when submitting query, no LLM response

**Solution**:
```bash
# Verify .env file has key
cat .env | grep ANTHROPIC_API_KEY

# If missing, add it
echo "ANTHROPIC_API_KEY=sk-ant-api03-YOUR-KEY" >> .env

# Restart Streamlit apps
pkill -f streamlit
streamlit run app/web_ui/research_notebook.py --server.port 8501 &
streamlit run app/web_ui/researcher_portal.py --server.port 8502 &
```

---

#### Issue: LangSmith traces not appearing

**Symptom**: Queries work but no traces in LangSmith dashboard

**Solution**:
```bash
# Check environment variables
echo $LANGCHAIN_TRACING_V2
echo $LANGCHAIN_API_KEY

# Should be "true" and "lsv2_pt_..." respectively
# If not set:
export LANGCHAIN_TRACING_V2=true
export LANGCHAIN_API_KEY=lsv2_pt_YOUR-KEY

# Verify LangSmith connection
python -c "
from langsmith import Client
client = Client()
print('LangSmith connected successfully')
"

# Restart services
```

---

#### Issue: "Feature flag not working"

**Symptom**: No "🎲 Selected for LangGraph" caption in UI

**Solution**:
```bash
# Check feature flag
echo $USE_LANGGRAPH_WORKFLOW
echo $LANGGRAPH_ROLLOUT_PCT

# Should be "true" and "100"
# If not:
export USE_LANGGRAPH_WORKFLOW=true
export LANGGRAPH_ROLLOUT_PCT=100

# Restart Streamlit (feature flags read at startup)
pkill -f streamlit
streamlit run app/web_ui/researcher_portal.py --server.port 8502 &
```

---

#### Issue: Database connection errors

**Symptom**: "could not connect to server" or "FATAL: database does not exist"

**Solution**:
```bash
# Check PostgreSQL running
pg_isready -h localhost

# If not running:
brew services start postgresql@15  # macOS
# OR
sudo systemctl start postgresql  # Linux

# Verify database exists
psql -h localhost -U postgres -c "\l" | grep researchflow

# If missing, create it
psql -h localhost -U postgres -c "CREATE DATABASE researchflow;"
```

---

#### Issue: Slow performance (> 20 seconds per query)

**Possible Causes**:

1. **Cold start**: First query after restart is slower
   - Solution: Run 1-2 warm-up queries, then restart timing

2. **Database not indexed**:
   - Check query execution plan: `EXPLAIN ANALYZE [your query]`
   - Add indexes if needed

3. **Network latency to Claude API**:
   - Check internet connection
   - Verify API endpoint responding: `curl https://api.anthropic.com/v1/messages -I`

4. **LangSmith tracing overhead**:
   - Temporarily disable: `export LANGCHAIN_TRACING_V2=false`
   - Re-test
   - If faster, tracing is cause (document as finding)

---

#### Issue: Test fails with "RuntimeError: threads can only be started once"

**Symptom**: Checkpointer error, workflow doesn't progress

**Solution**:
```python
# This was fixed in Sprint 7, but if you still see it:

# Clear checkpointer cache
python -c "
from app.langchain_orchestrator.persistence import clear_checkpointer_cache
clear_checkpointer_cache()
print('Cache cleared')
"

# Delete checkpoint database and restart
rm data/langgraph_checkpoints.db
# Restart services
```

---

## Appendix: Quick Reference

### URLs

- Exploratory Analytics Portal: http://localhost:8501
- Formal Request Portal: http://localhost:8502
- Admin Dashboard: http://localhost:8503
- HAPI FHIR Server: http://localhost:8080/fhir/metadata
- LangSmith Dashboard: https://smith.langchain.com/

### Key Commands

```bash
# Start all services
./scripts/start_all.sh

# Check service status
lsof -i :8501  # Exploratory portal
lsof -i :8502  # Formal portal
lsof -i :8503  # Admin dashboard

# View logs
tail -f /tmp/exploratory_portal.log
tail -f /tmp/researcher_portal.log

# Database queries
psql -h localhost -U researchflow -d researchflow

# Clear cache/restart
rm data/langgraph_checkpoints.db
pkill -f streamlit
```

### Success Criteria Summary

**Must Pass (Blockers)**:
- ✅ Requirements extraction: 100% accuracy
- ✅ Feasibility accuracy: ±15% of actual
- ✅ SQL generation: All queries execute without errors
- ✅ Response times: < 10 seconds per query
- ✅ LangSmith: 100% trace capture rate

**Should Pass (Can address during rollout)**:
- ✅ Both portals: End-to-end workflows complete
- ✅ Performance: < 3 minutes full workflow
- ✅ Concurrent: 5 requests without degradation

---

**End of Manual Testing Script**

Document results in: `docs/testing/MANUAL_TEST_RESULTS_[DATE].md`

For questions or issues during testing, refer to:
- `docs/LANGGRAPH_MIGRATION_GUIDE.md` - Deployment guide
- `docs/POST_DEPLOYMENT_TESTING_GUIDE.md` - Production validation
- `docs/sprints/archive/SPRINT_07_LANGGRAPH_COMPLETION.md` - Sprint 7 completion report
