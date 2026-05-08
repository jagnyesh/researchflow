# Approval Workflow - Requests Disappearing Bug Fix

## Problem Statement

After clicking "Approve" on a request in the Admin Dashboard, **the request disappeared from the sidebar** and could not be found, even though it was still in the database with `current_state = 'human_review'`.

## Root Cause

**Location**: `app/orchestrator/orchestrator.py:638`

**Issue**: The `_handle_workflow_error()` method incorrectly called `_complete_workflow()` when errors occurred, marking requests as "complete" even though they were in `HUMAN_REVIEW` state (a paused/waiting state, not a terminal state).

```python
async def _handle_workflow_error(self, request_id: str, agent_id: str, error: str):
    """Handle workflow execution errors"""
    # ... updates state to HUMAN_REVIEW ...

    await self._complete_workflow(request_id, WorkflowState.HUMAN_REVIEW)  # ❌ BUG!
```

### Why This Caused Requests to Disappear

1. When `_complete_workflow()` is called, it sets `research_request.completed_at = datetime.now()`
2. The `get_all_active_requests()` method filters by `WHERE completed_at IS NULL`
3. Requests with `completed_at` set are considered "complete" and excluded from active requests
4. Admin dashboard sidebar uses `get_all_active_requests()` to display requests
5. **Result**: Requests in `HUMAN_REVIEW` disappeared from the sidebar after approval

### Affected States

This bug affected **9 requests** in the database that were marked as complete but still in non-terminal states:
- `human_review`: 8 requests
- `new_request`: 1 request

## Fix Applied

### 1. Code Fix (`orchestrator.py:638`)

**Before (BROKEN)**:
```python
async def _handle_workflow_error(self, request_id: str, agent_id: str, error: str):
    """Handle workflow execution errors"""
    logger.error(f"[{request_id}] Workflow error in {agent_id}: {error}")

    async with get_db_session() as session:
        # ... update state to HUMAN_REVIEW ...
        await session.commit()

    await self._complete_workflow(request_id, WorkflowState.HUMAN_REVIEW)  # ❌ WRONG!
```

**After (FIXED)**:
```python
async def _handle_workflow_error(self, request_id: str, agent_id: str, error: str):
    """Handle workflow execution errors"""
    logger.error(f"[{request_id}] Workflow error in {agent_id}: {error}")

    async with get_db_session() as session:
        # ... update state to HUMAN_REVIEW ...
        await session.commit()

    # NOTE: Do NOT call _complete_workflow() here!
    # HUMAN_REVIEW is a paused state waiting for human intervention, not a terminal state.
    # Setting completed_at would cause the request to disappear from get_all_active_requests().
```

**Rationale**: `HUMAN_REVIEW` is a **paused state** where the workflow is waiting for human intervention, **not a terminal state**. Only terminal states (`COMPLETE`, `DELIVERED`, `FAILED`) should have `completed_at` set.

### 2. Database Fix

Fixed 9 existing requests that had `completed_at` incorrectly set:

```sql
-- Fix all requests with completed_at set but in non-terminal states
UPDATE research_requests
SET completed_at = NULL
WHERE completed_at IS NOT NULL
  AND current_state NOT IN ('complete', 'delivered', 'failed');

-- Result: Updated 9 requests
```

