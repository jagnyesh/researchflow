# E2E Testing Guide: Research Notebook & Portal with LangSmith Tracing

**Date**: October 31, 2025
**Purpose**: Manual end-to-end testing to verify LangSmith workflow tracing in production UIs
**Focus**: Verify experimental LangChain agents show full workflow traces vs production agents

---

## Prerequisites

### 1. Verify Services Running
```bash
# Check all UI ports are active
lsof -ti:8501,8502,8503

# Should see 3 process IDs (one for each UI)
# - 8501: Research Notebook (exploratory chat)
# - 8502: Researcher Portal (full workflow)
# - 8503: Admin Dashboard (monitoring)
```

### 2. Verify LangSmith Configuration
```bash
# Check environment variables
env | grep LANGCHAIN

# Should see:
# LANGCHAIN_TRACING_V2=true
# LANGCHAIN_API_KEY=lsv2_pt_your-langsmith-api-key-here
# LANGCHAIN_PROJECT=researchflow-production
```

### 3. Open LangSmith Dashboard
1. Go to: https://smith.langchain.com/
2. Select project: **researchflow-production**
3. Keep this tab open for real-time trace viewing

---

## Test 1: Research Notebook (Exploratory Chat) - Simple Query

### Step 1: Open Research Notebook
```bash
# Navigate to:
http://localhost:8501
```

### Step 2: Submit Test Query
**Test Message**: "I need all patients with type 2 diabetes diagnosed in 2024."

**Expected UI Behavior**:
- Chat interface shows your message
- Agent responds with clarifying questions or extracted requirements
- Response appears within 3-5 seconds

