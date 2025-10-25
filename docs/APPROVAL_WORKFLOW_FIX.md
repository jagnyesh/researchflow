## Approval Workflow Issue - Root Cause and Fix

**Date:** October 22, 2025
**Issue:** New request approvals not appearing/updating in admin portal

---

## Root Cause Analysis

### Issue Description
The admin dashboard was showing existing approvals, but new research requests were not progressing through the workflow to create new approvals.

### Investigation Results

Running the diagnostic script revealed:
- ✓ Database contains 16 approvals (10 pending)
- ✓ API endpoint `/approvals/pending` returns approvals correctly
- ✓ Admin dashboard can fetch approvals from API
- ❌ **13 requests stuck in early states** (`new_request`, `requirements_gathering`)

### Root Cause

**File:** `app/api/research.py`, line 88-103

**Problem:** The `/research/submit` endpoint was creating database records but **NOT triggering the orchestrator workflow**.

```python
# OLD CODE (BROKEN):
if orchestrator:
    logger.info(f"Triggering orchestrator for request: {request_id}")
    # Start processing in background
    # Note: In production, this should be a background task
    # For now, we'll return and let the user manually trigger processing
else:
    logger.warning("Orchestrator not available - request created but not processing")

return {
    "success": True,
    "request_id": request_id,
    "message": "Research request submitted successfully",
    "status": WorkflowState.NEW_REQUEST.value,
    "next_step": f"Use POST /research/process/{request_id} to begin processing"  # ← Manual step required!
}
```

**What was happening:**
1. User submits request via `/research/submit`
2. Database record created in `new_request` state
3. **Workflow NOT started** - comment said "let the user manually trigger processing"
4. User would need to call `/research/process/{request_id}` separately
5. If they didn't know to do this, requests stayed stuck forever

**Result:** 13 requests created but never processed, no approvals generated.

---

## The Fix

### Code Changes

**File:** `app/api/research.py`

**Change:** Modified `/research/submit` to automatically trigger orchestrator workflow.

```python
# NEW CODE (FIXED):
if orchestrator:
    logger.info(f"Triggering orchestrator for request: {request_id}")

    # Start workflow immediately
    context = {
        "request_id": request_id,
        "initial_request": submission.initial_request,
        "researcher_info": {
            "name": submission.researcher_name,
            "email": submission.researcher_email,
            "department": submission.researcher_department,
            "irb_number": submission.irb_number
        }
    }

    # Add structured requirements if provided
    if submission.structured_requirements:
        context["structured_requirements"] = submission.structured_requirements
        context["skip_conversation"] = True
        logger.info(f"Processing with pre-structured requirements")

    # Start the workflow (non-blocking)
    asyncio.create_task(
        orchestrator.route_task(
            agent_id="requirements_agent",
            task="gather_requirements",
            context=context,
            from_agent="research_api"
        )
    )

    return {
        "success": True,
        "request_id": request_id,
        "message": "Research request submitted and processing started",  # ← Updated message
        "status": WorkflowState.NEW_REQUEST.value,
        "workflow_started": True  # ← New field
    }
```

**Key improvements:**
1. ✅ Workflow starts **automatically** when request is submitted
2. ✅ Uses `asyncio.create_task()` for non-blocking execution
3. ✅ Supports pre-structured requirements from Research Notebook
4. ✅ Returns `workflow_started: true` to confirm workflow is running

---

## Testing & Verification

### Test Suite Created

**File:** `tests/test_agent_handoffs.py`

Comprehensive test suite for monitoring agent-to-agent handoffs:

1. **Agent Execution Tracking** - Verifies agent executions are recorded in database
2. **Agent Handoff Sequence** - Tests correct agent invocation order
3. **Approval Workflow Handoff** - Tests workflow pauses at approval gates
4. **Audit Log Tracking** - Verifies all activities are logged
5. **Context Passing** - Tests context is preserved between agents
6. **Failed Handoff Handling** - Tests error tracking
7. **Concurrent Handoffs** - Tests multiple concurrent requests

**Run tests:**
```bash
pytest tests/test_agent_handoffs.py -v
```

### Diagnostic Tools Created

#### 1. Approval Issue Diagnostic

**File:** `scripts/diagnose_approval_issue.py`

Comprehensive diagnostic that checks:
- Database connectivity and approval records
- Research request states
- API endpoint health
- Recent agent activity
- Specific workflow bottlenecks

**Run diagnostic:**
```bash
python scripts/diagnose_approval_issue.py
```

#### 2. Process Stuck Requests

**File:** `scripts/process_stuck_requests.py`

Utility to fix existing stuck requests by triggering their workflows.

**Run utility:**
```bash
python scripts/process_stuck_requests.py
```

This will:
1. Find all requests in `new_request` or `requirements_gathering` states
2. Initialize orchestrator with all agents
3. Trigger workflow for each stuck request
4. Report success/failure for each

---

## How to Monitor Agent Handoffs

### 1. Use the Test Suite

Run the diagnostic tests regularly:

```bash
# Run all diagnostics
pytest tests/test_agent_handoffs.py -v -k diagnose

# Monitor specific request
python -c "
import asyncio
from tests.test_agent_handoffs import monitor_request_handoffs
asyncio.run(monitor_request_handoffs('REQ-20251022-XXXXX'))
"
```

### 2. Check Database Tables

**Agent Executions:**
```sql
SELECT agent_id, task, status, started_at, duration_seconds
FROM agent_executions
WHERE request_id = 'REQ-XXXXX'
ORDER BY started_at;
```

