# Human-in-Loop Approval Workflow Guide

**Version**: 1.0
**Date**: October 2025
**Status**: Implementation Complete

---

## Overview

The Human-in-Loop Approval Workflow adds critical checkpoints where informaticians and administrators must review and approve requests before the workflow continues. This mirrors real-world clinical research processes where expert validation is required.

### Key Approval Gates

1. **Requirements Review** - Informatician validates medical accuracy of extracted requirements
2. **Phenotype SQL Review** - **CRITICAL** - Informatician approves SQL before execution
3. **Extraction Approval** - Admin approves data extraction to begin
4. **QA Review** - Informatician validates quality assurance results
5. **Scope Change Review** - All stakeholders review mid-workflow requirement changes

---

## Workflow States

### Approval States

| State | Description | Reviewer | Timeout |
|-------|-------------|----------|---------|
| `REQUIREMENTS_REVIEW` | Waiting for informatician to review requirements | Informatician | 24 hours |
| `PHENOTYPE_REVIEW` | Waiting for informatician to approve SQL query | Informatician | 24 hours |
| `EXTRACTION_APPROVAL` | Waiting for approval to extract data | Admin | 12 hours |
| `QA_REVIEW` | Waiting for informatician to approve QA results | Informatician | 24 hours |
| `SCOPE_CHANGE` | Scope change requested, waiting for review | Admin/Informatician | 48 hours |

### Approval Statuses

- `pending` - Awaiting review
- `approved` - Approved, workflow continues
- `rejected` - Rejected, returns to originating agent
- `modified` - Approved with modifications
- `timeout` - Approval timed out, escalated

---

## API Endpoints

### 1. Get Pending Approvals

```bash
GET /approvals/pending?approval_type=phenotype_sql
```

**Response:**
```json
{
 "count": 2,
 "approvals": [
 {
 "id": 1,
 "request_id": "REQ-20251011-ABC123",
 "approval_type": "phenotype_sql",
 "submitted_at": "2025-10-11T10:30:00",
 "submitted_by": "phenotype_agent",
 "timeout_at": "2025-10-12T10:30:00",
 "approval_data": {
 "sql_query": "SELECT ...",
 "estimated_cohort": 150,
 "feasibility_score": 0.85
 }
 }
 ]
}
```

### 2. Get Specific Approval

```bash
GET /approvals/{approval_id}
```

**Response:**
```json
{
 "id": 1,
 "request_id": "REQ-20251011-ABC123",
 "approval_type": "phenotype_sql",
 "status": "pending",
 "submitted_at": "2025-10-11T10:30:00",
 "approval_data": {
 "sql_query": "SELECT patient_id, birth_date FROM patient WHERE ...",
 "estimated_cohort": 150,
 "warnings": [],
 "recommendations": []
 }
}
```

### 3. Approve Request

```bash
POST /approvals/{approval_id}/respond
{
 "decision": "approve",
 "reviewer": "informatician@hospital.org",
 "notes": "SQL query validated and approved"
}
```

**Response:**
```json
{
 "success": true,
 "message": "Approval 1 approved by informatician@hospital.org",
 "approval_id": 1,
 "decision": "approve"
}
```

### 4. Reject Request

```bash
POST /approvals/{approval_id}/respond
{
 "decision": "reject",
 "reviewer": "informatician@hospital.org",
 "notes": "SQL query has syntax error in WHERE clause"
}
```

**Workflow Effect**: Returns to phenotype_agent to regenerate SQL

### 5. Modify and Approve

```bash
POST /approvals/{approval_id}/respond
{
 "decision": "modify",
 "reviewer": "informatician@hospital.org",
 "notes": "Updated SQL to use proper date format",
 "modifications": {
 "sql_query": "SELECT patient_id, birth_date FROM patient WHERE birth_date >= '2000-01-01'"
 }
}
```

**Workflow Effect**: Continues with modified SQL

### 6. Request Scope Change

```bash
POST /approvals/scope-change
{
 "request_id": "REQ-20251011-ABC123",
 "requested_by": "researcher@hospital.org",
 "requested_changes": {
 "inclusion_criteria": ["Add diabetes type 2 diagnosis"],
 "time_period": {
 "start": "2020-01-01",
 "end": "2024-12-31"
 }
 },
 "reason": "Need to expand cohort for statistical power"
}
```

