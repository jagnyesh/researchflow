"""#144: gate telemetry from the approvals table: counts, reviewer time, categories.

Reads only existing columns; reports aggregates, never review-note text.
"""

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.services.gate_telemetry import (
    CATEGORIES,
    categorize_rejection,
    load_gate_telemetry,
    summarize_gates,
)

T0 = datetime(2026, 10, 1, 9, 0)


def _row(approval_type, status, minutes=None, notes=None):
    return SimpleNamespace(
        approval_type=approval_type,
        status=status,
        submitted_at=T0,
        reviewed_at=T0 + timedelta(minutes=minutes) if minutes is not None else None,
        review_notes=notes,
    )


def test_counts_per_gate_by_decision():
    summary = summarize_gates(
        [
            _row("requirements", "approved", 5),
            _row("requirements", "rejected", 30, "missing the age criterion"),
            _row("phenotype_sql", "modified", 12, "wrong ICD code for T2DM"),
            _row("phenotype_sql", "pending"),
        ]
    )

    assert summary["G1"]["counts"] == {
        "approved": 1,
        "rejected": 1,
        "modified": 0,
        "pending": 0,
        "timeout": 0,
    }
    assert summary["G2"]["counts"] == {
        "approved": 0,
        "rejected": 0,
        "modified": 1,
        "pending": 1,
        "timeout": 0,
    }
    assert summary["G1"]["rejection_rate"] == 0.5


def test_reviewer_time_and_timestamp_coverage():
    summary = summarize_gates(
        [
            _row("requirements", "approved", 4),
            _row("requirements", "approved", 10),
            _row("requirements", "rejected", 60, "scope creep"),
            _row("requirements", "approved", None),  # decided, no reviewed_at
        ]
    )

    time = summary["G1"]["reviewer_minutes"]
    assert time["median"] == 10 and time["n"] == 3
    assert time["decided_without_timestamp"] == 1


@pytest.mark.parametrize(
    "notes,category",
    [
        ("wrong ICD-10 code for diabetes", "wrong_codes"),
        ("missing the age > 65 criterion", "missing_predicate"),
        ("adds a filter nobody asked for", "extra_predicate"),
        ("this is beyond the IRB scope", "scope_creep"),
        ("cohort too small to be feasible", "infeasible_cohort"),
        ("patient names must not be delivered", "phi_concern"),
        ("please re-check", "other"),
        (None, "other"),
    ],
)
def test_rejection_categories(notes, category):
    assert categorize_rejection(notes) == category
    assert len(CATEGORIES) <= 8 and category in CATEGORIES


def test_summary_never_carries_note_text():
    summary = summarize_gates([_row("phenotype_sql", "rejected", 3, "Patient Jane Doe 1970-01-01")])

    assert "Jane" not in repr(summary)
    assert summary["G2"]["categories"]["other"] == 1


@pytest.mark.asyncio
async def test_loader_reads_the_approvals_table():
    from app.database import ResearchRequest, get_db_session, init_db
    from app.database.models import Approval

    await init_db()
    request_id = f"REQ-GT-{uuid.uuid4().hex[:8]}"
    async with get_db_session() as session:
        session.add(
            ResearchRequest(
                id=request_id,
                researcher_name="Synthetic",
                researcher_email="s@example.org",
                initial_request="synthetic",
                current_state="complete",
            )
        )
        session.add(
            Approval(
                request_id=request_id,
                approval_type="phenotype_sql",
                submitted_by="phenotype_agent",
                approval_data={},
                status="rejected",
                submitted_at=T0,
                reviewed_at=T0 + timedelta(minutes=7),
                review_notes="wrong SNOMED code",
            )
        )

    summary = await load_gate_telemetry(request_ids=[request_id])

    assert summary["G2"]["counts"]["rejected"] == 1
    assert summary["G2"]["categories"]["wrong_codes"] == 1
    assert summary["G2"]["reviewer_minutes"]["median"] == 7


def test_a_gate_with_no_rows_is_reported_not_omitted():
    summary = summarize_gates([_row("phenotype_sql", "approved", 2)])

    assert summary["G1"]["counts"] == {
        "approved": 0,
        "rejected": 0,
        "modified": 0,
        "pending": 0,
        "timeout": 0,
    }
    assert summary["G1"]["rejection_rate"] is None


def test_dashboard_rows_flatten_each_gate():
    from app.services.gate_telemetry import gate_telemetry_rows

    rows = gate_telemetry_rows(
        summarize_gates([_row("phenotype_sql", "rejected", 6, "wrong LOINC code")])
    )

    g2 = next(r for r in rows if r["gate"] == "G2")
    assert g2["rejected"] == 1 and g2["median reviewer minutes"] == 6
    assert g2["top category"] == "wrong_codes"
    assert {r["gate"] for r in rows} >= {"G1", "G2"}


def test_timed_out_approvals_are_counted_but_not_as_reviewer_decisions():
    summary = summarize_gates(
        [
            _row("phenotype_sql", "approved", 5),
            _row("phenotype_sql", "rejected", 9, "wrong code"),
            _row("phenotype_sql", "timeout"),  # nobody reviewed it; no reviewed_at by design
        ]
    )

    g2 = summary["G2"]
    assert g2["counts"]["timeout"] == 1
    assert g2["rejection_rate"] == 0.5
    assert g2["reviewer_minutes"]["decided_without_timestamp"] == 0


def test_code_names_are_a_coding_problem_not_phi():
    assert categorize_rejection("the code names are wrong") == "wrong_codes"
    assert categorize_rejection("patient names must not be delivered") == "phi_concern"
