# LangSmith Debugging Guide for ResearchFlow Workflows

## Overview

LangSmith provides distributed tracing for LangChain/LangGraph workflows, making it easy to debug where requests get blocked, see execution times, and inspect context at each step.

## Setup

### 1. Enable LangSmith Tracing

Add to your `.env` file:
```bash
# LangSmith Observability
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_pt_REDACTED
LANGCHAIN_PROJECT=researchflow-production
LANGCHAIN_ENDPOINT=https://api.smith.langchain.com
```

### 2. Restart Services

After adding environment variables:
```bash
# Stop all Streamlit apps
pkill -f "streamlit run"

# Restart with environment variables
LANGCHAIN_TRACING_V2=true \
HAPI_DB_URL=postgresql://hapi:hapi@localhost:5433/hapi \
streamlit run app/web_ui/admin_dashboard.py --server.port 8502 &

LANGCHAIN_TRACING_V2=true \
HAPI_DB_URL=postgresql://hapi:hapi@localhost:5433/hapi \
streamlit run app/web_ui/researcher_portal.py --server.port 8501 &
```

## Using LangSmith to Debug Workflow Blockages

### Scenario: Request Stuck in "Human Review"

#### Step 1: Find the Request Trace

1. Go to https://smith.langchain.com/
2. Click "Projects" → "researchflow-production"
3. Search for your request ID (e.g., `REQ-20251104-16A5E0CF`)
4. Click on the trace to see the full execution tree

#### Step 2: Analyze the Trace Tree

LangSmith shows a hierarchical tree of all operations:
```
📊 Research Request Workflow
├── ✅ requirements_agent.gather_requirements (2.3s)
├── ✅ phenotype_agent.validate_feasibility (1.5s)
├── ⏸️  SQL Approval (PAUSED - waiting for human)
├── ✅ extraction_agent.extract_preview (0.8s)
└── ❌ qa_agent.validate_preview (FAILED - 'NoneType' error)
```

#### Step 3: Inspect Failed Steps

Click on the failed step to see:
- **Inputs**: What context was passed to the agent
- **Outputs**: What the agent returned (or error)
- **Errors**: Full stack trace
- **Metadata**: Execution time, model used, tokens consumed

**Example - Finding Field Mismatch**:
```json
{
  "inputs": {
    "request_id": "REQ-20251104-16A5E0CF",
    "sql_query": "SELECT DISTINCT...",          // ← Orchestrator passes this
    "structured_requirements": {...},           // ← Orchestrator passes this
    "parameters": {"gender_1": "male", ...}
  },
  "error": "'NoneType' object has no attribute 'get'",
  "code": {
    "line_134": "requirements = context.get('requirements')",  // ← Agent expects this (doesn't exist!)
    "line_135": "preview_package = context.get('preview_package')"
  }
}
```

#### Step 4: Compare Inputs vs. Expected Fields

Create a table:
| Field | Orchestrator Sends | Agent Expects | Match? |
|-------|-------------------|---------------|--------|
| SQL Query | `sql_query` | `phenotype_sql` | ❌ MISMATCH |
| Requirements | `structured_requirements` | `requirements` | ❌ MISMATCH |
| Parameters | `parameters` | N/A (not used) | ❌ MISSING |

#### Step 5: Track Approval Flow

LangSmith shows approval gates:
```
1. Agent requests approval → PAUSED
2. Human approves → approval_data stored
3. Orchestrator builds context from approval_data
4. Next agent receives context → Check if fields match!
```

### Scenario: SQL Query Returns 0 Results

#### Step 1: Find SQL Execution in Trace

Look for `sql_adapter.execute_sql` in the trace tree:
```
📊 extraction_agent.extract_preview
├── _execute_phenotype_query
│   └── sql_adapter.execute_sql(sql, parameters)  // ← Click here
└── _extract_data_element_preview (x4 elements)
```

#### Step 2: Inspect SQL Execution