**Response:**
```json
{
 "success": true,
 "message": "Scope change request submitted for approval",
 "approval_id": 5,
 "request_id": "REQ-20251011-ABC123",
 "impact_analysis": {
 "severity": "high",
 "requires_rework": true,
 "restart_from_state": "requirements_gathering",
 "estimated_delay_hours": 24,
 "affected_components": ["phenotype", "extraction", "qa"]
 }
}
```

### 7. Check Approval Timeouts

```bash
POST /approvals/check-timeouts
```

**Response:**
```json
{
 "success": true,
 "timed_out_count": 1,
 "timed_out_approvals": [
 {
 "id": 3,
 "request_id": "REQ-20251010-XYZ789",
 "approval_type": "phenotype_sql",
 "timeout_at": "2025-10-11T09:00:00",
 "escalation_id": 12
 }
 ]
}
```

**Effect**: Creates escalation records for timed out approvals

---

## NOTE: Usage Examples

### Example 1: SQL Review Workflow

```python
# 1. Phenotype agent generates SQL and requests approval
# State changes to PHENOTYPE_REVIEW

# 2. Get pending SQL approvals
import requests

response = requests.get(
 "http://localhost:8000/approvals/pending?approval_type=phenotype_sql"
)
approvals = response.json()['approvals']

# 3. Informatician reviews and approves
approval_id = approvals[0]['id']
sql_query = approvals[0]['approval_data']['sql_query']

# Review SQL...
# If good, approve:
requests.post(
 f"http://localhost:8000/approvals/{approval_id}/respond",
 json={
 "decision": "approve",
 "reviewer": "dr.smith@hospital.org",
 "notes": "Query validated against schema"
 }
)

# 4. Workflow automatically continues to calendar_agent
```

### Example 2: Scope Change Request

```python
# Researcher wants to modify requirements mid-workflow

requests.post(
 "http://localhost:8000/approvals/scope-change",
 json={
 "request_id": "REQ-20251011-ABC123",
 "requested_by": "researcher@hospital.org",
 "requested_changes": {
 "inclusion_criteria": [
 "Patients with diabetes type 2",
 "Age >= 50" # NEW: Added age criterion
 ]
 },
 "reason": "IRB requested age restriction"
 }
)

# Coordinator agent analyzes impact
# Creates scope_change approval
# Sends notifications to all stakeholders
# Waits for approval before modifying requirements
```

### Example 3: Rejection and Rework

```python
# Informatician rejects SQL due to error

requests.post(
 f"http://localhost:8000/approvals/{approval_id}/respond",
 json={
 "decision": "reject",
 "reviewer": "dr.smith@hospital.org",
 "notes": "SQL is missing time period filter. Please regenerate with date constraints."
 }
)

# Workflow automatically:
# 1. Routes back to phenotype_agent
# 2. Provides rejection reason in context
# 3. Agent regenerates SQL with feedback
# 4. Requests approval again
```

---

## Approval Data Structures

### Requirements Approval Data

```json
{
 "structured_requirements": {
 "study_title": "Diabetes Type 2 Study",
 "inclusion_criteria": [...],
 "exclusion_criteria": [...],
 "data_elements": ["demographics", "lab_results"]
 },
 "completeness_score": 0.92,
 "conversation_history": [...]
}
```

### Phenotype SQL Approval Data

```json
{
 "sql_query": "SELECT ...",
 "estimated_cohort": 150,
 "feasibility_score": 0.85,
 "data_availability": {
 "overall_availability": 0.90,
 "by_element": {...}
 },
 "warnings": [
 {
 "type": "small_cohort",
 "message": "Estimated cohort (150) smaller than requested minimum (200)"
 }
 ],
 "recommendations": []
}
```

### Scope Change Approval Data

```json
{
 "requested_changes": {
 "inclusion_criteria": ["Add diabetes type 2 diagnosis"]
 },
 "reason": "Need to expand cohort",
 "impact_analysis": {
 "severity": "high",
 "requires_rework": true,
 "restart_from_state": "requirements_gathering",
 "estimated_delay_hours": 24,
 "affected_components": ["phenotype", "extraction", "qa"]
 }
}
```

---

## Email Notifications

The Coordinator Agent sends email notifications at each approval stage:

### 1. Requirements Review Email

