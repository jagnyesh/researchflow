# Delivery Agent Fix - Complete Workflow Resolution

**Date**: November 5, 2025
**Issue**: delivery_agent failing with `AttributeError: 'NoneType' object has no attribute 'get'`
**Status**: ✅ **FIXED**

---

## Executive Summary

After fixing the orchestrator's "delivery" approval routing issue, the workflow was still failing at the delivery_agent stage. The root cause was that the **QA agent wasn't passing the `data_package` to the delivery_agent** when requesting delivery approval.

**Fixes Applied**:
1. **QA Agent** (`app/agents/qa_agent.py`): Include `data_package` and `requirements` in `approval_data` when requesting delivery approval
2. **Delivery Agent** (`app/agents/delivery_agent.py`): Add defensive validation and support both `requirements` and `structured_requirements` formats

**Result**: Complete end-to-end workflow now succeeds from request submission through final delivery!

---

## Root Cause Analysis

### The Error

```
[delivery_agent] Task failed: deliver_data - 'NoneType' object has no attribute 'get'
Traceback (most recent call last):
  File "/Users/jagnyesh/Development/FHIR_PROJECT/app/agents/delivery_agent.py", line 64, in _deliver_data
    "data": data_package.get("formatted_data"),
            ^^^^^^^^^^^^^^^^
AttributeError: 'NoneType' object has no attribute 'get'
```

### The Data Flow Problem

**Expected Flow**:
1. **extraction_agent** creates `data_package` → passes to `qa_agent`
2. **qa_agent** validates `data_package` → passes to `delivery_agent` via approval
3. **delivery_agent** receives `data_package` → creates final delivery package

**Actual Flow (BROKEN)**:
1. **extraction_agent** creates `data_package` ✅
2. **qa_agent** validates `data_package` ✅
3. **qa_agent** requests delivery approval BUT doesn't include `data_package` in approval_data ❌
4. Approval granted → orchestrator routes to **delivery_agent**
5. **delivery_agent** context missing `data_package` → CRASH ❌

### Why This Happened

The QA agent's return value when requesting delivery approval (line 109-122) was:

```python
# BEFORE (BROKEN)
return {
    "overall_status": "passed",
    "qa_report": qa_report,
    "requires_approval": True,
    "approval_type": "delivery",
    "additional_context": {
        "qa_report": qa_report,
        "approval_data": {
            "qa_report": qa_report,
            # ❌ MISSING: data_package
            # ❌ MISSING: requirements
            "message": "Full data extraction complete and QA passed...",
            "request_id": request_id,
        }
    },
}
```

The orchestrator's `_continue_workflow_after_approval` method (line 501-502) does:
```python
if approval.approval_data:
    context.update(approval.approval_data)
```

So if `data_package` isn't in `approval_data`, it won't be in the context when routing to delivery_agent.

---

## The Fixes

### Fix 1: QA Agent - Pass data_package in approval_data

**File**: `app/agents/qa_agent.py`
**Lines**: 109-126

```python
# AFTER (FIXED)
return {
    "overall_status": "passed",
    "qa_report": qa_report,
    "requires_approval": True,
    "approval_type": "delivery",
    "additional_context": {
        "qa_report": qa_report,
        "data_package": data_package,  # ✅ CRITICAL: Pass to delivery_agent
        "requirements": requirements,   # ✅ Also pass requirements
        "approval_data": {
            "qa_report": qa_report,
            "data_package": data_package,  # ✅ Include in approval data
            "requirements": requirements,
            "message": "Full data extraction complete and QA passed. Ready for delivery approval.",
            "request_id": request_id,
        }
    },
}
```

**Why**: The `approval_data` is stored in the database and then passed to the next agent when the approval is granted. By including `data_package` and `requirements` in `approval_data`, the delivery_agent will receive them in its context.

### Fix 2: Delivery Agent - Defensive Validation

**File**: `app/agents/delivery_agent.py`
**Lines**: 55-80

