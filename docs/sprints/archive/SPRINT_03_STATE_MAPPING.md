# Sprint 3: State Mapping Analysis

**Date:** 2025-10-25
**Purpose:** Map custom workflow_engine.py states to LangGraph StateGraph structure

---

## Current Workflow States (23 total)

### Main Workflow Path (15 states)
1. **NEW_REQUEST** → Entry point
2. **REQUIREMENTS_GATHERING** → Requirements Agent gathering requirements
3. **REQUIREMENTS_COMPLETE** → Requirements gathered (deprecated - using REQUIREMENTS_REVIEW now)
4. **FEASIBILITY_VALIDATION** → Phenotype Agent validating feasibility
5. **FEASIBLE** → Feasibility validated
6. **SCHEDULE_KICKOFF** → Calendar Agent scheduling meeting
7. **KICKOFF_COMPLETE** → Meeting scheduled
8. **DATA_EXTRACTION** → Extraction Agent extracting data
9. **EXTRACTION_COMPLETE** → Data extracted
10. **QA_VALIDATION** → QA Agent validating quality
11. **QA_PASSED** → QA passed
12. **DATA_DELIVERY** → Delivery Agent delivering data
13. **DELIVERED** → Data delivered
14. **COMPLETE** → Workflow complete
15. **FAILED** → Workflow failed

### Approval Gates (5 states) - NEW in Human-in-Loop Enhancement
16. **REQUIREMENTS_REVIEW** → Wait for requirements approval
17. **PHENOTYPE_REVIEW** → Wait for SQL query approval
18. **EXTRACTION_APPROVAL** → Wait for extraction approval
19. **QA_REVIEW** → Wait for QA approval
20. **SCOPE_CHANGE** → Wait for scope change approval

### Error/Terminal States (3 states)
21. **NOT_FEASIBLE** → Cohort too small or infeasible
22. **QA_FAILED** → QA failed, needs human review
23. **HUMAN_REVIEW** → Escalated to human review

---

## Workflow Transition Rules (12 rules)

### 1. Requirements Gathering → Requirements Review
- **Trigger:** `requirements_agent.gather_requirements`
- **Condition:** `requirements_complete == True`
- **Next State:** `REQUIREMENTS_REVIEW` (approval gate)
- **Next Agent:** None (waits for human approval)

### 2. Requirements Approved → Feasibility Validation
- **Trigger:** `approval_service.approve_requirements`
- **Condition:** `approved == True`
- **Next State:** `FEASIBILITY_VALIDATION`
- **Next Agent:** `phenotype_agent`
- **Next Task:** `validate_feasibility`

### 3. Requirements Rejected → Requirements Gathering
- **Trigger:** `approval_service.reject_requirements`
- **Condition:** `approved == False`
- **Next State:** `REQUIREMENTS_GATHERING`
- **Next Agent:** `requirements_agent`
- **Next Task:** `gather_requirements`

### 4. Feasibility Validation → Phenotype Review
- **Trigger:** `phenotype_agent.validate_feasibility`
- **Condition:** `feasible == True`
- **Next State:** `PHENOTYPE_REVIEW` (approval gate)
- **Next Agent:** None (waits for SQL approval)

### 5. Phenotype SQL Approved → Schedule Kickoff
- **Trigger:** `approval_service.approve_phenotype_sql`
- **Condition:** `approved == True`
- **Next State:** `SCHEDULE_KICKOFF`
- **Next Agent:** `calendar_agent`
- **Next Task:** `schedule_kickoff_meeting`

### 6. Phenotype SQL Rejected → Feasibility Validation
- **Trigger:** `approval_service.reject_phenotype_sql`
- **Condition:** `approved == False`
- **Next State:** `FEASIBILITY_VALIDATION`
- **Next Agent:** `phenotype_agent`
- **Next Task:** `validate_feasibility`

### 7. Feasibility Failed → Not Feasible
- **Trigger:** `phenotype_agent.validate_feasibility_failed`
- **Condition:** `feasible == False`
- **Next State:** `NOT_FEASIBLE` (terminal)
- **Next Agent:** None

