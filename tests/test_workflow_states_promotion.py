"""Sprint 7.2 Phase 0 guard — WorkflowState promoted to schema module.

Background: until Sprint 7.2, `WorkflowState` lived inside
`app/orchestrator/workflow_engine.py` (A2A FSM internal). Five production
callers (`app/api/research.py`, `app/web_ui/dashboard_helpers.py`, and
3 others) depended on its `.value` strings as the canonical state strings
for `research_requests.current_state` — effectively a DB schema enum
masquerading as an orchestrator internal.

Sprint 7.2 Phase 0 promotes it to `app/database/workflow_states.py` so the
A2A package can be deleted in Phase 4 without breaking production. This
test file LOCKS the promotion: all 25 enum values must resolve from the
new home with the exact same `.value` strings as before (DB schema
compatibility), AND the old home must still re-export them (A2A internal
self-references keep working until Phase 4 deletion).

If these tests fail in a future change, the most likely cause is someone
silently renaming a state value (breaks DB-stored historical rows) or
removing the re-export from the old home before Phase 4 lands. Both are
sprint-gating regressions.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Cycle 1 — tracer bullet: new module exists, one value resolves
# ---------------------------------------------------------------------------


def test_workflow_state_resolves_from_new_home():
    """WorkflowState importable from app.database.workflow_states with the
    canonical NEW_REQUEST value preserved.

    Tracer bullet for the promotion: if this fails, Phase 0's import path
    is broken before any other guard runs.
    """
    from app.database.workflow_states import WorkflowState

    assert WorkflowState.NEW_REQUEST.value == "new_request"


# ---------------------------------------------------------------------------
# Cycle 2 — full enum parity: all 27 (name, value) pairs preserved
# ---------------------------------------------------------------------------

# Source-of-truth (name, value) pairs at Sprint 7.2 Phase 0 commit time.
# Encoded literally to lock the DB schema contract — if a future change
# silently renames a value, this list breaks the contract loudly.
# 27 values total. Reordering OK; renaming a .value string is NOT OK
# (breaks DB-stored historical rows).
_EXPECTED_WORKFLOW_STATES = [
    ("NEW_REQUEST", "new_request"),
    ("REQUIREMENTS_GATHERING", "requirements_gathering"),
    ("REQUIREMENTS_COMPLETE", "requirements_complete"),
    ("REQUIREMENTS_REVIEW", "requirements_review"),
    ("PHENOTYPE_REVIEW", "phenotype_review"),
    ("EXTRACTION_APPROVAL", "extraction_approval"),
    ("QA_REVIEW", "qa_review"),
    ("SCOPE_CHANGE", "scope_change"),
    ("PREVIEW_EXTRACTION", "preview_extraction"),
    ("PREVIEW_QA", "preview_qa"),
    ("PREVIEW_COMPLETE", "preview_complete"),
    ("FEASIBILITY_VALIDATION", "feasibility_validation"),
    ("FEASIBLE", "feasible"),
    ("NOT_FEASIBLE", "not_feasible"),
    ("SCHEDULE_KICKOFF", "schedule_kickoff"),
    ("KICKOFF_COMPLETE", "kickoff_complete"),
    ("DATA_EXTRACTION", "data_extraction"),
    ("EXTRACTION_COMPLETE", "extraction_complete"),
    ("QA_VALIDATION", "qa_validation"),
    ("QA_PASSED", "qa_passed"),
    ("QA_FAILED", "qa_failed"),
    ("DELIVERY_REVIEW", "delivery_review"),
    ("DATA_DELIVERY", "data_delivery"),
    ("DELIVERED", "delivered"),
    ("COMPLETE", "complete"),
    ("FAILED", "failed"),
    ("HUMAN_REVIEW", "human_review"),
]


@pytest.mark.parametrize("name,expected_value", _EXPECTED_WORKFLOW_STATES)
def test_workflow_state_value_preserved(name, expected_value):
    """Each canonical state has its .value string preserved.

    This is the DB schema compatibility check: research_requests.current_state
    rows contain these strings. Changing a .value renames the DB row's state
    silently — production code keeps writing the new string while historical
    rows still hold the old one, breaking every query that filters on either.
    """
    from app.database.workflow_states import WorkflowState

    state = getattr(WorkflowState, name, None)
    assert state is not None, (
        f"WorkflowState.{name} is missing from app.database.workflow_states. "
        f"If this state was deliberately retired, the DB-stored historical rows "
        f"that reference '{expected_value}' need a migration plan first."
    )
    assert state.value == expected_value, (
        f"WorkflowState.{name}.value changed from {expected_value!r} to "
        f"{state.value!r}. This breaks DB schema compatibility — historical "
        f"rows holding {expected_value!r} no longer match any enum member."
    )


def test_workflow_state_total_count_locked():
    """No accidental state addition without updating this guard's manifest.

    If a new state lands in app/database/workflow_states.py without being
    added to _EXPECTED_WORKFLOW_STATES above, this catches it. New states are
    fine — but each one is a DB schema decision worth surfacing.
    """
    from app.database.workflow_states import WorkflowState

    actual_names = {s.name for s in WorkflowState}
    expected_names = {name for name, _ in _EXPECTED_WORKFLOW_STATES}
    extras = actual_names - expected_names
    missing = expected_names - actual_names
    assert not extras, (
        f"WorkflowState has new states not in the Phase 0 guard manifest: "
        f"{sorted(extras)}. Add them to _EXPECTED_WORKFLOW_STATES if they're "
        f"intentional."
    )
    assert not missing, (
        f"WorkflowState is missing states from the Phase 0 guard manifest: "
        f"{sorted(missing)}. Restore them or remove from the manifest with a "
        f"DB migration plan."
    )


# ---------------------------------------------------------------------------
# Cycle 3 — old home re-exports from new home (one source of truth)
# ---------------------------------------------------------------------------


def test_old_home_no_longer_exists_after_phase_4_deletion():
    """`from app.orchestrator.workflow_engine import WorkflowState` MUST FAIL
    after Phase 4 deleted app/orchestrator/ entirely (Sprint 7.2 2026-05-17).

    Phase 0 (cycle ~3-week ago) added a re-export shim so the A2A package
    could keep importing WorkflowState during the transitional period.
    Phase 4 retired that shim by deleting app/orchestrator/ wholesale.

    This test inverts the original Cycle-3 assertion: the old import path
    is now expected to be gone. If somehow `app.orchestrator.workflow_engine`
    is importable again, something has regressed (either Phase 4's deletion
    got reverted or someone re-created the package).
    """
    import pytest

    with pytest.raises(ImportError):
        from app.orchestrator.workflow_engine import WorkflowState  # noqa: F401
