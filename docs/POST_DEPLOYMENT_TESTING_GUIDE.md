# Post-Deployment Testing & Validation Guide

**Purpose**: Validate LangGraph migration deployment at each rollout phase
**Audience**: DevOps, SREs, Engineering leads
**Status**: Active - Updated Nov 10, 2025

---

## Table of Contents

1. [Overview](#overview)
2. [Smoke Tests (15 minutes)](#smoke-tests)
3. [Phase-Specific Validation](#phase-specific-validation)
4. [Rollback Decision Criteria](#rollback-decision-criteria)
5. [Success Metrics Dashboard](#success-metrics-dashboard)
6. [Incident Response](#incident-response)
7. [Appendix: SQL Queries](#appendix-sql-queries)

---

## Overview

This guide provides step-by-step validation procedures to run after each LangGraph rollout increment (10% → 25% → 50% → 100%).

### Rollout Schedule

| Phase | Percentage | Duration | Validation Window |
|-------|------------|----------|-------------------|
| **Canary** | 10% | Week 1 | Daily smoke tests + metrics |
| **Expand** | 25% | Week 2 | Twice-daily validation + comparison |
| **Majority** | 50% | Week 3 | Daily validation + load testing |
| **Full** | 100% | Week 4 | Final validation + cutover |

### Prerequisites

- Access to production environment
- LangSmith dashboard access (https://smith.langchain.com/)
- Database read access (PostgreSQL)
- Monitoring dashboards (Grafana/Prometheus if available)
- On-call rotation configured

---

## Smoke Tests

**Run Immediately After Each Deployment** (15 minutes total)

### Test 1: Submit Research Request via Researcher Portal (5 min)

**Objective**: Verify end-to-end workflow with LangGraph

**Steps**:
1. Navigate to Researcher Portal: http://localhost:8502 (or production URL)
2. Check feature flag status in UI:
   - Look for "🎲 Selected for LangGraph" or "🎲 Using legacy orchestrator" caption
   - Note the rollout percentage displayed
3. Submit a test request:
   ```
   Researcher Name: Test User (Deployment Validation)
   Email: devops+test@hospital.edu
   IRB Number: TEST-DEP-VALIDATION

   Request:
   "I need patient demographics and lab results for diabetic patients
   admitted in 2024 with HbA1c > 7.0. De-identified data only."
   ```
4. Verify request created:
   - Note the `request_id` (e.g., `REQ-20251110-ABC123`)
   - Check state = `new_request` or advanced

**Expected Result**:
- Request submitted successfully
- Request ID assigned
- Status displayed in UI
- No errors in browser console

**Rollback Trigger**: Request submission fails or errors occur

---

### Test 2: Verify LangSmith Trace (3 min)

**Objective**: Confirm observability is working

**Steps**:
1. Open LangSmith dashboard: https://smith.langchain.com/
2. Filter traces:
   - Project: `researchflow-production`
   - Time: Last 15 minutes
   - Search: Use the `request_id` from Test 1
3. Verify trace exists:
   - Workflow run should appear
   - Agent executions visible (if request progressed beyond new_request)
   - No error traces

**Expected Result**:
- Trace visible in LangSmith
- Workflow execution logged
- Trace includes request_id metadata

**Rollback Trigger**: No traces appear after 5 minutes

---

### Test 3: Check Database State Persistence (3 min)

**Objective**: Verify state saved to database

**Steps**:
1. Connect to database (PostgreSQL):
   ```bash
   psql -h localhost -U researchflow -d researchflow
   ```

2. Query for test request:
   ```sql
   SELECT
       id,
       current_state,
       researcher_name,
       created_at,
       updated_at
   FROM research_requests
   WHERE researcher_email = 'devops+test@hospital.edu'
   ORDER BY created_at DESC
   LIMIT 1;
   ```

3. Verify results:
   - Request exists in database
   - `current_state` matches UI display
   - `updated_at` is recent

**Expected Result**:
```
 id          | REQ-20251110-ABC123
 current_state | requirements_gathering (or other valid state)
 researcher_name | Test User (Deployment Validation)
 created_at    | 2025-11-10 10:30:00
 updated_at    | 2025-11-10 10:30:15
```

**Rollback Trigger**: No database record or state mismatch

---

### Test 4: Verify Approval Workflow (2 min)

**Objective**: Confirm approval gates working

**Steps**:
1. Navigate to Admin Dashboard: http://localhost:8503
2. Go to "Pending Approvals" tab
3. Check for test request (if it reached approval state)
4. If approval exists:
   - Verify request details displayed correctly
   - Verify approval type (requirements/phenotype/qa)
   - Click "Approve" and verify state transition

**Expected Result**:
- Approvals (if any) display correctly
- Approval actions update database
- No UI errors

**Rollback Trigger**: Approval workflow broken or approval actions fail

---

### Test 5: Test Rollback Procedure (2 min)

**Objective**: Verify ability to rollback if needed

**Steps**:
1. Check current rollout percentage:
   ```bash
   echo $LANGGRAPH_ROLLOUT_PCT
   ```

2. Temporarily disable LangGraph:
   ```bash
   export USE_LANGGRAPH_WORKFLOW=false
   # Restart Streamlit apps if needed
   ```

3. Submit another test request via Researcher Portal
4. Verify it uses legacy orchestrator (no "🎲 Selected for LangGraph" caption)

5. Re-enable LangGraph:
   ```bash
   export USE_LANGGRAPH_WORKFLOW=true
   export LANGGRAPH_ROLLOUT_PCT=10  # Or current phase percentage
   ```

**Expected Result**:
- Legacy orchestrator works when LangGraph disabled
- Feature flag toggles correctly
- No data loss or corruption

**Rollback Trigger**: Rollback procedure doesn't work

---

## Smoke Test Summary Checklist

Run after every deployment increment:

- [ ] Test 1: Research request submitted successfully
- [ ] Test 2: LangSmith trace visible
- [ ] Test 3: Database state persisted
- [ ] Test 4: Approval workflow functional
- [ ] Test 5: Rollback procedure verified

**Go/No-Go Decision**: All 5 tests must pass to proceed. If any test fails, investigate immediately and consider rollback.

---

## Phase-Specific Validation

### Phase 1: Canary Deployment (10% Rollout - Week 1)

**Frequency**: Daily validation (2x per day)

#### Metrics to Monitor

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Error Rate** | < 1% | LangSmith errors / total requests |
| **Success Rate** | > 99% | Successful workflows / total workflows |
| **Latency (p50)** | < 10% increase vs legacy | Workflow duration median |
| **Latency (p95)** | < 20% increase vs legacy | Workflow duration 95th percentile |
| **Checkpointer Working** | 100% | No "RuntimeError: threads can only be started once" |

#### Daily Validation Steps

**Morning Check (9am)**:
1. Run smoke tests (15 min)
2. Query LangSmith for overnight errors:
   ```python
   # LangSmith SDK
   from langsmith import Client

   client = Client()
   runs = client.list_runs(
       project_name="researchflow-production",
       start_time=datetime.now() - timedelta(hours=12),
       error=True  # Only error traces
   )

   for run in runs:
       print(f"ERROR: {run.id} - {run.error}")
   ```

3. Check database consistency:
   ```sql
   -- Count requests in each state (should have no stuck requests)
   SELECT current_state, COUNT(*) as count
   FROM research_requests
   WHERE created_at > NOW() - INTERVAL '24 hours'
   GROUP BY current_state
   ORDER BY count DESC;
   ```

4. Review monitoring dashboard (if available)

**Evening Check (5pm)**:
1. Run smoke tests again
2. Compare LangGraph vs legacy metrics:
   ```sql
   -- LangGraph request count
   SELECT COUNT(*) as langgraph_count
   FROM research_requests
   WHERE created_at > NOW() - INTERVAL '24 hours'
   AND (
       -- Identify LangGraph requests by checking for persistence
       updated_at > created_at + INTERVAL '1 second'
   );

   -- Legacy request count
   SELECT COUNT(*) as legacy_count
   FROM research_requests
   WHERE created_at > NOW() - INTERVAL '24 hours'
   AND updated_at <= created_at + INTERVAL '1 second';
   ```

3. Review approval workflow metrics:
   ```sql
   SELECT
       approval_type,
       status,
       COUNT(*) as count
   FROM approvals
   WHERE created_at > NOW() - INTERVAL '24 hours'
   GROUP BY approval_type, status;
   ```

#### Week 1 End-of-Week Review

**Friday 4pm**: Hold go/no-go meeting for Phase 2 (25% rollout)

**Decision Criteria**:
- ✅ Error rate < 1% for 7 consecutive days
- ✅ No P0/P1 incidents related to LangGraph
- ✅ Latency within acceptable range (< 10% degradation)
- ✅ All smoke tests passing daily
- ✅ Team confident in monitoring and rollback procedures

**If GO**: Proceed to Phase 2 (25% rollout) Monday morning
**If NO-GO**: Investigate issues, fix, and continue at 10% for another week

---

### Phase 2: Expand Deployment (25% Rollout - Week 2)

**Frequency**: Twice-daily validation + statistical comparison

#### Additional Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Data Integrity** | 100% | Compare final states (LangGraph vs legacy) |
| **Approval Accuracy** | 100% | No missed approval gates |
| **Performance Regression** | < 10% | Statistical comparison of latencies |

#### Daily Validation Steps

**Morning & Evening**:
1. Run smoke tests (15 min)
2. Statistical comparison query:
   ```sql
   -- Compare success rates by orchestrator type
   WITH langgraph_requests AS (
       SELECT
           COUNT(*) FILTER (WHERE current_state IN ('complete', 'delivered')) as success,
           COUNT(*) as total
       FROM research_requests
       WHERE created_at > NOW() - INTERVAL '24 hours'
       AND updated_at > created_at + INTERVAL '1 second'  -- LangGraph indicator
   ),
   legacy_requests AS (
       SELECT
           COUNT(*) FILTER (WHERE current_state IN ('complete', 'delivered')) as success,
           COUNT(*) as total
       FROM research_requests
       WHERE created_at > NOW() - INTERVAL '24 hours'
       AND updated_at <= created_at + INTERVAL '1 second'  -- Legacy indicator
   )
   SELECT
       'LangGraph' as type,
       success,
       total,
       ROUND(100.0 * success / NULLIF(total, 0), 2) as success_rate
   FROM langgraph_requests
   UNION ALL
   SELECT
       'Legacy' as type,
       success,
       total,
       ROUND(100.0 * success / NULLIF(total, 0), 2) as success_rate
   FROM legacy_requests;
   ```

3. Data integrity check:
   ```sql
   -- Find any requests with missing state transitions
   SELECT r.id, r.current_state, COUNT(a.id) as approval_count
   FROM research_requests r
   LEFT JOIN approvals a ON r.id = a.request_id
   WHERE r.created_at > NOW() - INTERVAL '24 hours'
   GROUP BY r.id, r.current_state
   HAVING
       (r.current_state IN ('phenotype_approval', 'extraction_approval', 'qa_approval')
        AND COUNT(a.id) = 0)  -- Should have at least one approval if in approval state
   ;
   ```

#### Week 2 Mid-Week Check (Wednesday)

**Review**:
- Error trends (should be stable or decreasing)
- Performance comparison (LangGraph should be within 10% of legacy)
- User feedback (check for any complaints or issues)

**If issues found**: Consider pausing rollout, investigate, and fix before proceeding

#### Week 2 End-of-Week Review

**Friday 4pm**: Hold go/no-go meeting for Phase 3 (50% rollout)

**Decision Criteria**:
- ✅ Success rate parity with legacy (within 1%)
- ✅ Performance within 10% of legacy
- ✅ No data integrity issues
- ✅ No approval workflow failures
- ✅ LangSmith observability providing value (debugging, monitoring)

**If GO**: Proceed to Phase 3 (50% rollout) Monday morning
**If NO-GO**: Rollback to 10% or pause for investigation

---

### Phase 3: Majority Deployment (50% Rollout - Week 3)

**Frequency**: Daily validation + load testing

#### Additional Testing

| Test | Frequency | Purpose |
|------|-----------|---------|
| **Load Testing** | Once (mid-week) | Verify concurrent request handling |
| **Long-Running Workflow** | Daily | Validate multi-hour workflows |
| **Service Restart** | Once | Verify state persistence after restart |

#### Daily Validation Steps

**Morning**:
1. Run smoke tests
2. Check for long-running workflows:
   ```sql
   -- Workflows running > 2 hours
   SELECT
       id,
       current_state,
       researcher_name,
       created_at,
       EXTRACT(EPOCH FROM (NOW() - created_at))/3600 as hours_running
   FROM research_requests
   WHERE created_at < NOW() - INTERVAL '2 hours'
   AND current_state NOT IN ('complete', 'delivered', 'error', 'escalated')
   ORDER BY created_at;
   ```

3. Verify state transitions:
   ```sql
   -- Check state transition velocity (should complete within SLA)
   SELECT
       AVG(EXTRACT(EPOCH FROM (updated_at - created_at))/60) as avg_minutes_to_first_update
   FROM research_requests
   WHERE created_at > NOW() - INTERVAL '24 hours'
   AND updated_at > created_at;
   ```

#### Load Testing (Wednesday Mid-Week)

**Objective**: Verify system handles 10+ concurrent requests

**Steps**:
1. Create load test script:
   ```python
   import asyncio
   import httpx
   from datetime import datetime

   async def submit_request(client, request_num):
       """Submit a single test request"""
       response = await client.post(
           "http://localhost:8000/api/v1/requests",
           json={
               "researcher_name": f"Load Test User {request_num}",
               "researcher_email": f"loadtest+{request_num}@hospital.edu",
               "researcher_request": "Test request for load testing",
               "researcher_info": {
                   "department": "Load Testing",
                   "irb_number": f"TEST-LOAD-{request_num}"
               }
           }
       )
       return response.json()

   async def run_load_test(num_requests=10):
       """Submit multiple concurrent requests"""
       async with httpx.AsyncClient() as client:
           tasks = [submit_request(client, i) for i in range(num_requests)]
           results = await asyncio.gather(*tasks)
           return results

   # Run test
   results = asyncio.run(run_load_test(10))
   print(f"Submitted {len(results)} requests")
   ```

2. Monitor system during load test:
   - CPU usage
   - Memory usage
   - Database connections
   - Response times

3. Verify all requests processed:
   ```sql
   SELECT COUNT(*)
   FROM research_requests
   WHERE researcher_email LIKE 'loadtest+%@hospital.edu'
   AND created_at > NOW() - INTERVAL '1 hour';
   ```

**Expected Result**: All 10 requests submitted and processed without errors

#### Service Restart Test (Friday)

**Objective**: Verify state persistence survives service restart

**Steps**:
1. Submit test request and note `request_id`
2. Wait for request to advance to `requirements_gathering` or beyond
3. Restart Streamlit apps:
   ```bash
   pkill -f "streamlit run"
   streamlit run app/web_ui/researcher_portal.py --server.port 8502 &
   streamlit run app/web_ui/admin_dashboard.py --server.port 8503 &
   ```

4. Wait 30 seconds for apps to restart
5. Check request status in Admin Dashboard
6. Verify state preserved and workflow continues

**Expected Result**: Request state persisted, workflow resumes after restart

#### Week 3 End-of-Week Review

**Friday 4pm**: Hold go/no-go meeting for Phase 4 (100% rollout)

**Decision Criteria**:
- ✅ Load testing passed (10+ concurrent requests)
- ✅ Long-running workflows completing successfully
- ✅ State persistence verified after restart
- ✅ Performance stable at 50% traffic
- ✅ No escalated incidents

**If GO**: Proceed to Phase 4 (100% rollout) Monday morning
**If NO-GO**: Rollback to 25% or pause for investigation

---

### Phase 4: Full Deployment (100% Rollout - Week 4)

**Frequency**: Daily validation for first 3 days, then normal monitoring

#### Final Validation Steps

**Monday (100% Cutover Day)**:
1. 8am: Update environment variable:
   ```bash
   export LANGGRAPH_ROLLOUT_PCT=100
   ```

2. 9am: Run comprehensive smoke tests
3. 10am: Monitor for 1 hour, check every 10 minutes
4. 12pm: Verify no legacy requests being created:
   ```sql
   SELECT COUNT(*)
   FROM research_requests
   WHERE created_at > NOW() - INTERVAL '3 hours'
   AND updated_at <= created_at + INTERVAL '1 second';  -- Should be 0
   ```

5. 3pm: Run load test (20 concurrent requests)
6. 5pm: End-of-day review meeting

**Tuesday-Wednesday**:
- Continue daily smoke tests
- Monitor for any regressions
- Review LangSmith traces for errors

**Thursday (Archive Legacy Orchestrator)**:
1. Verify 72 hours of stable operation
2. Archive legacy orchestrator code:
   ```bash
   git mv app/orchestrator app/legacy/orchestrator
   git commit -m "chore: archive legacy orchestrator after 100% LangGraph rollout"
   ```

3. Update documentation to reflect LangGraph as primary
4. Remove feature flag logic (optional - can keep for future use)

**Friday (Declare Migration Complete)**:
- Final review meeting
- Update project status to "Migration Complete"
- Send stakeholder communication
- Celebrate! 🎉

---

## Rollback Decision Criteria

**Rollback Immediately If**:

### Critical (P0) Triggers
- **Data Loss Detected**: Any evidence of data corruption or lost requests
- **Complete System Failure**: LangGraph causing system-wide outages
- **Security Breach**: LangGraph exposing sensitive data
- **Regulatory Compliance Issue**: PHI handling violations

### High Priority (P1) Triggers
- **Error Rate > 5%**: Sustained for > 30 minutes
- **Approval Workflow Blocked**: Users unable to approve requests
- **Data Corruption**: Inconsistent state across database and checkpointer
- **Performance Degradation > 50%**: Latency more than double legacy

### Medium Priority (P2) Triggers (Pause, Don't Rollback)
- **Error Rate 1-5%**: Sustained for > 1 hour
- **Performance Degradation 20-50%**: Investigate before rollback
- **Intermittent Failures**: < 10 failures per day
- **LangSmith Unavailable**: Observability issue, not workflow issue

### Rollback Procedure

**Execute Within 5 Minutes**:

1. **Disable LangGraph**:
   ```bash
   export USE_LANGGRAPH_WORKFLOW=false
   export LANGGRAPH_ROLLOUT_PCT=0
   ```

2. **Restart Services**:
   ```bash
   ./scripts/restart_apps.sh  # Restart Streamlit apps
   ```

3. **Verify Legacy Orchestrator Active**:
   - Submit test request
   - Verify no "🎲 Selected for LangGraph" caption
   - Check request processing with legacy orchestrator

4. **Communicate Rollback**:
   - Notify on-call team
   - Update incident ticket
   - Email stakeholders (if P0/P1)

5. **Investigate Root Cause**:
   - Check LangSmith traces for errors
   - Review application logs
   - Query database for anomalies
   - Create post-mortem document

---

## Success Metrics Dashboard

### Real-Time Monitoring Queries

#### 1. Request Volume by Orchestrator

```sql
SELECT
    CASE
        WHEN updated_at > created_at + INTERVAL '1 second' THEN 'LangGraph'
        ELSE 'Legacy'
    END as orchestrator,
    COUNT(*) as request_count,
    COUNT(*) FILTER (WHERE current_state IN ('complete', 'delivered')) as successful,
    COUNT(*) FILTER (WHERE current_state = 'error') as errors,
    ROUND(AVG(EXTRACT(EPOCH FROM (updated_at - created_at))), 2) as avg_duration_sec
FROM research_requests
WHERE created_at > NOW() - INTERVAL '1 hour'
GROUP BY orchestrator;
```

#### 2. LangSmith Error Traces (Last Hour)

```python
from langsmith import Client
from datetime import datetime, timedelta

client = Client()
errors = client.list_runs(
    project_name="researchflow-production",
    start_time=datetime.now() - timedelta(hours=1),
    error=True
)

print(f"Errors in last hour: {len(list(errors))}")
for run in errors:
    print(f"  - {run.id}: {run.error}")
```

#### 3. State Distribution

```sql
SELECT
    current_state,
    COUNT(*) as count,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) as percentage
FROM research_requests
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY current_state
ORDER BY count DESC;
```

#### 4. Approval Workflow Health

```sql
SELECT
    approval_type,
    status,
    COUNT(*) as count,
    AVG(EXTRACT(EPOCH FROM (reviewed_at - created_at))/60) as avg_review_time_minutes
FROM approvals
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY approval_type, status;
```

#### 5. Performance Percentiles

```sql
SELECT
    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (updated_at - created_at))) as p50_seconds,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (updated_at - created_at))) as p95_seconds,
    PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (updated_at - created_at))) as p99_seconds
FROM research_requests
WHERE created_at > NOW() - INTERVAL '1 hour'
AND updated_at > created_at;
```

### Dashboard Setup (Optional)

If using Grafana/Prometheus:

**Metrics to Track**:
- Request rate (requests/minute)
- Error rate (errors/total requests)
- Latency distribution (p50, p95, p99)
- Orchestrator distribution (LangGraph % vs Legacy %)
- Database query performance
- LangSmith trace count

---

## Incident Response

### Escalation Path

| Severity | Response Time | Escalation |
|----------|---------------|------------|
| **P0** (Critical) | Immediate | On-call engineer + Engineering lead + VP Eng |
| **P1** (High) | < 30 min | On-call engineer + Engineering lead |
| **P2** (Medium) | < 2 hours | On-call engineer |
| **P3** (Low) | Next business day | Engineering team |

### Communication Templates

#### P0/P1 Incident Email

**Subject**: [P0/P1] LangGraph Migration Issue - [Brief Description]

**Body**:
```
INCIDENT SUMMARY
----------------
Severity: P0 / P1
Started: [Timestamp]
Status: Investigating / Mitigating / Resolved
Impact: [Brief description]

CURRENT STATUS
--------------
[Current state of the incident]

MITIGATION STEPS
----------------
1. [Step 1]
2. [Step 2]
...

ROLLBACK STATUS
---------------
[ ] Rollback initiated
[ ] Rollback completed
[ ] System verified

NEXT UPDATE
-----------
Next update in [X] minutes at [Time]

CONTACT
-------
On-call engineer: [Name] - [Contact]
```

#### Daily Status Update (Week 1-4)

**Subject**: LangGraph Migration - Daily Status - Week [X] Day [Y]

**Body**:
```
ROLLOUT STATUS
--------------
Current Phase: [10% / 25% / 50% / 100%]
Rollout Date: [Date]
Days at Current Phase: [X]

SMOKE TESTS
-----------
[✅/❌] Test 1: Research request submitted
[✅/❌] Test 2: LangSmith trace visible
[✅/❌] Test 3: Database state persisted
[✅/❌] Test 4: Approval workflow functional
[✅/❌] Test 5: Rollback procedure verified

METRICS (Last 24 Hours)
-----------------------
Total Requests: [X] (LangGraph: [Y], Legacy: [Z])
Success Rate: [X]% (Target: > 99%)
Error Rate: [X]% (Target: < 1%)
Avg Latency: [X]s (Target: < 10% increase vs legacy)

ISSUES
------
[None / List of issues and resolution status]

NEXT STEPS
----------
[Plan for tomorrow]
```

### Post-Incident Review Template

**Document**: `docs/incidents/INCIDENT_[DATE]_[TITLE].md`

```markdown
# Incident Report: [Title]

## Summary
- **Date**: [Date]
- **Duration**: [Start] - [End]
- **Severity**: P0 / P1 / P2
- **Impact**: [Description]

## Timeline
- **[Time]**: Incident detected
- **[Time]**: Investigation started
- **[Time]**: Root cause identified
- **[Time]**: Mitigation deployed
- **[Time]**: Incident resolved

## Root Cause
[Detailed description of what caused the incident]

## Resolution
[How the incident was resolved]

## Prevention
[Steps to prevent similar incidents in the future]

## Action Items
- [ ] [Action 1] - Owner: [Name] - Due: [Date]
- [ ] [Action 2] - Owner: [Name] - Due: [Date]
```

---

## Appendix: SQL Queries

### A. Find All LangGraph Requests

```sql
SELECT
    id,
    researcher_name,
    current_state,
    created_at,
    updated_at
FROM research_requests
WHERE updated_at > created_at + INTERVAL '1 second'  -- LangGraph indicator
ORDER BY created_at DESC
LIMIT 100;
```

### B. Compare LangGraph vs Legacy Performance

```sql
WITH performance_comparison AS (
    SELECT
        CASE
            WHEN updated_at > created_at + INTERVAL '1 second' THEN 'LangGraph'
            ELSE 'Legacy'
        END as orchestrator,
        EXTRACT(EPOCH FROM (updated_at - created_at)) as duration_seconds
    FROM research_requests
    WHERE created_at > NOW() - INTERVAL '24 hours'
    AND updated_at > created_at
)
SELECT
    orchestrator,
    COUNT(*) as sample_size,
    ROUND(AVG(duration_seconds), 2) as avg_duration,
    ROUND(PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY duration_seconds), 2) as p50,
    ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_seconds), 2) as p95,
    ROUND(PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY duration_seconds), 2) as p99
FROM performance_comparison
GROUP BY orchestrator;
```

### C. Find Stuck Workflows

```sql
SELECT
    id,
    current_state,
    researcher_name,
    created_at,
    EXTRACT(EPOCH FROM (NOW() - updated_at))/60 as minutes_since_update
FROM research_requests
WHERE current_state NOT IN ('complete', 'delivered', 'error', 'escalated')
AND updated_at < NOW() - INTERVAL '2 hours'
ORDER BY updated_at;
```

### D. Approval Workflow Audit

```sql
SELECT
    r.id as request_id,
    r.current_state,
    a.approval_type,
    a.status as approval_status,
    a.reviewed_by,
    a.reviewed_at
FROM research_requests r
LEFT JOIN approvals a ON r.id = a.request_id
WHERE r.created_at > NOW() - INTERVAL '24 hours'
ORDER BY r.created_at DESC;
```

### E. Error Rate Trending

```sql
SELECT
    DATE_TRUNC('hour', created_at) as hour,
    COUNT(*) as total_requests,
    COUNT(*) FILTER (WHERE current_state = 'error') as errors,
    ROUND(100.0 * COUNT(*) FILTER (WHERE current_state = 'error') / COUNT(*), 2) as error_rate_pct
FROM research_requests
WHERE created_at > NOW() - INTERVAL '7 days'
GROUP BY DATE_TRUNC('hour', created_at)
ORDER BY hour DESC;
```

---

## Conclusion

This guide provides comprehensive validation procedures for each phase of the LangGraph rollout. The key to success is:

1. **Run smoke tests after every deployment** (15 min investment for confidence)
2. **Monitor metrics daily** (especially error rate and performance)
3. **Don't hesitate to rollback** if metrics degrade
4. **Communicate status regularly** (daily updates during rollout)
5. **Document incidents** for continuous improvement

For questions or issues, contact:
- On-call engineer: [PagerDuty rotation]
- Engineering lead: [Name]
- Documentation: See `docs/LANGGRAPH_MIGRATION_GUIDE.md`

**Last Updated**: November 10, 2025