### 8. Kickoff Scheduled → Extraction Approval
- **Trigger:** `calendar_agent.schedule_kickoff_meeting`
- **Condition:** `meeting_scheduled == True`
- **Next State:** `EXTRACTION_APPROVAL` (approval gate)
- **Next Agent:** None (waits for extraction approval)

### 9. Extraction Approved → Data Extraction
- **Trigger:** `approval_service.approve_extraction`
- **Condition:** `approved == True`
- **Next State:** `DATA_EXTRACTION`
- **Next Agent:** `extraction_agent`
- **Next Task:** `extract_data`

### 10. Extraction Rejected → Human Review
- **Trigger:** `approval_service.reject_extraction`
- **Condition:** `approved == False`
- **Next State:** `HUMAN_REVIEW` (terminal)
- **Next Agent:** None

### 11. Data Extracted → QA Validation
- **Trigger:** `extraction_agent.extract_data`
- **Condition:** `extraction_complete == True`
- **Next State:** `QA_VALIDATION`
- **Next Agent:** `qa_agent`
- **Next Task:** `validate_extracted_data`

### 12. QA Passed → QA Review
- **Trigger:** `qa_agent.validate_extracted_data`
- **Condition:** `overall_status == 'passed'`
- **Next State:** `QA_REVIEW` (approval gate)
- **Next Agent:** None (waits for QA approval)

### 13. QA Approved → Data Delivery
- **Trigger:** `approval_service.approve_qa`
- **Condition:** `approved == True`
- **Next State:** `DATA_DELIVERY`
- **Next Agent:** `delivery_agent`
- **Next Task:** `deliver_data`

### 14. QA Rejected → Data Extraction
- **Trigger:** `approval_service.reject_qa`
- **Condition:** `approved == False`
- **Next State:** `DATA_EXTRACTION`
- **Next Agent:** `extraction_agent`
- **Next Task:** `extract_data`

### 15. QA Failed → QA Failed
- **Trigger:** `qa_agent.validate_extracted_data_failed`
- **Condition:** `overall_status == 'failed'`
- **Next State:** `QA_FAILED` (terminal)
- **Next Agent:** None

### 16. Data Delivered → Complete
- **Trigger:** `delivery_agent.deliver_data`
- **Condition:** `delivered == True`
- **Next State:** `COMPLETE` (terminal)
- **Next Agent:** None

### 17. Scope Change Approved → Requirements Gathering
- **Trigger:** `coordinator_agent.handle_scope_change`
- **Condition:** `scope_approved == True`
- **Next State:** `REQUIREMENTS_GATHERING`
- **Next Agent:** `requirements_agent`
- **Next Task:** `gather_requirements`

### 18. Scope Change Rejected → Human Review
- **Trigger:** `coordinator_agent.reject_scope_change`
- **Condition:** `scope_approved == False`
- **Next State:** `HUMAN_REVIEW` (terminal)
- **Next Agent:** None

---

## LangGraph StateGraph Design

### Nodes (Agent Actions)
1. `new_request` - Initialize request
2. `gather_requirements` - Requirements Agent
3. `requirements_review` - Wait for approval (approval gate)
4. `validate_feasibility` - Phenotype Agent
5. `phenotype_review` - Wait for SQL approval (approval gate)
6. `schedule_kickoff` - Calendar Agent
7. `extraction_approval` - Wait for extraction approval (approval gate)
8. `extract_data` - Extraction Agent
9. `validate_qa` - QA Agent
10. `qa_review` - Wait for QA approval (approval gate)
11. `deliver_data` - Delivery Agent
12. `complete` - Terminal success
13. `failed` - Terminal failure
14. `not_feasible` - Terminal (cohort too small)
15. `human_review` - Terminal (needs escalation)

### Conditional Edges (Routing)
1. `route_after_requirements` - Check if requirements complete
2. `route_after_requirements_review` - Check if approved/rejected
3. `route_after_feasibility` - Check if feasible
4. `route_after_phenotype_review` - Check if SQL approved/rejected
5. `route_after_extraction_approval` - Check if extraction approved/rejected
6. `route_after_qa` - Check if QA passed/failed
7. `route_after_qa_review` - Check if QA approved/rejected