### Step 3: Check LangSmith Trace
1. Return to LangSmith dashboard (https://smith.langchain.com/)
2. Look for the most recent run (timestamp matches your test)
3. Click on the trace to expand

**What to Look For**:

**If Production Agent** (current default):
```
Run: extract_requirements (3.2s)
└─ LLM Call: Claude 3.5 Sonnet (3.1s)
   ├─ Input: system prompt + user message
   └─ Output: JSON with extracted requirements
```
- Single LLM call visible
- No workflow context
- No agent method breakdown

**If Experimental Agent** (after migration):
```
Run: gather_requirements (4.1s)
├─ extract_requirements (4.0s)
│  ├─ LLM Call: Claude 3.5 Sonnet (3.1s)
│  │  ├─ Input: system prompt + user message
│  │  └─ Output: JSON with extracted requirements
│  └─ _validate_extracted_requirements (0.3s)
│     └─ check_completeness (0.2s)
└─ save_to_database (0.1s)
```
- Full method tree visible
- Each step timed
- Complete workflow context

### Step 4: Document Findings
**Screenshot**: LangSmith trace
**Note**: Whether production or experimental agent was used
**Trace URL**: Copy from browser address bar

---

## Test 2: Research Notebook - Complex Multi-Turn Conversation

### Step 1: Start New Conversation
In Research Notebook, clear chat history (reload page or use "New Request" button if available)

### Step 2: Multi-Turn Dialogue

**Turn 1**: "I want to study diabetic patients."

**Expected**: Agent asks clarifying questions
- "What type of diabetes?"
- "What time period?"
- "Any specific medications?"

**Turn 2**: "Type 2 diabetes, diagnosed in the last year."

**Expected**: Agent extracts and confirms
- Shows extracted requirements
- Asks about additional criteria

**Turn 3**: "Also must be on metformin and age 45-65."

**Expected**: Agent updates requirements
- Adds medication criterion
- Adds age range
- May ask about exclusion criteria

### Step 3: Check LangSmith Traces
1. LangSmith should show **3 separate traces** (one per turn)
2. Each trace should show conversation history growing
3. Look for `conversation_history` in input parameters

**What to Compare**:

**Production Traces**:
- Each turn shows only LLM call
- No persistence layer visible
- No state management visible

**Experimental Traces**:
- Each turn shows full workflow
- `_update_conversation_state()` method visible
- `_save_requirements_to_db()` method visible
- Complete state transitions tracked

---

## Test 3: Researcher Portal - Full Workflow Submission

### Step 1: Open Researcher Portal
```bash
# Navigate to:
http://localhost:8502
```

### Step 2: Submit Full Request

**Form Fields**:
- **Title**: "Diabetes Metformin Cohort Study 2024"
- **Description**: "Find type 2 diabetes patients on metformin, age 45-65, diagnosed in 2024"
- **Inclusion Criteria**:
  - Type 2 diabetes (ICD-10: E11.*)
  - On metformin
  - Age 45-65
  - Diagnosed 2024
- **Exclusion Criteria**:
  - Dialysis patients
  - Pregnant women
- **Data Elements**:
  - Demographics
  - Medications
  - Lab results (HbA1c)
- **PHI Level**: "Limited Dataset"

### Step 3: Submit and Monitor
1. Click "Submit Request"
2. Note the Request ID (e.g., "REQ-2024-001")
3. Watch the status panel for workflow progression:
   - `new_request`
   - `requirements_gathering`
   - `feasibility_validation`
   - `schedule_kickoff`
   - etc.

### Step 4: Check LangSmith for Full Workflow
1. Return to LangSmith dashboard
2. Look for traces matching the Request ID
3. Should see **multiple traces** for each agent:
   - Requirements Agent: `gather_requirements`
   - Phenotype Agent: `validate_feasibility`
   - Calendar Agent: `schedule_kickoff_meeting`

**What to Look For**:

**Production Workflow**:
```
Trace 1: RequirementsAgent
└─ LLM Call (requirements extraction)

Trace 2: PhenotypeAgent
└─ LLM Call (SQL generation)

Trace 3: CalendarAgent
└─ LLM Call (meeting scheduling)
```
- Each agent = 1 trace with 1-2 LLM calls
- No inter-agent communication visible
- No orchestrator context visible

**Experimental Workflow** (GOAL):
```
Trace 1: gather_requirements
├─ extract_requirements
│  └─ LLM Call: Claude 3.5 Sonnet
├─ validate_completeness
├─ save_to_database
└─ return_to_orchestrator

Trace 2: validate_feasibility
├─ generate_phenotype_sql
│  └─ LLM Call: Claude 3.5 Sonnet
├─ execute_sql_query
│  └─ Database: SELECT COUNT(*)
├─ calculate_feasibility_score
└─ save_report

Trace 3: schedule_kickoff_meeting
├─ extract_meeting_requirements
│  └─ LLM Call: Claude 3.5 Sonnet
├─ generate_calendar_invite
├─ save_meeting_record
└─ return_confirmation
```
- Full method breakdown for each agent
- Database calls visible
- State transitions visible
- Complete orchestrator context

---

## Test 4: Side-by-Side Comparison (Production vs Experimental)

### Setup: Run Same Query Through Both Systems

**Option A: Use Feature Flag (if implemented)**
```python
# In .env or UI settings
EXPERIMENTAL_AGENT_ENABLED=true
EXPERIMENTAL_TRAFFIC_PERCENTAGE=50  # Route 50% to experimental
```

**Option B: Manual Script (manual_test.py)**
```bash
# From project root
PYTHONPATH=/Users/jagnyesh/Development/FHIR_PROJECT python manual_test.py
```

### Step 1: Run Script
```bash
# Select scenario
🧪 MANUAL AGENT TESTING
Available test scenarios:
  1. I need all patients with type 2 diabetes diagnosed in 2024.
  2. Find diabetic patients on metformin, age 45-65, with HbA1c > 7.5%.
  3. I want patients with heart failure. Exclude anyone on dialysis.
  4. Custom input

Select scenario (1-4): 1
```

### Step 2: Compare Console Output
```
🏭 PRODUCTION AGENT
📝 Input: I need all patients with type 2 diabetes diagnosed in 2024.
⏳ Processing...
✅ Completed in 3.12s

🧪 EXPERIMENTAL AGENT (LangChain)
📝 Input: I need all patients with type 2 diabetes diagnosed in 2024.
⏳ Processing...
✅ Completed in 4.10s

📈 COMPARISON
Timing:
  Production:   3.12s
  Experimental: 4.10s
  Ratio:        1.31x

Outputs Match: True
```

### Step 3: Compare LangSmith Traces
1. Go to LangSmith dashboard
2. Filter by timestamp (shown in console output)
3. Open both traces side-by-side

**Comparison Checklist**:

| Feature | Production | Experimental | Notes |
|---------|-----------|--------------|-------|
| **Trace Depth** | 1-2 levels | 5+ levels | Full method tree |
| **LLM Calls** | ✅ Visible | ✅ Visible | Same prompts |
| **Method Breakdown** | ❌ Missing | ✅ Visible | e.g., `_validate_extracted_requirements()` |
| **Database Calls** | ❌ Missing | ✅ Visible | e.g., `save_to_database()` |
| **State Management** | ❌ Missing | ✅ Visible | e.g., `_update_conversation_state()` |
| **Error Handling** | ❌ Missing | ✅ Visible | Retry logic, escalation |
| **Performance** | Faster (3.12s) | Slower (4.10s) | +31% overhead |
| **Input/Output** | ✅ Visible | ✅ Visible | Same structure |

---

## Test 5: Error Scenario Testing

### Step 1: Trigger Validation Error
In Research Notebook, submit: "Give me all the data."

**Expected Behavior**:
- Agent detects incomplete requirements
- Asks clarifying questions
- Does NOT proceed to feasibility

**LangSmith Trace (Experimental)**:
```
gather_requirements
├─ extract_requirements
│  └─ LLM Call (detects missing criteria)
├─ validate_completeness ← Should fail here
│  └─ ValidationError: "Missing inclusion criteria"
└─ generate_clarifying_question
   └─ LLM Call (asks for specifics)
```

### Step 2: Trigger LLM API Error
**Simulate**: Temporarily set invalid API key (DON'T DO THIS IN PROD)
```bash
# For testing only - use in local .env
ANTHROPIC_API_KEY=invalid-key-test
```

**Expected Behavior**:
- Agent catches API error
- Retries with exponential backoff (3 attempts)
- Falls back to human escalation

**LangSmith Trace (Experimental)**:
```
gather_requirements
├─ extract_requirements (FAILED)
│  ├─ LLM Call Attempt 1 ← API Error
│  ├─ LLM Call Attempt 2 ← API Error (2s delay)
│  └─ LLM Call Attempt 3 ← API Error (4s delay)
├─ escalate_to_human
│  └─ create_escalation_record
└─ return error state
```

**Note**: Production traces WON'T show retry logic - only experimental will.

---

## Test 6: Performance Benchmarking

### Run 10 Identical Queries and Compare

**Test Script**:
```bash
# Use manual_test.py in loop
for i in {1..10}; do
  echo "Run $i:"
  PYTHONPATH=/Users/jagnyesh/Development/FHIR_PROJECT python manual_test.py <<< "1"
  sleep 5
done
```

### Measure from LangSmith

1. Go to LangSmith dashboard
2. Filter last 10 minutes
3. Group by agent type (production vs experimental)
4. Export timing data

**Expected Results** (from Phase 2):
| Metric | Production | Experimental | Ratio |
|--------|-----------|--------------|-------|
| Mean | 3.12s | 4.10s | 1.31x |
| Median | 3.03s | 3.82s | 1.26x |
| P95 | 3.62s | 5.11s | 1.41x |
| P99 | 5.00s | 6.32s | 1.26x |

---

## Test 7: Verify Database Persistence

### Step 1: Submit Request via Portal
Use Test 3 instructions to submit a full request.

### Step 2: Check Database
```bash
# Connect to database
PGPASSWORD=researchflow psql -h localhost -p 5434 -U researchflow -d researchflow

# Query research requests
SELECT request_id, status, created_at
FROM research_requests
ORDER BY created_at DESC
LIMIT 5;

# Query requirements data
SELECT request_id, requirements_json
FROM requirements_data
WHERE request_id = 'REQ-2024-001';  -- Use actual request_id

# Query agent executions
SELECT agent_name, task_name, status, execution_time_ms
FROM agent_executions
WHERE request_id = 'REQ-2024-001'
ORDER BY started_at;
```

### Step 3: Verify in LangSmith
**Experimental agents should show**:
```
gather_requirements
├─ extract_requirements
├─ validate_completeness
└─ save_to_database ← Look for this
   └─ Database: INSERT INTO requirements_data
```

**Production agents**:
- Database writes happen but NOT visible in traces

---

## Success Criteria

### ✅ Research Notebook Working If:
1. Chat interface responds to queries (< 5s)
2. Agent extracts requirements correctly
3. Conversation history persists across turns
4. LangSmith traces appear for each interaction

### ✅ Researcher Portal Working If:
1. Form submission creates new request
2. Request ID generated (e.g., REQ-2024-001)
3. Status progresses through workflow states
4. All agents execute in sequence
5. LangSmith traces show full workflow

### ✅ LangSmith Tracing Working If:
1. Traces appear within 5 seconds of execution
2. Production traces show LLM calls only
3. Experimental traces show full method tree
4. All input/output parameters captured
5. Performance metrics accurate (matches console output)

### ✅ Experimental Agents Production-Ready If:
1. Success rate = 100% (all test queries succeed)
2. Performance overhead ≤ 1.30x production (currently 1.31x - acceptable)
3. Output matches production exactly
4. No errors or warnings in console
5. Database persistence working
6. Full workflow visible in LangSmith

---

## Troubleshooting

### Issue: No LangSmith Traces Appearing

**Check**:
```bash
# Verify environment
env | grep LANGCHAIN

# Should see:
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_pt_...
LANGCHAIN_PROJECT=researchflow-production
```

**Fix**:
```bash
# Add to .env if missing
echo "LANGCHAIN_TRACING_V2=true" >> .env
echo "LANGCHAIN_API_KEY=lsv2_pt_your-langsmith-api-key-here" >> .env
echo "LANGCHAIN_PROJECT=researchflow-production" >> .env

# Restart UIs
pkill -f streamlit
streamlit run app/web_ui/research_notebook.py --server.port 8501 &
streamlit run app/web_ui/researcher_portal.py --server.port 8502 &
```

### Issue: UI Not Loading (Port Already in Use)

**Check**:
```bash
lsof -ti:8501,8502,8503
```

**Fix**:
```bash
# Kill existing processes
pkill -f streamlit

# Restart
streamlit run app/web_ui/research_notebook.py --server.port 8501 &
streamlit run app/web_ui/researcher_portal.py --server.port 8502 &
streamlit run app/web_ui/admin_dashboard.py --server.port 8503 &
```

### Issue: Experimental Agents Not Being Used

**Check which agent is active**:
```python
# In app/web_ui/research_notebook.py or researcher_portal.py
# Look for imports:

# If you see this - PRODUCTION agent:
from app.agents.requirements_agent import RequirementsAgent

# If you see this - EXPERIMENTAL agent:
from app.langchain_orchestrator.langchain_agents import LangChainRequirementsAgent
```

**To switch to experimental**:
1. Edit the UI file
2. Change import and instantiation
3. Restart Streamlit

### Issue: Database Connection Failed

**Check**:
```bash
# Verify PostgreSQL running
docker ps | grep postgres

# Test connection
PGPASSWORD=researchflow psql -h localhost -p 5434 -U researchflow -d researchflow -c "SELECT 1"
```

**Fix**:
```bash
# Restart database
docker-compose -f config/docker-compose.yml restart postgres
```

---

## Expected Timeline

- **Test 1** (Simple query): 5 minutes
- **Test 2** (Multi-turn): 10 minutes
- **Test 3** (Full workflow): 15 minutes
- **Test 4** (Side-by-side): 10 minutes
- **Test 5** (Error scenarios): 10 minutes
- **Test 6** (Performance): 15 minutes
- **Test 7** (Database): 5 minutes

**Total**: ~70 minutes for comprehensive E2E testing

---

## Next Steps After Testing

### If All Tests Pass ✅

1. **Document Results**
   - Screenshot LangSmith traces (production vs experimental)
   - Record performance metrics
   - Update SPRINT_06_6 with E2E validation section

2. **Proceed to Phase 3: Shadow Mode**
   - Deploy experimental agents alongside production
   - Route 10% of traffic to experimental
   - Monitor for 2 weeks

3. **Create Phase 3 Test Plan**
   - Define shadow mode success criteria
   - Set up alerting for errors
   - Plan gradual rollout schedule

### If Tests Fail ❌

1. **Document Failures**
   - Which test failed?
   - Error messages from console
   - LangSmith trace URLs
   - Database query results

2. **Categorize Issues**
   - UI integration issue?
   - Agent logic issue?
   - Database persistence issue?
   - LangSmith tracing issue?

3. **Create Fix Tasks**
   - File GitHub issues
   - Update sprint backlog
   - Prioritize blockers

---

**Ready to Start Testing!**

Begin with Test 1 (Research Notebook simple query) and work your way through the guide. Good luck!
