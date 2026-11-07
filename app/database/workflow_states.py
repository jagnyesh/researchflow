"""Canonical workflow state strings for research_requests.current_state.

This enum was originally internal to the A2A orchestrator at
app/orchestrator/workflow_engine.py. Sprint 7.2 Phase 0 (2026-05-15)
promoted it to a schema module because production code depends on the
`.value` strings as the canonical DB state values. Sprint 7.2 Phase 4
(2026-05-17) then deleted app/orchestrator/ entirely. This module is now
the sole home; there is no compatibility shim, no re-export path.

The enum contains 27 states. The current LangGraph orchestrator
(app/langchain_orchestrator/langgraph_workflow.py) emits 17 distinct
state strings, all members of this enum. The remaining 10 are
historical-only — they may appear in `research_requests.current_state`
for pre-LangGraph rows but LangGraph never writes them:

    REQUIREMENTS_COMPLETE, EXTRACTION_APPROVAL, SCOPE_CHANGE,
    PREVIEW_COMPLETE, FEASIBLE, KICKOFF_COMPLETE, EXTRACTION_COMPLETE,
    QA_PASSED, DELIVERY_REVIEW, DELIVERED, FAILED

These are retained so old-row queries don't break. Code that filters by
state should be aware that LangGraph never writes these values — any
filter depending on them only matches pre-LangGraph rows.

The request API's delivered checks (app/api/research.py) accept only
COMPLETE, the state LangGraph ends a successful run in (#53). DELIVERED
stays for old rows and is A2A-era only.
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
    DELIVERED = "delivered"  # A2A-era only; LangGraph ends at COMPLETE (#53)
    COMPLETE = "complete"
    FAILED = "failed"
    HUMAN_REVIEW = "human_review"