Click on `sql_adapter.execute_sql` to see:
```json
{
  "inputs": {
    "sql": "SELECT DISTINCT p.patient_id... WHERE p.gender = :gender_1",
    "parameters": {"gender_1": "male", "condition_2": "%diabetes%"}  // ← Check if passed!
  },
  "outputs": {
    "result": [],  // ← 0 rows returned
    "row_count": 0
  },
  "duration_ms": 45
}
```

#### Step 3: Debug SQL Manually

Test the exact SQL from the trace:
```bash
# Copy SQL and parameters from LangSmith trace
PGPASSWORD=hapi psql -h localhost -p 5433 -U hapi -d hapi -c "
SELECT DISTINCT p.patient_id
FROM sqlonfhir.patient_demographics p
WHERE p.gender = 'male'  -- Manually substitute :gender_1
  AND EXISTS (
    SELECT 1 FROM sqlonfhir.condition_simple c
    WHERE c.patient_id = p.patient_id
    AND LOWER(c.code_text) LIKE LOWER('%diabetes%')
  );
"
```

#### Step 4: Check for Common SQL Issues

1. **Materialized views don't exist**:
   ```sql
   SELECT schemaname, matviewname
   FROM pg_matviews
   WHERE schemaname = 'sqlonfhir';
   ```

2. **Wrong database** (researchflow vs. hapi):
   ```bash
   # Check which DB the agent is connecting to
   echo $HAPI_DB_URL  # Should be hapi DB, not researchflow
   ```

3. **Parameters not bound**:
   ```python
   # In LangSmith trace, check if parameters is None or {}
   "parameters": null  # ❌ Not passed!
   "parameters": {"gender_1": "male"}  # ✅ Correct
   ```

## Common Workflow Blockage Patterns

### Pattern 1: Context Field Mismatch

**Symptom**: Agent fails with `'NoneType' object has no attribute 'get'`

**LangSmith Diagnosis**:
1. Go to failed agent step
2. Click "Inputs" tab
3. Compare field names with agent code
4. Look for `context.get("field_that_doesnt_exist")`

**Fix**: Update agent to use correct field names or add fallbacks

### Pattern 2: Missing SQL Parameters

**Symptom**: SQL query returns 0 rows or "bind parameter required" error

**LangSmith Diagnosis**:
1. Find `sql_adapter.execute_sql` in trace
2. Check if `parameters` is in inputs
3. If `parameters: null`, parameters weren't passed

**Fix**: Update `_execute_phenotype_query()` to accept and pass parameters

### Pattern 3: Wrong Database Connection

**Symptom**: Query runs but returns 0 rows (even though data exists)

**LangSmith Diagnosis**:
1. Check `sql_adapter` initialization in trace metadata
2. Look for `database_url` in agent constructor
3. Verify it points to HAPI DB (not researchflow DB)

**Fix**: Ensure `HAPI_DB_URL` is set and used for phenotype queries

### Pattern 4: Approval Data Not Propagating

**Symptom**: Agent fails because required context is missing

**LangSmith Diagnosis**:
1. Find approval creation step
2. Check `approval_data` contents
3. Find orchestrator `_continue_workflow_after_approval`
4. Verify `context.update(approval.approval_data)` happened
5. Check if next agent received the fields

**Fix**: Ensure orchestrator merges approval_data into context

## Advanced LangSmith Features

### 1. Custom Metadata Tagging

Add tags to trace requests for easier filtering:
```python
from langsmith import traceable

@traceable(
    run_type="tool",
    tags=["preview-extraction", "sql-query"],
    metadata={"request_id": request_id, "cohort_size": len(cohort)}
)
async def extract_preview(context):
    ...
```

### 2. Comparison View

Compare two requests side-by-side:
1. Select 2 traces (working vs. broken)
2. Click "Compare"
3. See diff of inputs, outputs, execution paths

### 3. Performance Analysis

Identify bottlenecks:
1. Sort traces by duration
2. Look for steps taking > 5 seconds
3. Check if LLM calls are slow (token counts)
4. Optimize expensive operations

### 4. Error Rate Monitoring

Track failure patterns:
1. Go to "Analytics" tab
2. Filter by error type
3. See which agents fail most often
4. Identify systemic issues