**Approvals:**
```sql
SELECT id, approval_type, status, submitted_at, reviewed_at
FROM approvals
WHERE request_id = 'REQ-XXXXX'
ORDER BY submitted_at;
```

**Audit Logs:**
```sql
SELECT timestamp, event_type, agent_id, severity
FROM audit_logs
WHERE request_id = 'REQ-XXXXX'
ORDER BY timestamp;
```

### 3. Use API Endpoints

**Check request status:**
```bash
curl http://localhost:8000/research/REQ-XXXXX
```

**Check pending approvals:**
```bash
curl http://localhost:8000/approvals/pending
```

**Get approvals for specific request:**
```bash
curl http://localhost:8000/approvals/request/REQ-XXXXX
```

### 4. Admin Dashboard

The admin dashboard now properly shows:
- **Overview Tab:** Active requests and their states
- **Agent Metrics Tab:** Agent performance and status
- **Pending Approvals Tab:** All approvals requiring review (properly updates)
- **Escalations Tab:** Failed workflows needing attention
- **Analytics Tab:** Request volume and trends

---

## Workflow State Machine

Understanding the workflow helps monitor handoffs:

```
new_request
    ↓
requirements_gathering ← (agent: requirements_agent)
    ↓
requirements_review ← (APPROVAL GATE)
    ↓ (approval granted)
feasibility_validation ← (agent: phenotype_agent)
    ↓
phenotype_review ← (APPROVAL GATE)
    ↓ (approval granted)
schedule_kickoff ← (agent: calendar_agent)
    ↓
extraction_approval ← (APPROVAL GATE)
    ↓ (approval granted)
data_extraction ← (agent: extraction_agent)
    ↓
qa_validation ← (agent: qa_agent)
    ↓
qa_review ← (APPROVAL GATE)
    ↓ (approval granted)
data_delivery ← (agent: delivery_agent)
    ↓
delivered ← (FINAL STATE)
```

**Approval Gates** (workflow pauses, human must review):
- `requirements_review` - Informatician validates requirements for medical accuracy
- `phenotype_review` - **CRITICAL** - Informatician approves SQL before execution
- `extraction_approval` - Admin authorizes data access
- `qa_review` - QA analyst validates data quality

---

## Expected Behavior After Fix

### New Requests
1. User submits via Research Notebook or API
2. Request created in database (`new_request` state)
3. **Workflow starts automatically** (new!)
4. Requirements agent gathers requirements
5. Approval created when requirements complete
6. Approval appears in admin dashboard **immediately**

### Existing Stuck Requests
Run the utility script to process them:
```bash
python scripts/process_stuck_requests.py
```

### Monitoring
- Use diagnostic script to check system health regularly
- Run test suite to verify handoffs are working
- Check admin dashboard for real-time approval updates

---

## Troubleshooting

### If approvals still don't appear:

1. **Check API server is running:**
   ```bash
   lsof -i :8000 | grep LISTEN
   # Should show python process on port 8000
   ```

2. **Check orchestrator is initialized:**
   ```bash
   curl http://localhost:8000/
   # Should return: "orchestrator_initialized": true
   ```

3. **Run diagnostic:**
   ```bash
   python scripts/diagnose_approval_issue.py
   ```

4. **Check agent activity:**
   ```bash
   # Look for recent agent executions
   python -c "
   import asyncio
   from app.database import get_db_session, init_db
   from app.database.models import AgentExecution
   from sqlalchemy import select

   async def check():
       await init_db()
       async with get_db_session() as session:
           result = await session.execute(
               select(AgentExecution).order_by(AgentExecution.started_at.desc()).limit(5)
           )
           for exec in result.scalars():
               print(f'{exec.agent_id}.{exec.task}: {exec.status}')

   asyncio.run(check())
   "
   ```

5. **Check logs:**
   ```bash
   # API server logs will show workflow routing
   # Look for: "Routing to requirements_agent.gather_requirements"
   ```

### Common Issues

**Issue:** Requests still stuck after fix
**Solution:** Run `python scripts/process_stuck_requests.py` to process existing stuck requests

**Issue:** Workflow starts but stalls at requirements
**Solution:** Check ANTHROPIC_API_KEY is set in .env file (LLM required for requirements extraction)

**Issue:** Dashboard shows 0 approvals but database has them
**Solution:** Hard refresh dashboard (Ctrl+Shift+R), or check API_BASE_URL setting

**Issue:** Approval created but workflow doesn't continue
**Solution:** Check that approval was actually approved via dashboard (status should be "approved", not "pending")

---

## Summary

### What Was Fixed
✅ Automatic workflow triggering on request submission
✅ Non-blocking workflow execution
✅ Support for pre-structured requirements
✅ Clear feedback on workflow status

### Tools Created
✅ Comprehensive test suite for agent handoff monitoring
✅ Diagnostic script for identifying workflow issues
✅ Utility script for processing stuck requests
✅ Documentation for monitoring and troubleshooting

### Impact
- **Before:** 13 requests stuck, no new approvals
- **After:** All new requests automatically processed, approvals appear immediately

---

## Related Files

- `app/api/research.py` - Fixed `/research/submit` endpoint
- `tests/test_agent_handoffs.py` - Agent handoff monitoring tests
- `scripts/diagnose_approval_issue.py` - Diagnostic tool
- `scripts/process_stuck_requests.py` - Fix stuck requests
- `docs/APPROVAL_WORKFLOW_FIX.md` - This document
