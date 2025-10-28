# LangSmith Workflow Traces - All Execution Paths

**Sprint 5 Enhancement** | **Created:** 2025-10-27 | **Status:** Complete

This guide documents the expected LangSmith trace patterns for all 20+ execution paths in the ResearchFlow LangGraph workflow, enabling you to identify, monitor, and debug any workflow scenario.

---

## Table of Contents

1. [Overview](#overview)
2. [Understanding Trace Hierarchy](#understanding-trace-hierarchy)
3. [Success Path Traces](#success-path-traces)
4. [Failure Path Traces](#failure-path-traces)
5. [Pause/Wait Path Traces](#pausewait-path-traces)
6. [Loop/Retry Path Traces](#loopretry-path-traces)
7. [Edge Case Path Traces](#edge-case-path-traces)
8. [Filtering & Searching Traces](#filtering--searching-traces)
9. [Debugging with Traces](#debugging-with-traces)
10. [Performance Benchmarks](#performance-benchmarks)

---

## Overview

### Trace Architecture

ResearchFlow uses **3-level hierarchical tracing**:

```
Level 1: Workflow Trace (@traceable on run() method)
  ResearchFlow_FullWorkflow
    └── Duration: Total workflow execution time
    └── Cost: Sum of all LLM calls
    └── Tags: workflow, langgraph, research, [e2e-test|production]
    └── Metadata: request_id, initial_state, researcher, timestamp

Level 2: Agent Traces (@traceable on execute_task())
  RequirementsAgent, PhenotypeAgent, DeliveryAgent, etc.
    └── Duration: Agent execution time
    └── Tags: agent, [requirements|phenotype|delivery], llm
    └── Metadata: agent_type, task, capability

Level 3: LLM Calls (auto-traced by LangChain)
  ChatAnthropic.ainvoke()
    └── Duration: LLM API response time
    └── Cost: Input/output token cost
    └── Metrics: input_tokens, output_tokens, model
```

### Identifying Workflow Paths

Each workflow execution creates a top-level trace with:
- **Name:** `ResearchFlow_FullWorkflow`
- **Final State:** Indicates which path was taken
- **Duration:** Varies by path (60ms - 15 minutes)
- **Child Traces:** Show which agents were invoked

---

## Success Path Traces

### Path 1.1: Happy Path (Zero Rejections)

**Trace Name:** `ResearchFlow_FullWorkflow`
**Final State:** `complete`
**Expected Duration:** 60-120ms (no LLM calls in stub mode) | 2-3 minutes (production)
**Expected Cost:** $0.05-$0.15

#### Trace Hierarchy

```
ResearchFlow_FullWorkflow (90ms) ✅
├─ [1] new_request (2ms) ✅
├─ [2] requirements_gathering (3ms) ✅
├─ [3] requirements_review (2ms) ✅
├─ [4] feasibility_validation (45ms) ✅
│   └─ ChatAnthropic (42ms) ✅  [Production only]
│      Input: 3,245 tokens | Output: 512 tokens | Cost: $0.0234
├─ [5] phenotype_review (2ms) ✅
├─ [6] schedule_kickoff (8ms) ✅
├─ [7] extraction_approval (2ms) ✅
├─ [8] data_extraction (6ms) ✅
├─ [9] qa_validation (5ms) ✅
├─ [10] qa_review (2ms) ✅
├─ [11] data_delivery (14ms) ✅
│   └─ ChatAnthropic (11ms) ✅  [Production only]
│      Input: 1,850 tokens | Output: 278 tokens | Cost: $0.0142
└─ [12] complete (1ms) ✅
```

#### Key Metrics

| Metric | Stub/Test Value | Production Value |
|--------|----------------|------------------|
| Total States Executed | 12 | 12 |
| LLM Calls | 0 | 2-3 |
| Total Duration | 60-120ms | 120-180 seconds |
| Total Cost | $0 | $0.05-$0.15 |
| Approval Gates | 5 (all auto-approved) | 5 (manual) |

#### Metadata

```json
{
  "request_id": "REQ-E2E-1761574143",
  "initial_state": "new_request",
  "researcher": "Dr. Sarah Chen",
  "timestamp": "2025-10-27T09:09:03.881Z",
  "final_state": "complete",
  "duration_ms": 90,
  "states_executed": 12,
  "llm_calls": 0
}
```

#### Identifying This Path

**Filters:**
- `final_state: complete`
- `states_executed: 12`
- `duration < 200ms` (stub) OR `duration < 300s` (production)

**Search:**
```
Tag: e2e-test OR Tag: production
Metadata: final_state = "complete"
Duration: < 300s
```

---

### Path 1.2: Requirements Rejection Loop → Success

**Trace Name:** `ResearchFlow_FullWorkflow`
**Final State:** `complete`
**Expected Duration:** 3-5 minutes (production)
**Expected Cost:** $0.15-$0.30 (additional LLM calls)

#### Trace Hierarchy

```
ResearchFlow_FullWorkflow (180ms) ✅
├─ [1] new_request (2ms) ✅
├─ [2] requirements_gathering (40ms) ✅
│   └─ ChatAnthropic (35ms) ✅
│      Input: 2,100 tokens | Output: 450 tokens | Cost: $0.0198
├─ [3] requirements_review (2ms) ✅
├─ [4] requirements_gathering (45ms) ✅  ← SECOND ITERATION (rejected)
│   └─ ChatAnthropic (40ms) ✅
│      Input: 3,500 tokens | Output: 520 tokens | Cost: $0.0280
├─ [5] requirements_review (2ms) ✅  ← SECOND REVIEW (approved)
├─ [6] feasibility_validation (45ms) ✅
├─ [7] phenotype_review (2ms) ✅
├─ [8] schedule_kickoff (8ms) ✅
├─ [9] extraction_approval (2ms) ✅
├─ [10] data_extraction (6ms) ✅
├─ [11] qa_validation (5ms) ✅
├─ [12] qa_review (2ms) ✅
├─ [13] data_delivery (14ms) ✅
└─ [14] complete (1ms) ✅
```

#### Key Metrics

| Metric | Value |
|--------|-------|
| Total States Executed | 14 (2 extra for loop) |
| LLM Calls | 4-5 (2 extra for requirements) |
| Total Duration | 3-5 minutes |
| Total Cost | $0.15-$0.30 |
| Loop Count | 1 (requirements rejection) |

#### Identifying This Path

**Characteristic:**
- **Duplicate states:** `requirements_gathering` and `requirements_review` appear **twice** in trace
- **Increased LLM calls:** 4-5 instead of 2-3
- **Higher cost:** ~2x happy path

**Search:**
```
Metadata: states_executed > 12
Contains: "requirements_gathering" (count: 2)
Duration: > 180s
```

---

### Path 1.3: Phenotype SQL Rejection Loop → Success

**Trace Name:** `ResearchFlow_FullWorkflow`
**Final State:** `complete`
**Expected Duration:** 3-4 minutes
**Expected Cost:** $0.10-$0.20

#### Trace Hierarchy

```
ResearchFlow_FullWorkflow (195ms) ✅
├─ [1-5] [same as happy path up to phenotype_review]
├─ [5] phenotype_review (2ms) ✅  ← FIRST REVIEW (rejected)
├─ [6] feasibility_validation (50ms) ✅  ← SECOND SQL GENERATION
│   └─ ChatAnthropic (45ms) ✅
│      Input: 3,800 tokens | Output: 580 tokens | Cost: $0.0298
│      Metadata: regeneration_attempt: 2, previous_error: "Missing JOIN"
├─ [7] phenotype_review (2ms) ✅  ← SECOND REVIEW (approved)
├─ [8-14] [continues to complete]
```

#### Key Metrics

| Metric | Value |
|--------|-------|
| Total States Executed | 13 |
| LLM Calls | 3-4 (1 extra for phenotype) |
| Total Duration | 3-4 minutes |
| Total Cost | $0.10-$0.20 |
| Loop Count | 1 (phenotype rejection) |

#### Identifying This Path

**Characteristic:**
- `feasibility_validation` and `phenotype_review` appear **twice**
- PhenotypeAgent trace shows `regeneration_attempt > 1`

**Search:**
```
Metadata: states_executed = 13
Contains: "phenotype_review" (count: 2)
```

---

### Path 1.4: QA Rejection Loop → Success

**Trace Name:** `ResearchFlow_FullWorkflow`
**Final State:** `complete`
**Expected Duration:** 4-6 minutes
**Expected Cost:** $0.05-$0.15 (same LLM calls, but longer duration)

#### Trace Hierarchy

```
ResearchFlow_FullWorkflow (240ms) ✅
├─ [1-11] [same as happy path up to qa_review]
├─ [11] qa_review (2ms) ✅  ← FIRST REVIEW (rejected)
├─ [12] data_extraction (85ms) ✅  ← RE-EXTRACTION (different params)
│   Metadata: extraction_attempt: 2, phi_level: "safe_harbor" (changed from "limited_dataset")
├─ [13] qa_validation (12ms) ✅  ← RE-VALIDATION
│   └─ QA report regenerated
├─ [14] qa_review (2ms) ✅  ← SECOND REVIEW (approved)
├─ [15] data_delivery (14ms) ✅
└─ [16] complete (1ms) ✅
```

#### Key Metrics

| Metric | Value |
|--------|-------|
| Total States Executed | 16 |
| LLM Calls | 2-3 (same as happy path) |
| Total Duration | 4-6 minutes (re-extraction is slow) |
| Total Cost | $0.05-$0.15 |
| Loop Count | 1 (QA rejection) |

#### Identifying This Path

**Characteristic:**
- `data_extraction`, `qa_validation`, `qa_review` appear **twice**
- ExtractionAgent shows `extraction_attempt > 1`
- Duration significantly longer due to re-extraction

**Search:**
```
Metadata: states_executed > 14
Contains: "data_extraction" (count: 2)
Duration: > 240s
```

---

### Path 1.5: Multiple Rejections → Success

**Trace Name:** `ResearchFlow_FullWorkflow`
**Final State:** `complete`
**Expected Duration:** 10-15 minutes
**Expected Cost:** $0.20-$0.50

#### Trace Hierarchy

```
ResearchFlow_FullWorkflow (720ms) ✅
├─ [1-2] requirements_gathering (loop 1)
├─ [3] requirements_review (rejected)
├─ [4-5] requirements_gathering (loop 2)  ← FIRST REJECTION LOOP
├─ [6] requirements_review (approved)
├─ [7] feasibility_validation
├─ [8] phenotype_review (rejected)
├─ [9] feasibility_validation (regenerate)  ← SECOND REJECTION LOOP
├─ [10] phenotype_review (approved)
├─ [11-14] [schedule → extraction → qa_validation]
├─ [15] qa_review (rejected)
├─ [16-17] data_extraction + qa_validation (re-extract)  ← THIRD REJECTION LOOP
├─ [18] qa_review (approved)
├─ [19] data_delivery
└─ [20] complete ✅
```

#### Key Metrics

| Metric | Value |
|--------|-------|
| Total States Executed | 20 |
| LLM Calls | 6-8 |
| Total Duration | 10-15 minutes |
| Total Cost | $0.20-$0.50 |
| Loop Count | 3 (all rejection types) |

#### Identifying This Path

**Characteristic:**
- Very high `states_executed` (15-20)
- Multiple duplicate states
- High cost and duration
- Most realistic production scenario

**Search:**
```
Metadata: states_executed > 15
Duration: > 600s
Cost: > $0.20
```

---

## Failure Path Traces

### Path 2.1: Not Feasible (Cohort Too Small)

**Trace Name:** `ResearchFlow_FullWorkflow`
**Final State:** `not_feasible` ⛔
**Expected Duration:** 40-60ms (stub) | 1-2 minutes (production)
**Expected Cost:** $0.03-$0.08

#### Trace Hierarchy

```
ResearchFlow_FullWorkflow (55ms) ❌
├─ [1] new_request (2ms) ✅
├─ [2] requirements_gathering (3ms) ✅
├─ [3] requirements_review (2ms) ✅
├─ [4] feasibility_validation (45ms) ✅
│   └─ ChatAnthropic (42ms) ✅
│      Input: 3,200 tokens | Output: 480 tokens | Cost: $0.0220
│      Output: {"feasible": false, "estimated_cohort_size": 0}
└─ [5] not_feasible (1ms) ⛔ TERMINAL
```

#### Key Metrics

| Metric | Value |
|--------|-------|
| Total States Executed | 5 (early termination) |
| LLM Calls | 1-2 (requirements + phenotype only) |
| Total Duration | 40-60ms (stub) | 60-120s (production) |
| Total Cost | $0.03-$0.08 |
| Terminal State | `not_feasible` |

#### Metadata

```json
{
  "request_id": "REQ-12345",
  "final_state": "not_feasible",
  "escalation_reason": "Cohort size too small or infeasible criteria",
  "feasible": false,
  "estimated_cohort_size": 0,
  "phenotype_sql": "SELECT * FROM Patient WHERE ... [returns 0 rows]"
}
```

#### Identifying This Path

**Filters:**
- `final_state: not_feasible`
- `states_executed: 5`
- `escalation_reason: "Cohort size too small"`

**Search:**
```
Tag: production
Metadata: final_state = "not_feasible"
Metadata: estimated_cohort_size < 10
```

**Debugging Tips:**
1. Check `phenotype_sql` in trace metadata - does it have correct WHERE clauses?
2. Review `inclusion_criteria` and `exclusion_criteria` - too restrictive?
3. Check `time_period` - is date range too narrow?
4. Run SQL manually against FHIR database to verify cohort size

---

### Path 2.2: QA Failed (Validation Errors)

**Trace Name:** `ResearchFlow_FullWorkflow`
**Final State:** `qa_failed` ⛔
**Expected Duration:** 80-100ms (stub) | 4-6 minutes (production)
**Expected Cost:** $0.05-$0.15

#### Trace Hierarchy

```
ResearchFlow_FullWorkflow (95ms) ❌
├─ [1-8] [same as happy path up to data_extraction]
├─ [9] qa_validation (15ms) ❌
│   └─ QA checks executed:
│      ├─ Completeness check: FAILED (score: 0.65, threshold: 0.80)
│      ├─ Duplicate check: FAILED (47 duplicates found)
│      └─ PHI scrubbing: PASSED
│   Output: {"overall_status": "failed"}
└─ [10] qa_failed (1ms) ⛔ TERMINAL
```

#### Key Metrics

| Metric | Value |
|--------|-------|
| Total States Executed | 10 |
| LLM Calls | 2-3 |
| Total Duration | 80-100ms (stub) | 240-360s (production) |
| Total Cost | $0.05-$0.15 |
| Terminal State | `qa_failed` |

#### Metadata

```json
{
  "final_state": "qa_failed",
  "escalation_reason": "QA validation failed",
  "overall_status": "failed",
  "qa_report": {
    "overall_status": "failed",
    "checks": {
      "completeness": {
        "passed": false,
        "score": 0.65,
        "missing_fields": ["medications", "lab_results"]
      },
      "duplicates": {
        "passed": false,
        "duplicates_found": 47
      },
      "phi_scrubbing": {
        "passed": true,
        "phi_found": 0
      }
    }
  }
}
```

#### Identifying This Path

**Filters:**
- `final_state: qa_failed`
- `overall_status: failed`
- `states_executed: 10`

**Search:**
```
Metadata: final_state = "qa_failed"
Metadata: overall_status = "failed"
```

**Debugging Tips:**
1. **Completeness failures:**
   - Check `missing_fields` in QA report
   - Verify FHIR server has complete records for requested data elements
   - Review extraction SQL - are all required fields included?

2. **Duplicate failures:**
   - Check `duplicates_found` count
   - Review extraction logic for GROUP BY clauses
   - Verify FHIR server doesn't have duplicate resource IDs

3. **PHI scrubbing failures:**
   - Check `phi_found` - which fields leaked?
   - Review de-identification configuration
   - Verify PHI level is set correctly (safe_harbor vs limited_dataset)

---

### Path 2.3: Human Review Required (Extraction Rejection)

**Trace Name:** `ResearchFlow_FullWorkflow`
**Final State:** `human_review` ⛔
**Expected Duration:** 50-70ms (stub) | 2-3 minutes (production)
**Expected Cost:** $0.05-$0.10

#### Trace Hierarchy

```
ResearchFlow_FullWorkflow (65ms) ❌
├─ [1-7] [same as happy path up to extraction_approval]
├─ [8] extraction_approval (2ms) ❌
│   Metadata: {
│     "extraction_approved": false,
│     "extraction_rejection_reason": "IRB approval not verified - awaiting documentation"
│   }
└─ [9] human_review (1ms) ⛔ TERMINAL
```

#### Key Metrics

| Metric | Value |
|--------|-------|
| Total States Executed | 9 |
| LLM Calls | 2-3 |
| Total Duration | 50-70ms (stub) | 120-180s (production) |
| Total Cost | $0.05-$0.10 |
| Terminal State | `human_review` |

#### Metadata

```json
{
  "final_state": "human_review",
  "escalation_reason": "Extraction rejected - needs human intervention",
  "extraction_approved": false,
  "extraction_rejection_reason": "IRB approval not verified - awaiting documentation"
}
```

#### Identifying This Path

**Filters:**
- `final_state: human_review`
- `extraction_approved: false`
- `states_executed: 9`

**Search:**
```
Metadata: final_state = "human_review"
Metadata: extraction_approved = false
```

**Common Rejection Reasons:**
1. **IRB approval missing/expired**
2. **Study protocol not finalized**
3. **Ethical concerns** (sensitive populations, risky study design)
4. **Legal/compliance issues** (HIPAA violations, consent problems)
5. **Resource constraints** (too expensive, system overload)

**Debugging Tips:**
- Check `extraction_rejection_reason` for specific issue
- Review researcher's IRB documentation
- Coordinate with informatician/data governance team

---

## Pause/Wait Path Traces

### Path 3.1: Incomplete Requirements (Wait for User Input)

**Trace Name:** `ResearchFlow_FullWorkflow`
**Final State:** `requirements_gathering` ⏸️
**Expected Duration:** 15-25ms
**Expected Cost:** $0.02-$0.05 (partial LLM call)

#### Trace Hierarchy

```
ResearchFlow_FullWorkflow (20ms) ⏸️
├─ [1] new_request (2ms) ✅
└─ [2] requirements_gathering (15ms) ⏸️ PAUSED
    └─ ChatAnthropic (12ms) ✅
       Input: 1,500 tokens | Output: 180 tokens | Cost: $0.0120
       Output: {
         "requirements_complete": false,
         "completeness_score": 0.6,
         "missing_fields": ["exclusion_criteria", "time_period"],
         "next_question": "What is your target time period for this study?"
       }
```

#### Key Metrics

| Metric | Value |
|--------|-------|
| Total States Executed | 2 (early pause) |
| LLM Calls | 1 (partial) |
| Total Duration | 15-25ms (stub) | 30-60s (production) |
| Total Cost | $0.02-$0.05 |
| Final State | `requirements_gathering` (not terminal) |

#### Metadata

```json
{
  "final_state": "requirements_gathering",
  "requirements_complete": false,
  "completeness_score": 0.6,
  "missing_fields": ["exclusion_criteria", "time_period"],
  "conversation_history": [
    {"role": "user", "content": "I need patients with diabetes"},
    {"role": "assistant", "content": "What is your target time period for this study?"}
  ]
}
```

#### Identifying This Path

**Filters:**
- `final_state: requirements_gathering`
- `requirements_complete: false`
- `completeness_score < 0.8`

**Search:**
```
Metadata: final_state = "requirements_gathering"
Metadata: requirements_complete = false
```

**Resumption:**
```python
# User provides additional information
state_updated = {
    **paused_state,
    'requirements': {
        **paused_state['requirements'],
        'time_period': {'start': '2020-01-01', 'end': '2023-12-31'}
    },
    'completeness_score': 0.9,
    'requirements_complete': True
}

# Resume workflow
final_state = await workflow.run(state_updated)
# Now continues to requirements_review
```

---

### Path 3.2-3.5: Pending Approval Gates

**Trace Names:** Various
**Final States:** `requirements_review`, `phenotype_review`, `extraction_approval`, `qa_review` ⏸️
**Expected Duration:** 10-30ms
**Expected Cost:** Varies by stage

#### Generic Approval Gate Trace

```
ResearchFlow_FullWorkflow (25ms) ⏸️
├─ [states before gate]
└─ [approval_state] (2ms) ⏸️ WAITING FOR APPROVAL
    Metadata: {
      "approval_field": null,  ← Neither True nor False
      "awaiting_human_review": true
    }
```

#### Approval Gate Comparison

| Gate | Final State | Prerequisites | Expected Duration | Typical Wait Time |
|------|-------------|---------------|-------------------|-------------------|
| Requirements Review | `requirements_review` | Requirements complete | 15-20ms | 1-4 hours |
| Phenotype Review | `phenotype_review` | SQL generated | 50-70ms | 30min-2 hours |
| Extraction Approval | `extraction_approval` | Meeting scheduled | 60-80ms | 2-8 hours |
| QA Review | `qa_review` | QA validation passed | 90-110ms | 1-3 hours |

#### Identifying Approval Gates

**Filters:**
- `final_state` ends in `_review` OR `_approval`
- Corresponding `*_approved` field is `null`

**Search:**
```
Metadata: requirements_approved = null
OR Metadata: phenotype_approved = null
OR Metadata: extraction_approved = null
OR Metadata: qa_approved = null
```

#### Resumption Pattern

```python
# Informatician approves via approval service
state_approved = {
    **paused_state,
    'requirements_approved': True  # Or phenotype_approved, etc.
}

# Resume workflow
final_state = await workflow.run(state_approved)
# Continues to next state
```

---

## Loop/Retry Path Traces

### Identifying Loops in Traces

**Loop Detection Patterns:**

1. **State Repetition:** Same state appears multiple times in execution sequence
   ```
   states_executed: [
     "new_request",
     "requirements_gathering",  ← First occurrence
     "requirements_review",
     "requirements_gathering",  ← Second occurrence (LOOP DETECTED)
     "requirements_review",
     ...
   ]
   ```

2. **Agent Re-invocation:** Same agent called multiple times
   ```
   RequirementsAgent (attempt 1) → RequirementsAgent (attempt 2)
   ```

3. **Metadata Counters:** Loop-specific metadata fields
   ```json
   {
     "requirements_iteration": 2,
     "phenotype_regeneration_attempt": 3,
     "extraction_retry_count": 1
   }
   ```

### Loop Performance Impact

| Loop Type | Additional States | Additional LLM Calls | Additional Cost | Additional Time |
|-----------|------------------|---------------------|----------------|----------------|
| Requirements Loop | +2 per iteration | +1-2 | $0.05-$0.10 | +1-2 min |
| Phenotype Loop | +2 per iteration | +1 | $0.03-$0.08 | +30-90 sec |
| QA Loop | +3 per iteration | 0 | $0 | +2-4 min (re-extraction) |

---

## Edge Case Path Traces

### Path 4.1: Error/Exception During Processing

**Trace Name:** `ResearchFlow_FullWorkflow`
**Final State:** Varies (state where error occurred)
**Status:** ❌ Failed

#### Trace Hierarchy (Example: LLM Timeout)

```
ResearchFlow_FullWorkflow (125,000ms) ❌ FAILED
├─ [1-2] [normal execution]
├─ [3] requirements_gathering (125,000ms) ❌ ERROR
│   └─ ChatAnthropic (125,000ms) ❌ TIMEOUT
│      Error: "APITimeoutError: Request timed out after 120000ms"
│      Stack trace: [full Python traceback]
└─ ERROR: Workflow failed at requirements_gathering
```

#### Error Types & Traces

**1. LLM API Timeout:**
```json
{
  "error": "ChatAnthropic timeout after 120s",
  "error_type": "APITimeoutError",
  "failed_at_state": "requirements_gathering",
  "llm_call_duration_ms": 120000
}
```

**2. Database Connection Failure:**
```json
{
  "error": "asyncpg.exceptions.PostgresConnectionError: connection refused",
  "error_type": "DatabaseError",
  "failed_at_state": "feasibility_validation"
}
```

**3. FHIR Server Unavailable:**
```json
{
  "error": "httpx.ConnectError: [Errno 111] Connection refused",
  "error_type": "ExternalServiceError",
  "failed_at_state": "data_extraction",
  "fhir_server_url": "http://localhost:8080/fhir"
}
```

#### Identifying Error Paths

**Filters:**
- Trace status: ❌ Failed
- `error` field is not null
- Very high duration (timeouts)
- Exception stack traces visible

**Search:**
```
Status: Failed
Contains: "Error" OR "Exception" OR "Timeout"
```

**Debugging Tips:**
1. Check LangSmith trace's **Exception** tab for full stack trace
2. Review **Logs** tab for error messages before failure
3. Check **Metadata** for `error_type` and `failed_at_state`
4. Verify external services (FHIR server, database) are running
5. Check LLM API rate limits and quotas

---

## Filtering & Searching Traces

### Common Filters

#### By Workflow Outcome
```
# Success paths only
Metadata: final_state = "complete"

# All failures
Metadata: final_state IN ["not_feasible", "qa_failed", "human_review"]

# Paused/waiting
Metadata: final_state IN ["requirements_gathering", "requirements_review", "phenotype_review", "extraction_approval", "qa_review"]
AND Metadata: requirements_approved = null
```

#### By Duration
```
# Fast executions (stub mode or highly optimized)
Duration: < 200ms

# Normal production
Duration: 60s - 600s

# Slow/problematic
Duration: > 600s
```

#### By Cost
```
# Low cost (minimal LLM usage)
Cost: < $0.05

# Normal production
Cost: $0.05 - $0.20

# High cost (many loops or complex conversations)
Cost: > $0.20
```

#### By Environment
```
# E2E tests
Tag: e2e-test

# Production
Tag: production

# By researcher
Metadata: researcher = "Dr. Sarah Chen"
```

### Advanced Searches

#### Find All Rejection Loops
```
Metadata: states_executed > 12
AND Duration: > 180s
```

#### Find Not Feasible Paths
```
Metadata: final_state = "not_feasible"
AND Metadata: estimated_cohort_size < 10
```

#### Find QA Failures
```
Metadata: final_state = "qa_failed"
AND Metadata: overall_status = "failed"
```

#### Find Long-Running Workflows
```
Duration: > 600s
Tag: production
```

---

## Debugging with Traces

### Scenario 1: Workflow Unexpectedly Terminates at `not_feasible`

**Steps:**
1. Find trace: `Metadata: final_state = "not_feasible"`
2. Expand `feasibility_validation` node
3. Check:
   - `estimated_cohort_size` - what was the count?
   - `phenotype_sql` - is SQL correct?
   - If PhenotypeAgent child trace exists:
     - Check LLM input: Were requirements passed correctly?
     - Check LLM output: What did it generate?
4. Run `phenotype_sql` manually against FHIR database to verify cohort size
5. Review `inclusion_criteria` and `exclusion_criteria` for overly restrictive rules

**Root Causes:**
- ✅ Requirements too restrictive (expected behavior)
- ❌ SQL generation error (bug in PhenotypeAgent)
- ❌ Empty FHIR database (environment issue)

---

### Scenario 2: Workflow Stuck in Requirements Loop (3+ Iterations)

**Steps:**
1. Find trace: `Contains: "requirements_gathering" (count: > 2)`
2. Expand each `requirements_gathering` iteration
3. Compare:
   - What changed between iterations?
   - What's the `completeness_score` progression?
   - What are the `missing_fields` in each iteration?
4. Check conversation history for researcher responses
5. If Requirements Agent child traces exist:
   - Check LLM input/output for each iteration
   - Verify prompts are guiding toward completion

**Root Causes:**
- ✅ Researcher providing incomplete answers (expected)
- ❌ Requirements Agent not extracting fields correctly (bug)
- ❌ Completeness threshold too high (configuration issue)

---

### Scenario 3: High LLM Costs (> $0.50 per workflow)

**Steps:**
1. Find expensive traces: `Cost: > $0.50`
2. Expand all child traces and sort by cost (highest first)
3. Identify bottleneck:
   - Which LLM call is most expensive?
   - Check input token count - is context too large?
   - Check output token count - is response too verbose?
4. Review:
   - Prompt templates - can they be shortened?
   - Conversation history - is it being truncated?
   - Model selection - using correct model tier?

**Optimization Tips:**
- ✅ Use cheaper models for non-critical tasks (Calendar, Delivery)
- ✅ Truncate long conversation histories (keep last 10 messages)
- ✅ Use structured outputs instead of verbose responses
- ✅ Cache frequently used prompts

---

### Scenario 4: Workflow Taking > 10 Minutes

**Steps:**
1. Find slow traces: `Duration: > 600s`
2. Expand full trace hierarchy
3. Sort child nodes by duration (longest first)
4. Identify bottleneck:
   - **If RequirementsAgent is slow:** Long LLM conversation, complex requirements
   - **If ExtractionAgent is slow:** Large data retrieval, slow FHIR server
   - **If QAAgent is slow:** Large dataset validation
5. Check for:
   - External service timeouts
   - Database query performance
   - Network latency

---

## Performance Benchmarks

### Expected Trace Metrics by Path

| Path | States | LLM Calls | Duration (Stub) | Duration (Prod) | Cost | Success Rate |
|------|--------|-----------|----------------|-----------------|------|--------------|
| Happy Path | 12 | 0-3 | 60-120ms | 2-3 min | $0.05-$0.15 | 30% |
| Requirements Loop (1x) | 14 | 2-5 | 100-180ms | 3-5 min | $0.15-$0.30 | 40% |
| Phenotype Loop (1x) | 13 | 1-4 | 80-150ms | 3-4 min | $0.10-$0.20 | 15% |
| QA Loop (1x) | 16 | 0-3 | 120-240ms | 4-6 min | $0.05-$0.15 | 10% |
| Multiple Loops | 15-20 | 4-8 | 200-720ms | 10-15 min | $0.20-$0.50 | 5% |
| Not Feasible | 5 | 1-2 | 40-60ms | 1-2 min | $0.03-$0.08 | 15% |
| QA Failed | 10 | 2-3 | 80-100ms | 4-6 min | $0.05-$0.15 | 3% |
| Human Review | 9 | 2-3 | 50-70ms | 2-3 min | $0.05-$0.10 | 2% |

**Notes:**
- Success rates are estimated based on typical production scenarios
- Stub durations are for E2E tests with no real LLM calls
- Production durations include real LLM calls and external service latency

---

## Summary: Trace Patterns at a Glance

### Quick Reference Table

| Trace Pattern | final_state | states_executed | Duration | Cost | Identification |
|---------------|-------------|----------------|----------|------|----------------|
| ✅ Happy Path | `complete` | 12 | < 3 min | $0.05-$0.15 | No loops, all approvals ✅ |
| ✅ Req Loop | `complete` | 14 | 3-5 min | $0.15-$0.30 | `requirements_gathering` × 2 |
| ✅ Pheno Loop | `complete` | 13 | 3-4 min | $0.10-$0.20 | `feasibility_validation` × 2 |
| ✅ QA Loop | `complete` | 16 | 4-6 min | $0.05-$0.15 | `data_extraction` × 2 |
| ⛔ Not Feasible | `not_feasible` | 5 | < 2 min | $0.03-$0.08 | `estimated_cohort_size: 0` |
| ⛔ QA Failed | `qa_failed` | 10 | 4-6 min | $0.05-$0.15 | `overall_status: "failed"` |
| ⛔ Human Review | `human_review` | 9 | 2-3 min | $0.05-$0.10 | `extraction_approved: false` |
| ⏸️ Req Pause | `requirements_gathering` | 2 | < 1 min | $0.02-$0.05 | `requirements_complete: false` |
| ⏸️ Approval Gate | `*_review`/`*_approval` | Varies | < 2 min | Varies | `*_approved: null` |
| ❌ Error | Varies | Varies | Timeout | Varies | Trace status: Failed |

---

## Next Steps

### For Production Monitoring
1. Set up **LangSmith Alerts** for:
   - Workflows stuck in loop (> 3 iterations)
   - High cost workflows (> $0.50)
   - Slow workflows (> 10 minutes)
   - Failure rate > 10%

2. Create **Custom Dashboards** for:
   - Path distribution (% of each path type)
   - Average duration by path
   - Cost trends over time
   - Success vs failure rates

3. **Weekly Review:**
   - Analyze most common failure paths
   - Identify optimization opportunities
   - Review high-cost workflows

---

**Updated:** 2025-10-27 | **Sprint:** 5 | **Status:** ✅ Complete
**Related Docs:**
- [LangSmith Dashboard Guide](LANGSMITH_DASHBOARD_GUIDE.md) - Basic usage
- [Sprint 5 Completion Summary](sprints/SPRINT_05_COMPLETION_SUMMARY.md) - Observability implementation
- [LangGraph Workflow](../app/langchain_orchestrator/langgraph_workflow.py) - Implementation
