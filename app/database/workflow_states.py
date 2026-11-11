"""The states that `research_requests.current_state` can hold, and what each one means.

This module is the one declared vocabulary for a request's lifecycle (#432).
`WorkflowState` lists every value. `STATE_INFO` gives each value a kind, a
display label, the agent that owns the state and, for a review state, the
approval type that resumes it.

`tests/test_workflow_state_contract.py` reads the graph and the source under
`app/`. It fails when code writes a value that is not a member, when a member
has no `STATE_INFO` entry, and when a member's kind disagrees with whether code
writes the value. This docstring gives no counts, because the counts it used to
give were wrong. The test's scan is the list of values that code writes.

A `LEGACY` member is a value that old rows hold and that no current code
writes. Most date from the A2A orchestrator, which Sprint 7.2 deleted. A filter
on a legacy value matches old rows only. The request API's delivered checks
(`app/api/research.py`) accept only `COMPLETE`, the state that a successful run
ends in (#53). `DELIVERED` is legacy.

`WorkflowState` is a plain `Enum`, and `current_state` is a `String` column.
Compare the column with `.value`:

    ResearchRequest.current_state == WorkflowState.COMPLETE.value

Comparing the column with a member raises `ProgrammingError` on SQLAlchemy 2.0
with aiosqlite. A `str` subclass would stop that error. It would also change
equality, hashing and JSON output for every existing member, and no reader
needs that: a reader starts from a stored string and looks the member up with
`WorkflowState(value)`. A later move to a `str` subclass breaks no `.value`
caller, so the enum stays plain until a reader needs otherwise.

A comparison in Python between a stored string and a member is `False` and
raises nothing. Compare with `.value` there too.

History: the enum began inside the A2A orchestrator. Sprint 7.2 Phase 0
(2026-05-15) moved it here because production code depends on the `.value`
strings, and Phase 4 (2026-05-17) deleted `app/orchestrator/`. Renaming a
value orphans the rows that hold it. `tests/test_workflow_states_promotion.py`
pins every name and value.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


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
    PREVIEW_QA_REVIEW = "preview_qa_review"  # Informatician reviews a failed preview QA
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
    ERROR = "error"  # The workflow raised, or the requirements node caught a failure
    HUMAN_REVIEW = "human_review"

    @property
    def info(self) -> "StateInfo":
        """This state's kind, label, owning agent and approval type."""
        return STATE_INFO[self]


class StateKind(Enum):
    """What a state tells a reader about the request."""

    IN_PROGRESS = "in_progress"  # An agent is working, or the request waits for its next step
    AWAITING_REVIEW = "awaiting_review"  # Paused at a gate until a person decides
    SUCCEEDED = "succeeded"  # Ended with the data delivered
    FAILED = "failed"  # Ended without delivering the data
    LEGACY = "legacy"  # Old rows hold it; no current code writes it


@dataclass(frozen=True)
class StateInfo:
    kind: StateKind
    label: str
    agent: Optional[str] = None  # Agent ID as `research_requests.current_agent` stores it
    approval_type: Optional[str] = None  # `approvals.approval_type` that resumes a review state


_IN_PROGRESS = StateKind.IN_PROGRESS
_AWAITING_REVIEW = StateKind.AWAITING_REVIEW
_LEGACY = StateKind.LEGACY

STATE_INFO: dict[WorkflowState, StateInfo] = {
    WorkflowState.NEW_REQUEST: StateInfo(_IN_PROGRESS, "New request"),
    WorkflowState.REQUIREMENTS_GATHERING: StateInfo(
        _IN_PROGRESS, "Requirements gathering", "requirements_agent"
    ),
    WorkflowState.REQUIREMENTS_REVIEW: StateInfo(
        _AWAITING_REVIEW, "Requirements review", "requirements_agent", "requirements"
    ),
    WorkflowState.FEASIBILITY_VALIDATION: StateInfo(
        _IN_PROGRESS, "Feasibility validation", "phenotype_agent"
    ),
    WorkflowState.PHENOTYPE_REVIEW: StateInfo(
        _AWAITING_REVIEW, "Phenotype review", "phenotype_agent", "phenotype_sql"
    ),
    WorkflowState.PREVIEW_EXTRACTION: StateInfo(
        _IN_PROGRESS, "Preview extraction", "extraction_agent"
    ),
    WorkflowState.PREVIEW_QA: StateInfo(_IN_PROGRESS, "Preview QA", "qa_agent"),
    WorkflowState.PREVIEW_QA_REVIEW: StateInfo(
        _AWAITING_REVIEW, "Preview QA review", "qa_agent", "preview_qa"
    ),
    WorkflowState.DATA_EXTRACTION: StateInfo(_IN_PROGRESS, "Data extraction", "extraction_agent"),
    WorkflowState.QA_VALIDATION: StateInfo(_IN_PROGRESS, "QA validation", "qa_agent"),
    # A `delivery` approval resumes qa_review: the reviewer approves the delivery.
    WorkflowState.QA_REVIEW: StateInfo(_AWAITING_REVIEW, "QA review", "qa_agent", "delivery"),
    WorkflowState.DATA_DELIVERY: StateInfo(_IN_PROGRESS, "Data delivery", "delivery_agent"),
    WorkflowState.COMPLETE: StateInfo(StateKind.SUCCEEDED, "Complete"),
    WorkflowState.NOT_FEASIBLE: StateInfo(StateKind.FAILED, "Not feasible"),
    WorkflowState.QA_FAILED: StateInfo(StateKind.FAILED, "QA failed"),
    WorkflowState.ERROR: StateInfo(StateKind.FAILED, "Error"),
    # The graph ends here with no approval to resume it, so this is not a review state.
    WorkflowState.HUMAN_REVIEW: StateInfo(StateKind.FAILED, "Human review"),
    WorkflowState.REQUIREMENTS_COMPLETE: StateInfo(_LEGACY, "Requirements complete"),
    WorkflowState.EXTRACTION_APPROVAL: StateInfo(_LEGACY, "Extraction approval"),
    WorkflowState.SCOPE_CHANGE: StateInfo(_LEGACY, "Scope change"),
    WorkflowState.PREVIEW_COMPLETE: StateInfo(_LEGACY, "Preview complete"),
    WorkflowState.FEASIBLE: StateInfo(_LEGACY, "Feasible"),
    WorkflowState.SCHEDULE_KICKOFF: StateInfo(_LEGACY, "Schedule kickoff"),
    WorkflowState.KICKOFF_COMPLETE: StateInfo(_LEGACY, "Kickoff complete"),
    WorkflowState.EXTRACTION_COMPLETE: StateInfo(_LEGACY, "Extraction complete"),
    WorkflowState.QA_PASSED: StateInfo(_LEGACY, "QA passed"),
    WorkflowState.DELIVERY_REVIEW: StateInfo(_LEGACY, "Delivery review"),
    WorkflowState.DELIVERED: StateInfo(_LEGACY, "Delivered"),
    WorkflowState.FAILED: StateInfo(_LEGACY, "Failed"),
}
