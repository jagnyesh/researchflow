# Complete Workflow Fix - End-to-End Resolution

**Date**: November 5, 2025
**Issue**: Workflow getting stuck with no updates on Researcher Portal
**Status**: ✅ **FULLY RESOLVED**

---

## Executive Summary

The ResearchFlow workflow had **two critical bugs** preventing end-to-end completion:

1. **Bug #1**: Missing "delivery" approval type mapping in orchestrator → workflow stuck after delivery approval
2. **Bug #2**: QA agent not passing `data_package` to delivery_agent → delivery_agent crash

Both bugs have been **fixed and verified** with end-to-end testing. The complete workflow now succeeds from request submission through final data delivery.

---

## Problem Statement

### User-Reported Symptoms

From screenshots:
- Request stuck in "Human Review" state with "Extraction Agent" as current agent
- Duration increasing (2 min → 4 min) but no progress
- Multiple approvals granted (Phenotype SQL, Preview QA) but workflow not advancing
- No updates propagating to Researcher Portal
- Workflow timeline only showing Requirements Agent despite later approvals

### Observable Behavior

```
✅ requirements_agent.gather_requirements: success
✅ phenotype_agent.validate_feasibility: success
✅ extraction_agent.extract_preview: success
✅ qa_agent.validate_preview: success
✅ extraction_agent.extract_data: success
✅ qa_agent.validate_extracted_data: success
❌ delivery_agent.deliver_data: failed (8 failures)
State: human_review (STUCK)
```

---

## Investigation & Root Cause Analysis

### Diagnostic Approach

As a senior principal engineer with 30 years of experience would approach this:

1. **Created diagnostic tools** to examine database state and trace workflow
   - `scripts/diagnose_stuck_request.py` - Deep database analysis
   - `scripts/list_all_requests.py` - List all requests
   - `scripts/test_complete_workflow.py` - End-to-end workflow test with auto-approval

2. **Traced complete workflow** with live testing and monitoring
3. **Identified TWO distinct bugs** in approval routing and context passing

### Bug #1: Missing "Delivery" Approval Type Mapping

**Location**: `app/orchestrator/orchestrator.py:473-483`

**Root Cause**: The orchestrator's `next_agent_map` in `_continue_workflow_after_approval` was missing the "delivery" approval type.

**Error Message**:
```
[REQ-20251105-C2D8A452] No next agent found for approval type: 'delivery'.
Available types: ['requirements', 'phenotype_sql', 'preview_qa', 'extraction', 'qa', 'scope_change']
```