```python
# Accept both 'requirements' and 'structured_requirements' (from orchestrator)
requirements = context.get("requirements") or context.get("structured_requirements")
data_package = context.get("data_package")
qa_report = context.get("qa_report")

logger.info(f"[{self.agent_id}] Preparing delivery for {request_id}")

# DEFENSIVE: Validate required context
if not data_package:
    error_msg = (
        f"Missing 'data_package' in context for {request_id}. "
        f"Available keys: {list(context.keys())}. "
        f"QA agent should provide data_package in approval_data."
    )
    logger.error(f"[{self.agent_id}] {error_msg}")
    raise ValueError(error_msg)

if not requirements:
    error_msg = (
        f"Missing 'requirements'/'structured_requirements' in context for {request_id}. "
        f"Available keys: {list(context.keys())}. "
        f"Orchestrator should enrich context with requirements."
    )
    logger.error(f"[{self.agent_id}] {error_msg}")
    raise ValueError(error_msg)
```

**Why**:
1. **Accept both formats**: The orchestrator may pass `structured_requirements` while the QA agent passes `requirements`
2. **Clear error messages**: If the context is missing required data, provide actionable error messages that explain what went wrong and where the fix should be

---

## Verification

### Test Results

**Test Command**:
```bash
HAPI_DB_URL=postgresql://hapi:hapi@localhost:5433/hapi python scripts/test_complete_workflow.py
```

**Before Fixes**:
```
❌ delivery_agent.deliver_data: failed (8 failures due to retries)
AttributeError: 'NoneType' object has no attribute 'get'
State: human_review (workflow stuck)
```

**After Fixes**:
```
✅ delivery_agent.deliver_data: success (8 successes - 1 per retry of approval process)
State: complete
Completed: 2025-11-05 17:52:16
```

### Complete Agent Execution Flow (Success)

```
✅ requirements_agent.gather_requirements: success
✅ phenotype_agent.validate_feasibility: success
✅ extraction_agent.extract_preview: success
✅ qa_agent.validate_preview: success
✅ extraction_agent.extract_data: success
✅ qa_agent.validate_extracted_data: success
✅ delivery_agent.deliver_data: success
State: complete ← Workflow successfully completes!
```

---

## Complete Workflow Data Flow (Fixed)

```
1. requirements_agent
   ↓ (creates RequirementsData in DB)

2. phenotype_agent
   ↓ (creates FeasibilityReport with SQL in DB)
   → phenotype_sql approval

3. extraction_agent.extract_preview
   ↓ (creates preview_package with 10 rows)

4. qa_agent.validate_preview
   ↓ (validates preview)
   → preview_qa approval (if failed) OR auto-advance

5. extraction_agent.extract_data
   ↓ (creates data_package with full cohort)
   context = { data_package, requirements }

6. qa_agent.validate_extracted_data
   ↓ (validates data_package)
   → delivery approval
   approval_data = {
       qa_report,
       data_package,  ← ✅ NOW INCLUDED
       requirements   ← ✅ NOW INCLUDED
   }

7. [Approval granted]
   orchestrator.process_approval_response()
   ↓ context.update(approval_data)
   context = {
       request_id,
       approval_id,
       approved_by,
       qa_report,
       data_package,      ← ✅ NOW AVAILABLE
       requirements,      ← ✅ NOW AVAILABLE
       structured_requirements  ← (added by orchestrator enrichment)
   }

8. delivery_agent.deliver_data
   ↓ (receives complete context)
   ✅ data_package available
   ✅ requirements available
   → Creates final delivery package
   → Saves to storage
   → Creates DataDelivery record
   → Workflow COMPLETE
```

---

## Files Modified

### 1. `app/agents/qa_agent.py`
**Lines changed**: 109-126
**Change**: Added `data_package` and `requirements` to `approval_data` when requesting delivery approval

### 2. `app/agents/delivery_agent.py`
**Lines changed**: 55-80
**Changes**:
- Accept both `requirements` and `structured_requirements`
- Add defensive validation with clear error messages
- Fail fast if required context is missing