## Integration with ResearchFlow

### Automatic Request Tagging

All ResearchFlow traces include:
- `request_id`: Unique identifier
- `agent_id`: Which agent executed
- `task`: Task name (e.g., "extract_preview")
- `workflow_state`: Current state (e.g., "preview_extraction")

### Search by Request ID

```
# In LangSmith search bar
metadata.request_id = "REQ-20251104-16A5E0CF"
```

### Filter by Agent

```
# Show all extraction agent traces
tags:"extraction_agent"
```

### Filter by Errors

```
# Show only failed requests
error:*
```

## Example: Debugging Our Stuck Request

### Step-by-Step Using LangSmith

1. **Search for Request**:
   ```
   REQ-20251104-16A5E0CF
   ```

2. **See Execution Timeline**:
   ```
   00:00 ✅ requirements_agent (2.3s)
   00:02 ✅ phenotype_agent (1.5s)
   00:04 ⏸️ SQL Approval (WAITING)
   00:10 ✅ SQL Approved
   00:10 ✅ extraction_agent.extract_preview (0.8s)
   00:11 ❌ qa_agent.validate_preview (FAILED)
   ```

3. **Click Failed QA Agent**:
   ```json
   {
     "error": "'NoneType' object has no attribute 'get'",
     "error_location": "qa_agent.py:134",
     "code": "requirements = context.get('requirements')",
     "inputs": {
       "structured_requirements": {...},  // ← Present!
       "requirements": null                // ← Missing!
     }
   }
   ```

4. **Root Cause Identified**:
   - QA agent expects `requirements`
   - Orchestrator sends `structured_requirements`
   - Field name mismatch!

5. **Fix Applied**:
   ```python
   # qa_agent.py:134 (BEFORE)
   requirements = context.get("requirements")  # ❌ Doesn't exist

   # qa_agent.py:137 (AFTER)
   requirements = context.get("structured_requirements") or context.get("requirements")  # ✅ Fallback
   ```

6. **Verify Fix in Next Trace**:
   - Submit new request
   - Check LangSmith trace
   - QA agent should succeed with `structured_requirements`

## Troubleshooting LangSmith Issues

### LangSmith Not Showing Traces

**Check Environment Variables**:
```bash
# In Python script or Streamlit app
import os
print("Tracing enabled:", os.getenv("LANGCHAIN_TRACING_V2"))
print("API key set:", bool(os.getenv("LANGCHAIN_API_KEY")))
```

**Restart Services**:
```bash
# Environment variables must be set BEFORE starting app
export LANGCHAIN_TRACING_V2=true
export LANGCHAIN_API_KEY=lsv2_pt_...
streamlit run app/web_ui/admin_dashboard.py --server.port 8502
```

### Traces Missing Steps

**Ensure All Agents Use LangChain**:
- Only LangChain/LangGraph operations are traced
- Custom code outside LangChain won't appear
- Add `@traceable` decorator to custom functions

### Sensitive Data in Traces

**Filter Sensitive Fields**:
```python
from langsmith import traceable

@traceable(
    run_type="tool",
    filter=lambda x: {k: v for k, v in x.items() if k not in ["ssn", "dob"]}
)
async def extract_data(context):
    ...
```

## Summary

LangSmith provides:
1. ✅ **Execution Timeline**: See exactly where requests pause/fail
2. ✅ **Input/Output Inspection**: Compare what was sent vs. expected
3. ✅ **Error Stack Traces**: Full context for debugging
4. ✅ **Performance Metrics**: Identify bottlenecks
5. ✅ **Comparison Tools**: Side-by-side analysis of working vs. broken requests

**For ResearchFlow workflow debugging**:
- Search by `request_id`
- Inspect failed agent steps
- Check context field names in inputs
- Verify SQL parameters are passed
- Compare database connections (HAPI vs. researchflow)

**Next Steps**:
1. Enable LangSmith tracing in `.env`
2. Restart Streamlit apps
3. Submit test request
4. Monitor in LangSmith dashboard
5. Debug field mismatches visually