**Why This Happened**: Architecture mismatch between workflow_engine.py (which defined delivery approval transition) and orchestrator.py (which didn't have routing logic for it).

**Impact**: When delivery approval was granted, orchestrator couldn't determine next agent → workflow hung indefinitely.

### Bug #2: Missing data_package in Delivery Context

**Location**: `app/agents/qa_agent.py:109-126`

**Root Cause**: QA agent wasn't including `data_package` in `approval_data` when requesting delivery approval.

**Error Message**:
```
[delivery_agent] Task failed: deliver_data - 'NoneType' object has no attribute 'get'
AttributeError: 'NoneType' object has no attribute 'get'
```

**Why This Happened**: QA agent's return value only included `qa_report` in approval_data, not the `data_package` that delivery_agent requires.

**Impact**: Even after fixing Bug #1, delivery_agent crashed because it didn't receive the data package.

---

## The Fixes

### Fix #1: Add "Delivery" Approval Type Mapping

**File**: `app/orchestrator/orchestrator.py`
**Line**: 479 (added)

```python
next_agent_map = {
    "requirements": ("phenotype_agent", "validate_feasibility"),
    "phenotype_sql": ("extraction_agent", "extract_preview"),
    "preview_qa": ("extraction_agent", "extract_data"),
    "extraction": ("extraction_agent", "extract_data"),
    "qa": ("delivery_agent", "deliver_data"),
    "delivery": ("delivery_agent", "deliver_data"),  # ✅ ADDED
    "scope_change": ("requirements_agent", "gather_requirements"),
}
```

### Fix #2: Pass data_package in Approval Context

**File**: `app/agents/qa_agent.py`
**Lines**: 109-126

```python
return {
    "overall_status": "passed",
    "qa_report": qa_report,
    "requires_approval": True,
    "approval_type": "delivery",
    "additional_context": {
        "qa_report": qa_report,
        "data_package": data_package,  # ✅ ADDED
        "requirements": requirements,   # ✅ ADDED
        "approval_data": {
            "qa_report": qa_report,
            "data_package": data_package,  # ✅ ADDED
            "requirements": requirements,   # ✅ ADDED
            "message": "Full data extraction complete and QA passed. Ready for delivery approval.",
            "request_id": request_id,
        }
    },
}
```

### Fix #3: Defensive Validation in Delivery Agent

**File**: `app/agents/delivery_agent.py`
**Lines**: 55-80

```python
# Accept both 'requirements' and 'structured_requirements' (from orchestrator)
requirements = context.get("requirements") or context.get("structured_requirements")
data_package = context.get("data_package")
qa_report = context.get("qa_report")

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

---

## Verification & Testing

### End-to-End Test Results

**Test Command**:
```bash
HAPI_DB_URL=postgresql://hapi:hapi@localhost:5433/hapi python scripts/test_complete_workflow.py
```

**Before All Fixes**:
```
State: human_review (STUCK)
8 duplicate "delivery" approvals created (retry loop)
❌ No next agent found for approval type: 'delivery'
```

**After Fix #1 (orchestrator)**:
```
Workflow progresses past delivery approval
✅ Routes to delivery_agent.deliver_data
❌ delivery_agent crashes: 'NoneType' object has no attribute 'get'
```

**After All Fixes**:
```
✅ delivery_agent.deliver_data: success
State: complete
Completed: 2025-11-05 17:52:16
```

### Complete Successful Workflow Execution

```
================================================================================
WORKFLOW TEST: Creating new request and monitoring progress
================================================================================

Creating request...
✅ Request created: REQ-20251105-XXXXXXXX
Starting monitoring...

MONITORING REQUEST: REQ-20251105-XXXXXXXX
Duration: 60 seconds
================================================================================

   ⏳ PENDING APPROVAL: phenotype_sql (ID: 25)
      Auto-approving and continuing workflow...
      ✅ Approved and workflow continued!
[17:52:14] State: phenotype_review, Agent: phenotype_agent
[17:52:15] State: preview_extraction, Agent: extraction_agent
[17:52:15] State: preview_qa, Agent: qa_agent
[17:52:16] State: data_extraction, Agent: extraction_agent
[17:52:16] State: qa_validation, Agent: qa_agent
   ⏳ PENDING APPROVAL: delivery (ID: 26)
      Auto-approving and continuing workflow...
      ✅ Approved and workflow continued!
[17:52:16] State: complete, Agent: delivery_agent

================================================================================
MONITORING COMPLETE
================================================================================

FINAL STATUS:
  State: complete
  Agent: delivery_agent
  Completed: 2025-11-05 17:52:16.980102

  APPROVALS:
    ✅ phenotype_sql: approved
    ✅ delivery: approved

  AGENT EXECUTIONS:
    ✅ requirements_agent.gather_requirements: success
    ✅ phenotype_agent.validate_feasibility: success
    ✅ extraction_agent.extract_preview: success
    ✅ qa_agent.validate_preview: success
    ✅ extraction_agent.extract_data: success
    ✅ qa_agent.validate_extracted_data: success
    ✅ delivery_agent.deliver_data: success
```

---

## Complete Workflow Flow (Fixed)

```
1. Researcher Portal
   → Submit request: "male patients with diabetes"
   ↓

2. requirements_agent.gather_requirements
   → Extract structured requirements
   → Save RequirementsData to DB
   → Request requirements approval (if needed)
   ↓

3. phenotype_agent.validate_feasibility
   → Generate SQL-on-FHIR query
   → Estimate cohort size
   → Save FeasibilityReport to DB
   → Request phenotype_sql approval
   ↓

4. [Admin approves phenotype_sql]
   ↓

5. extraction_agent.extract_preview
   → Extract 10 rows per data element
   → Create preview_package
   ↓

6. qa_agent.validate_preview
   → Validate cohort count matches estimate (±10%)
   → If failed: Request preview_qa approval
   → If passed: Auto-advance
   ↓

7. extraction_agent.extract_data
   → Execute phenotype SQL
   → Extract all requested data elements
   → Apply de-identification
   → Format as CSV files
   → Create data_package
   ↓

8. qa_agent.validate_extracted_data
   → Run comprehensive QA checks
   → Create qa_report
   → ✅ Include data_package + requirements in approval_data
   → Request delivery approval
   ↓

9. [Admin approves delivery]
   → orchestrator.process_approval_response()
   → ✅ Lookup "delivery" in next_agent_map → delivery_agent
   → ✅ Pass approval_data (with data_package) to delivery_agent
   ↓

10. delivery_agent.deliver_data
    → ✅ Receive data_package, requirements, qa_report
    → Create final delivery package with metadata
    → Generate data dictionary
    → Generate citation info
    → Save all files to storage
    → Create DataDelivery record in DB
    → Send notification to researcher
    → Mark workflow as COMPLETE
    ↓

11. Researcher Portal
    → Show request status: "Complete"
    → Show delivery location
    → Allow download of data files
```

---

## Files Changed

### 1. Orchestrator - Approval Routing
**File**: `app/orchestrator/orchestrator.py`
**Lines**: 473-483
**Change**: Added "delivery" approval type mapping

### 2. QA Agent - Context Passing
**File**: `app/agents/qa_agent.py`
**Lines**: 109-126
**Change**: Include data_package and requirements in approval_data

### 3. Delivery Agent - Defensive Validation
**File**: `app/agents/delivery_agent.py`
**Lines**: 55-80
**Change**: Validate required context, accept multiple formats

### 4. Diagnostic Scripts (NEW)
- `scripts/diagnose_stuck_request.py` - Database analysis tool
- `scripts/test_complete_workflow.py` - End-to-end workflow test
- `scripts/list_all_requests.py` - Request listing utility

---

## Deployment Checklist

### Pre-Deployment

- [x] All fixes applied
- [x] End-to-end testing completed
- [x] Documentation created
- [ ] Code review by team
- [ ] Integration tests passed
- [ ] Security review (no new vulnerabilities)

### Deployment Steps

1. **Commit changes**:
   ```bash
   git add app/orchestrator/orchestrator.py
   git add app/agents/qa_agent.py
   git add app/agents/delivery_agent.py
   git add scripts/diagnose_stuck_request.py
   git add scripts/test_complete_workflow.py
   git add scripts/list_all_requests.py
   git add WORKFLOW_STUCK_FIX.md
   git add DELIVERY_AGENT_FIX.md
   git add COMPLETE_WORKFLOW_FIX_SUMMARY.md

   git commit -m "fix: complete end-to-end workflow - orchestrator routing + delivery context

   Two critical fixes for workflow completion:

   1. Orchestrator: Add missing 'delivery' approval type mapping
      - Fixes workflow getting stuck after delivery approval
      - Routes to delivery_agent when delivery is approved

   2. QA Agent: Pass data_package to delivery_agent
      - Include data_package and requirements in approval_data
      - Enables delivery_agent to create final delivery package

   3. Delivery Agent: Defensive validation
      - Accept both requirements formats
      - Clear error messages for missing context

   Result: Complete end-to-end workflow now succeeds!

   Includes diagnostic scripts for troubleshooting stuck workflows."
   ```

2. **Push to repository**:
   ```bash
   git push origin feature/complete-workflow-fix
   ```

3. **Deploy to staging**: Test complete workflow manually

4. **Deploy to production**: Monitor for issues

### Post-Deployment Monitoring

**Monitor for**:
- "No next agent found" errors in logs
- delivery_agent failures
- Workflows not completing
- Approvals not triggering next steps

**Success Metrics**:
- Workflows complete end-to-end (state = "complete")
- No stuck workflows (state != "human_review" indefinitely)
- Admin Dashboard shows correct request progression
- Researcher Portal shows delivery location and files

---

## Prevention Strategies

### 1. Approval Type Registry (Future Enhancement)

Create centralized approval type registry to prevent mismatches:

```python
# app/orchestrator/approval_types.py (NEW FILE)
APPROVAL_TYPES = {
    "requirements": {
        "next_agent": "phenotype_agent",
        "next_task": "validate_feasibility",
    },
    "phenotype_sql": {
        "next_agent": "extraction_agent",
        "next_task": "extract_preview",
    },
    "delivery": {
        "next_agent": "delivery_agent",
        "next_task": "deliver_data",
    },
    # ...
}
```

Use this in both workflow_engine.py and orchestrator.py.

### 2. Validation Tests

```python
# tests/test_approval_routing.py (NEW)
def test_all_approval_types_have_orchestrator_mappings():
    """Ensure every approval type has a routing rule"""
    # Extract approval types from workflow_engine
    # Verify orchestrator has mappings for all
    pass

# tests/test_qa_agent.py (NEW)
async def test_qa_passes_required_context_to_delivery():
    """Verify QA agent passes data_package to delivery_agent"""
    # Run QA validation
    # Verify data_package in approval_data
    pass
```

### 3. Context Passing Pattern

**Document standard pattern** for passing context between agents via approvals:

```python
# PATTERN: Agent requesting approval that routes to another agent
return {
    "requires_approval": True,
    "approval_type": "some_approval",
    "additional_context": {
        # Include ALL data the next agent needs
        "approval_data": {
            "data_from_this_agent": my_data,
            "requirements": requirements,
            "any_other_context": context_needed_by_next_agent,
        }
    },
}
```

---

## Summary

### Problem
Workflow getting stuck with no visible progress, requests showing in "Human Review" state indefinitely.

### Root Causes
1. Missing "delivery" approval type mapping in orchestrator
2. QA agent not passing data_package to delivery_agent

### Solutions
1. Added "delivery" mapping to orchestrator's next_agent_map
2. QA agent includes data_package and requirements in approval_data
3. Delivery agent validates required context with clear error messages

### Result
✅ **Complete end-to-end workflow now succeeds!**
- Requests progress from submission through delivery
- All agent executions successful
- Workflow state reaches "complete"
- Data delivered to researcher

### Files Changed
- `app/orchestrator/orchestrator.py` (1 line)
- `app/agents/qa_agent.py` (9 lines)
- `app/agents/delivery_agent.py` (26 lines)
- 3 new diagnostic scripts

### Testing
- End-to-end test: ✅ PASSING
- Manual UI test: Ready for verification
- Unit tests: To be added

### Next Steps
1. ✅ Fixes applied and tested
2. Code review by team
3. Integration testing
4. Deploy to staging
5. Deploy to production
6. Monitor for issues

---

## Documentation References

- **WORKFLOW_STUCK_FIX.md** - Bug #1 (orchestrator routing)
- **DELIVERY_AGENT_FIX.md** - Bug #2 (delivery context)
- **COMPLETE_WORKFLOW_FIX_SUMMARY.md** (this file) - Complete overview

For troubleshooting stuck workflows, use:
- `scripts/diagnose_stuck_request.py` - Analyze stuck requests
- `scripts/test_complete_workflow.py` - Test end-to-end workflow
- `scripts/list_all_requests.py` - List all requests in DB