---

## Prevention: Design Patterns

### Pattern 1: Always Pass Data Forward in Approvals

When an agent requests approval that will route to another agent, **always include all context that the next agent will need** in the `approval_data`:

```python
# GOOD PATTERN
return {
    "requires_approval": True,
    "approval_type": "some_approval",
    "additional_context": {
        "approval_data": {
            # Include ALL data the next agent needs
            "data_from_this_agent": my_data,
            "requirements": requirements,
            "any_other_context": other_context,
        }
    },
}
```

### Pattern 2: Defensive Context Validation

Every agent should validate its required context and provide actionable error messages:

```python
# GOOD PATTERN
data = context.get("required_data")
if not data:
    error_msg = (
        f"Missing 'required_data' in context. "
        f"Available keys: {list(context.keys())}. "
        f"<agent_name> should provide this in approval_data."
    )
    logger.error(error_msg)
    raise ValueError(error_msg)
```

### Pattern 3: Accept Multiple Context Formats

Agents should accept context in multiple formats to handle different orchestration paths:

```python
# GOOD PATTERN
requirements = (
    context.get("requirements") or
    context.get("structured_requirements")
)
```

---

## Testing Recommendations

### 1. End-to-End Workflow Test
```bash
# Run complete workflow test (60 seconds)
HAPI_DB_URL=postgresql://hapi:hapi@localhost:5433/hapi \
python scripts/test_complete_workflow.py
```

Expected: Workflow completes with state "complete"

### 2. Manual UI Test
1. Start Researcher Portal: `streamlit run app/web_ui/researcher_portal.py --server.port 8501`
2. Start Admin Dashboard: `streamlit run app/web_ui/admin_dashboard.py --server.port 8502`
3. Submit request for male patients with diabetes
4. Approve phenotype SQL in Admin Dashboard
5. Approve delivery in Admin Dashboard
6. Verify request completes and data is delivered

### 3. Unit Test for QA Agent
```python
# tests/test_qa_agent.py
async def test_qa_agent_passes_data_package_to_delivery():
    """Verify QA agent includes data_package in approval_data"""
    qa_agent = QualityAssuranceAgent()

    context = {
        "request_id": "TEST-123",
        "data_package": {"cohort": [], "data_elements": {}},
        "structured_requirements": {"phi_level": "de-identified"},
    }

    result = await qa_agent.execute_task("validate_extracted_data", context)

    # Verify data_package is in approval_data
    assert result["requires_approval"] == True
    assert result["approval_type"] == "delivery"
    assert "approval_data" in result["additional_context"]
    assert "data_package" in result["additional_context"]["approval_data"]
    assert "requirements" in result["additional_context"]["approval_data"]
```

---

## Summary

**Problem**: delivery_agent was receiving `None` for `data_package` and crashing.

**Root Cause**: QA agent wasn't passing `data_package` to delivery_agent via `approval_data`.

**Solution**:
1. QA agent now includes `data_package` and `requirements` in `approval_data`
2. Delivery agent validates required context and accepts multiple formats

**Impact**: Complete end-to-end workflow now succeeds!

**Files Changed**:
- `app/agents/qa_agent.py` (lines 109-126)
- `app/agents/delivery_agent.py` (lines 55-80)

**Next Steps**:
1. Test in staging environment
2. Add unit tests for context passing
3. Deploy to production
4. Monitor for any related issues

---

## Related Fixes

This fix builds on the previous **"delivery" approval type mapping fix** in `app/orchestrator/orchestrator.py`. Together, these two fixes enable the complete end-to-end workflow:

1. **Orchestrator fix** (WORKFLOW_STUCK_FIX.md): Added "delivery" approval type to `next_agent_map`
2. **Delivery agent fix** (this document): Pass `data_package` through approvals to delivery_agent

Both fixes were necessary for the workflow to complete successfully!