**Affected Request IDs**:
- REQ-20251104-A5621BCF (user's reported request)
- REQ-20251104-2C8F24F2
- REQ-20251104-C628E737
- REQ-20251104-228D4C7C
- REQ-20251030-AC26823F
- REQ-20251030-DD184196
- REQ-20251030-92C8265E
- REQ-20251030-CB1A9097
- REQ-20251030-3C9FD115

### 3. Admin Dashboard Status Filter Enhancement

**Location**: `app/web_ui/admin_dashboard.py:191-213`

**Issue**: Status filter only had a limited subset of workflow states, making it impossible to filter by states like `human_review`, `phenotype_review`, etc.

**Fix**: Added all 17 workflow states to the filter dropdown:

```python
# Status filter (all possible workflow states)
all_statuses = [
    "new_request",
    "requirements_gathering",
    "requirements_complete",
    "requirements_review",
    "feasibility_validation",
    "phenotype_review",
    "human_review",           # ✅ Now available for filtering
    "preview_extraction",
    "preview_qa",
    "schedule_kickoff",
    "data_extraction",
    "qa_validation",
    "delivery_review",
    "data_delivery",
    "delivered",
    "complete",
    "failed",
]
```

## Test Results

### Before Fix

**Database State**:
```sql
SELECT id, current_state, completed_at
FROM research_requests
WHERE id = 'REQ-20251104-A5621BCF';

          id           | current_state |        completed_at
-----------------------+---------------+----------------------------
 REQ-20251104-A5621BCF | human_review  | 2025-11-04 22:14:08.503904  ❌
```

**Admin Dashboard**:
- Showing: "Showing 36 of 45 requests" (9 requests missing)
- Search for A5621BCF: No results ❌
- Status: Request disappeared after approval

### After Fix

**Database State**:
```sql
SELECT id, current_state, completed_at
FROM research_requests
WHERE id = 'REQ-20251104-A5621BCF';

          id           | current_state | completed_at
-----------------------+---------------+--------------
 REQ-20251104-A5621BCF | human_review  |              ✅ NULL
```

**Admin Dashboard**:
- Showing: "Showing 45 of 45 requests" ✅ (all requests visible)
- Search for A5621BCF: "Showing 1 of 45 requests" ✅ (found!)
- Status: Request remains visible in sidebar after approval

## Files Modified

1. **`app/orchestrator/orchestrator.py`** (line 638)
   - Removed incorrect `_complete_workflow()` call from `_handle_workflow_error()`
   - Added explanatory comment about why NOT to set completed_at

2. **`app/web_ui/admin_dashboard.py`** (lines 191-213)
   - Expanded status filter from 7 states to all 17 workflow states
   - Added comprehensive status filtering capability

3. **Database** (via SQL migration)
   - Set `completed_at = NULL` for 9 requests in non-terminal states

## Workflow State Classification

### Terminal States (should have `completed_at`)
- `COMPLETE` - Workflow successfully finished
- `DELIVERED` - Data delivered to researcher
- `FAILED` - Workflow failed permanently

### Paused States (should NOT have `completed_at`)
- `REQUIREMENTS_REVIEW` - Waiting for informatician to approve requirements
- `PHENOTYPE_REVIEW` - Waiting for SQL approval
- `HUMAN_REVIEW` - Workflow error, waiting for manual intervention
- `PREVIEW_QA` - Waiting for preview data approval
- `DELIVERY_REVIEW` - Waiting for full dataset approval

### Active States (should NOT have `completed_at`)
- All other states (agents actively working)

## Validation

### Database Query to Check for Future Bugs
```sql
-- Find requests with completed_at but in non-terminal states
SELECT
    id,
    current_state,
    completed_at
FROM research_requests
WHERE completed_at IS NOT NULL
  AND current_state NOT IN ('complete', 'delivered', 'failed')
ORDER BY created_at DESC;

-- Expected Result: 0 rows ✅
```

### Admin Dashboard Checks
1. ✅ All 45 requests visible in sidebar
2. ✅ Search functionality works correctly
3. ✅ Status filter includes all workflow states
4. ✅ Requests in `HUMAN_REVIEW` state remain visible after approval

## Prevention

**Code Review Checklist**:
- [ ] Only call `_complete_workflow()` for terminal states
- [ ] Never set `completed_at` for paused/waiting states
- [ ] Verify `get_all_active_requests()` filters correctly by `completed_at IS NULL`
- [ ] Test that requests remain visible in UI after state transitions

**Testing Checklist**:
- [ ] Submit test request and approve at each stage
- [ ] Verify request remains in sidebar after each approval
- [ ] Check database that `completed_at` is NULL for non-terminal states
- [ ] Trigger workflow error and verify request stays visible

## Related Issues

This fix also resolves:
- Requests appearing as "completed" in metrics when still in progress
- Inability to filter by `human_review` state in admin dashboard
- Missing requests in researcher portal (uses similar `get_all_active_requests()` logic)

## Summary

**Root Cause**: `_complete_workflow()` incorrectly called for `HUMAN_REVIEW` state
**Impact**: 9 requests disappeared from admin dashboard after approval
**Fix**: Removed incorrect call + added comment + fixed database + enhanced status filter
**Result**: ✅ All requests now remain visible throughout their lifecycle

**The workflow approval disappearing bug is FIXED.**
