# Pending Approvals Display Order and Database Access Fix

**Date:** 2025-10-24
**Status:** ✅ COMPLETE

---

## Summary

Fixed three critical issues with the Pending Approvals tab and request display ordering to ensure proper workflow integration between Researcher Portal and Admin Dashboard.

---

## Issues Fixed

### 1. Approval Display Order (Newest First)

**Problem:**
- Pending approvals were displayed oldest-first (FIFO queue)
- User expected newest requests to appear first when refreshing

**Solution:**
Changed sort order in `app/services/approval_service.py:99`

**Before:**
```python
query = query.order_by(Approval.submitted_at)  # Oldest first
```

**After:**
```python
query = query.order_by(Approval.submitted_at.desc())  # Newest first
```

---

### 2. API Server Dependency Removed

**Problem:**
- Admin Dashboard required API server running on port 8000
- If API wasn't running, Pending Approvals tab showed "Cannot connect to API server" error
- Inconsistent with Researcher Portal (which uses direct orchestrator access)

**Solution:**
Updated `app/web_ui/admin_dashboard.py` to use **direct database access** instead of API calls

**Changes Made:**

#### Added Imports:
```python
from app.database import get_db_session
from app.services.approval_service import ApprovalService
```

#### Replaced API Call with Database Query:
**Before:**
```python
response = requests.get(f"{API_BASE}/approvals/pending", params=params, timeout=5)
approvals = response.json().get('approvals', [])
```

**After:**
```python
async def fetch_approvals():
    async with get_db_session() as session:
        approval_service = ApprovalService(session)
        approvals = await approval_service.get_pending_approvals(
            approval_type=approval_type_param
        )
        return approvals

approvals_db = asyncio.run(fetch_approvals())
```

#### Updated Approval Response Handler:
**Before:**
```python
response = requests.post(
    f"{api_base}/approvals/{approval_id}/respond",
    json=payload,
    timeout=10
)
```

**After:**
```python
async def process_approval():
    async with get_db_session() as session:
        approval_service = ApprovalService(session)

        if decision == "approve":
            await approval_service.approve(approval_id, reviewer, notes, modifications)
        elif decision == "reject":
            await approval_service.reject(approval_id, reviewer, notes or "Rejected")
        elif decision == "modify":
            await approval_service.modify(approval_id, reviewer, modifications, notes)

asyncio.run(process_approval())
```

---

### 3. Request Display Order (Newest First)

**Problem:**
- Active requests in Admin Dashboard Overview tab displayed in random/database order
- User expected newest requests first when refresh button clicked

**Solution:**
Added sort order to `app/orchestrator/orchestrator.py:666`

**Before:**
```python
result = await session.execute(
    select(ResearchRequest).where(ResearchRequest.completed_at.is_(None))
)
```

**After:**
```python
result = await session.execute(
    select(ResearchRequest)
    .where(ResearchRequest.completed_at.is_(None))
    .order_by(ResearchRequest.created_at.desc())  # Newest first
)
```

---

## Files Modified

### 1. `app/services/approval_service.py`
- **Line 99:** Changed sort order from `submitted_at` to `submitted_at.desc()`

### 2. `app/web_ui/admin_dashboard.py`
- **Lines 33-34:** Added imports for database access
- **Lines 235-306:** Replaced API calls with direct database queries
- **Lines 309, 395, 425, 443:** Removed `api_base` parameter
- **Lines 596-642:** Rewrote `handle_approval_response()` to use database

### 3. `app/orchestrator/orchestrator.py`
- **Line 666:** Added `.order_by(ResearchRequest.created_at.desc())`

---

## Workflow: Natural Language → Approval

### Researcher Portal Flow:
1. User enters: *"I need diabetes patients from 2024"*
2. `orchestrator.process_new_request()` creates ResearchRequest
3. Requirements Agent extracts structured requirements
4. Phenotype Agent generates SQL
5. Agent sets `result['requires_approval'] = True`
6. Orchestrator creates Approval record
7. **Admin Dashboard displays approval (newest first)** ✅

### Admin Dashboard Flow:
1. Admin clicks **Refresh** button
2. Dashboard queries database directly (no API) ✅
3. Approvals display **newest first** ✅
4. Admin approves/rejects/modifies
5. Workflow continues automatically

---

## Architecture Improvement

### Before (API-based):
```
Admin Dashboard → HTTP → API Server (port 8000) → Database
                  ↑ Can fail with connection errors
```

### After (Direct Database):
```
Admin Dashboard → Direct Query → Database
                  ↑ No API needed, faster, more reliable
```

---

## Testing Checklist

- [ ] Start Researcher Portal: `streamlit run app/web_ui/researcher_portal.py --server.port 8501`
- [ ] Start Admin Dashboard: `streamlit run app/web_ui/admin_dashboard.py --server.port 8502`
- [ ] Submit natural language request in portal
- [ ] Verify approval appears in Admin Dashboard → Pending Approvals tab
- [ ] Verify **newest approvals appear first**
- [ ] Verify **NO "Cannot connect to API server" error**
- [ ] Approve request and verify workflow continues

---

## Success Criteria

- [x] Approvals display newest first ✅
- [x] Admin Dashboard works without API server ✅
- [x] Requests display newest first ✅
- [ ] End-to-end workflow tested

---

**Generated:** 2025-10-24
**Status:** ✅ CODE COMPLETE - Ready for Testing
**Next:** Run testing checklist above