### State Schema (TypedDict)
```python
class FullWorkflowState(TypedDict):
    # Request metadata
    request_id: str
    current_state: str
    created_at: str
    updated_at: str

    # Researcher info
    researcher_request: str
    researcher_info: dict

    # Requirements phase
    requirements: dict
    conversation_history: Annotated[list, add_messages]
    completeness_score: float
    requirements_approved: bool

    # Feasibility phase
    phenotype_sql: str
    feasibility_score: float
    estimated_cohort_size: int
    feasible: bool
    phenotype_approved: bool

    # Kickoff phase
    meeting_scheduled: bool
    meeting_details: dict

    # Extraction phase
    extraction_approved: bool
    extraction_complete: bool
    extracted_data_summary: dict

    # QA phase
    qa_passed: bool
    qa_report: dict
    qa_approved: bool

    # Delivery phase
    delivered: bool
    delivery_info: dict

    # Error handling
    error: str | None
    escalation_reason: str | None
```

---

## Implementation Plan

### Phase 1: Core Workflow (4 hours)
1. Create `WorkflowState` TypedDict with all fields
2. Create `FullWorkflow` class with `_build_graph()` method
3. Add all 15 nodes (state handlers)
4. Add basic edges (sequential flow)

### Phase 2: Conditional Routing (2 hours)
5. Implement 7 routing functions
6. Add conditional edges to graph
7. Test routing logic

### Phase 3: Agent Integration (4 hours)
8. Wrap Phenotype Agent with LangChain
9. Wrap Calendar Agent with LangChain
10. Wrap Extraction Agent with LangChain
11. Wrap QA Agent with LangChain
12. Wrap Delivery Agent with LangChain

### Phase 4: Persistence (2 hours)
13. Create `persistence.py` with database state management
14. Integrate with existing database models (ResearchRequest)
15. Add state save/load methods

### Phase 5: Testing (4 hours)
16. Create comprehensive test suite (20+ tests)
17. Test happy path (all approvals)
18. Test rejection paths
19. Test error paths
20. Test scope changes

### Phase 6: Documentation (2 hours)
21. Generate workflow diagram
22. Create Sprint 3 summary
23. Update Sprint Tracker

**Total Estimate:** 18 hours (2-3 days)

---

## Key Decisions

### Decision 1: Approval Gates as Nodes or Edges?
**Chosen:** Nodes (better for state persistence and observability)

**Reasoning:**
- Approval states need to persist in database
- LangSmith observability tracks node executions
- Easier to add timeout handling later
- Clearer in workflow diagram

### Decision 2: Agent Wrapping Strategy
**Chosen:** Keep existing agents, add LangChain wrapper layer

**Reasoning:**
- Minimize changes to existing agents (less risk)
- Allows gradual migration (can switch back if issues)
- Sprint 1 proved LangChain wrapper works well
- Can benchmark side-by-side

### Decision 3: State Management
**Chosen:** LangGraph state + database persistence

**Reasoning:**
- LangGraph state is transient (in-memory during workflow execution)
- Database is source of truth (survives restarts)
- Best of both worlds: fast execution + durable storage

---

## Risks & Mitigations

### Risk 1: Complexity Explosion
**Risk:** 23 states × 18 transitions = very complex graph
**Mitigation:** Build incrementally, test each phase
**Status:** Monitoring

### Risk 2: Approval State Handling
**Risk:** Approval gates block workflow, need external trigger
**Mitigation:** Use `END` marker, resume with new invocation
**Status:** Planned (based on Sprint 2 learning)

### Risk 3: Database Persistence
**Risk:** State schema mismatch between LangGraph and database
**Mitigation:** Clear mapping layer in `persistence.py`
**Status:** Planned

### Risk 4: Agent Integration Issues
**Risk:** 5 new agents to wrap, potential integration issues
**Mitigation:** Follow Sprint 1 pattern, test incrementally
**Status:** Monitoring

---

## Success Criteria

1. ✅ All 23 states represented in LangGraph
2. ✅ All 18 transitions work correctly
3. ✅ All 6 agents integrated with LangChain
4. ✅ Database persistence working
5. ✅ Test coverage ≥ 90% (20+ tests)
6. ✅ Automatic diagram generation
7. ✅ Performance acceptable (< 20% overhead vs custom)

---

**Next Step:** Create `app/langchain_orchestrator/langgraph_workflow.py` with full StateGraph