**Subject**: Requirements Review Needed - REQ-20251011-ABC123
**To**: Informatician
**Content**: Link to admin dashboard, requirements summary

### 2. SQL Review Email

**Subject**: SQL Query Review Needed - REQ-20251011-ABC123
**To**: Informatician
**Content**: SQL query, estimated cohort, warnings, dashboard link

### 3. Scope Change Notification

**Subject**: Scope Change Request - REQ-20251011-ABC123
**To**: Informatician, Admin, Researcher
**Content**: Original vs. new requirements, impact analysis, approval link

---

## ⏱ Timeout Handling

### Automatic Timeout Detection

A scheduled job should call `/approvals/check-timeouts` every hour to:

1. Identify approvals past their timeout deadline
2. Mark them as `timeout` status
3. Create escalation records with severity "high"
4. Notify admins for immediate action

### Timeout Configuration

Configured in `WorkflowEngine.get_approval_timeout_hours()`:

```python
{
 "requirements": 24, # 24 hours
 "phenotype_sql": 24, # 24 hours (CRITICAL)
 "extraction": 12, # 12 hours
 "qa": 24, # 24 hours
 "scope_change": 48 # 48 hours
}
```

---

## Security Considerations

1. **Authentication**: All approval endpoints should require authentication
2. **Authorization**: Verify reviewer has appropriate role (informatician/admin)
3. **Audit Trail**: All approval decisions logged to `audit_logs` table
4. **SQL Validation**: Phenotype SQL must be reviewed before execution
5. **Email Verification**: Verify reviewer email matches authenticated user

---

## 🧪 Testing Approval Workflow

### Test Script

```python
import requests
import time

BASE_URL = "http://localhost:8000"

# 1. Start a request (triggers requirements extraction)
# ... (use orchestrator)

# 2. Wait for requirements review approval
while True:
 response = requests.get(f"{BASE_URL}/approvals/pending?approval_type=requirements")
 approvals = response.json()['approvals']

 if approvals:
 approval_id = approvals[0]['id']

 # 3. Approve requirements
 requests.post(
 f"{BASE_URL}/approvals/{approval_id}/respond",
 json={
 "decision": "approve",
 "reviewer": "test@example.com",
 "notes": "Test approval"
 }
 )
 break

 time.sleep(5)

# 4. Wait for SQL review approval
while True:
 response = requests.get(f"{BASE_URL}/approvals/pending?approval_type=phenotype_sql")
 approvals = response.json()['approvals']

 if approvals:
 approval_id = approvals[0]['id']
 sql_query = approvals[0]['approval_data']['sql_query']

 print(f"SQL Query to review: {sql_query}")

 # 5. Approve SQL
 requests.post(
 f"{BASE_URL}/approvals/{approval_id}/respond",
 json={
 "decision": "approve",
 "reviewer": "informatician@example.com",
 "notes": "SQL validated"
 }
 )
 break

 time.sleep(5)

# Workflow continues automatically...
```

---

## Related Documentation

- [Enhancement Roadmap](HUMAN_IN_LOOP_ENHANCEMENT_ROADMAP.md) - Full implementation plan
- [Coordinator Agent Guide](COORDINATOR_AGENT_GUIDE.md) - Email and scope change coordination
- [Gap Analysis](GAP_ANALYSIS_AND_ROADMAP.md) - Original gap identification
- [API Examples](API_EXAMPLES.md) - Additional API usage examples

---

## [x] Best Practices

### For Informaticians

1. **SQL Review Checklist**:
 - [x] Verify SQL syntax is correct
 - [x] Check date filters are appropriate
 - [x] Validate cohort size is reasonable
 - [x] Review joins and data element selections
 - [x] Ensure no sensitive fields exposed

2. **Requirements Review**:
 - [x] Verify medical terminology is correct
 - [x] Check inclusion/exclusion criteria are clear
 - [x] Validate time periods are appropriate
 - [x] Confirm data elements are available

### For Admins

1. **Scope Change Review**:
 - [x] Review impact analysis
 - [x] Verify researcher has authority to request change
 - [x] Check if delay is acceptable
 - [x] Coordinate with informatician if medical validation needed

2. **Timeout Management**:
 - [x] Monitor timeout escalations daily
 - [x] Follow up on pending approvals approaching timeout
 - [x] Escalate to management if approvals blocked

---

**Last Updated**: October 2025
**Maintainer**: Development Team
