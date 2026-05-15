"""Canonical workflow state strings for research_requests.current_state.

This enum was historically internal to the A2A orchestrator
(app/orchestrator/workflow_engine.py). Sprint 7.2 Phase 0 promoted it to a
schema module because production code (5 callers in app/api/research.py,
app/web_ui/dashboard_helpers.py, and others) depends on the .value strings
as the canonical DB state values.

The enum contains 27 states. The current LangGraph orchestrator
(app/langchain_orchestrator/langgraph_workflow.py) emits 17 distinct
state strings, all of which are members of this enum. The remaining
10 states are historical-only — they may appear in production DB rows
from the A2A era but LangGraph never writes them:

    REQUIREMENTS_COMPLETE, EXTRACTION_APPROVAL, SCOPE_CHANGE,
    PREVIEW_COMPLETE, FEASIBLE, KICKOFF_COMPLETE, EXTRACTION_COMPLETE,
    QA_PASSED, DELIVERY_REVIEW, DELIVERED, FAILED

These are retained for backward-compat queries. Production code that
filters by state should be aware that LangGraph never emits these
values — any query depending on them only matches pre-LangGraph rows.

(Empirical note: Sprint 8.4 grilling claimed 25 A2A values and listed
HUMAN_REVIEW as LangGraph-only. Sprint 7.2 Phase 0 implementation
verified the actual count is 27, and HUMAN_REVIEW is in both engines.
The DECISIONS.md ADR is corrected separately.)

Known related issue: app/api/research.py queries
WHERE current_state IN ('delivered', 'complete'). LangGraph never writes
'delivered'. Pre-existing latent bug, filed as #53 — not in
Sprint 7.2 scope (Sprint 7.2 preserves existing query behavior).

Until Sprint 7.2 Phase 4 deletes app/orchestrator/, the old import path
(app.orchestrator.workflow_engine.WorkflowState) continues to resolve
via a re-export. Both paths point to the same enum object — there is no
drift. After Phase 4, only the new home remains.
"""

from __future__ import annotations

from enum import Enum


class WorkflowState(Enum):
    """Workflow states for research data requests."""

    NEW_REQUEST = "new_request"
    REQUIREMENTS_GATHERING = "requirements_gathering"
    REQUIREMENTS_COMPLETE = "requirements_complete"

    # Approval states (Human-in-Loop)
    REQUIREMENTS_REVIEW = "requirements_review"
    PHENOTYPE_REVIEW = "phenotype_review"
    EXTRACTION_APPROVAL = "extraction_approval"
    QA_REVIEW = "qa_review"
    SCOPE_CHANGE = "scope_change"

    # Preview extraction workflow
    PREVIEW_EXTRACTION = "preview_extraction"  # Extract 10 rows per data element
    PREVIEW_QA = "preview_qa"  # Auto QA validation on preview
    PREVIEW_COMPLETE = "preview_complete"  # Preview validated and approved

    FEASIBILITY_VALIDATION = "feasibility_validation"
    FEASIBLE = "feasible"
    NOT_FEASIBLE = "not_feasible"
    SCHEDULE_KICKOFF = "schedule_kickoff"  # Optional post-delivery
    KICKOFF_COMPLETE = "kickoff_complete"
    DATA_EXTRACTION = "data_extraction"  # Full extraction
    EXTRACTION_COMPLETE = "extraction_complete"
    QA_VALIDATION = "qa_validation"  # Auto QA validation on full data
    QA_PASSED = "qa_passed"
    QA_FAILED = "qa_failed"
    DELIVERY_REVIEW = "delivery_review"  # Informatician reviews full dataset before delivery
    DATA_DELIVERY = "data_delivery"
    DELIVERED = "delivered"
    COMPLETE = "complete"
    FAILED = "failed"
    HUMAN_REVIEW = "human_review"
