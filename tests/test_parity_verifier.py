"""Sprint 7.2 Phase 1 — parity verifier harness tests.

The harness drives 30 formal-portal requests through each
USE_LANGGRAPH_WORKFLOW value (false=A2A, true=LangGraph), then compares
structural-parity evidence across 5 dimensions and emits a JSONL report.
The Sprint 7.2 close ADR cites the JSONL artifact as evidence that the
deletion in Phase 5 is safe.

These tests follow Sprint 7.2 ADR D4c — JSONL schema with self-describing
rows: each row carries both orchestrator's raw values plus a match bit
plus bounded/blocking severity. The harness is in
scripts/parity_verify_a2a_vs_langgraph.py (one-shot tool; deleted at
sprint close per migration-helper pattern).

Cycle 1 tracer bullet: prove the end-to-end shape works. Given a pair of
synthetic state sequences, compare_pair() emits a ParityRow JSON-serializable
object that a JSONL writer can dump to disk.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Cycle 1 — tracer bullet: compare_pair + JSONL writer end-to-end shape
# ---------------------------------------------------------------------------


def test_compare_pair_emits_jsonl_row_for_matching_state_sequence(tmp_path):
    """Given identical state sequences, compare_pair() yields a ParityRow with
    match=True, severity=None, both sides' raw values preserved.

    Tracer bullet for the harness pipeline: if this fails, the report-row
    shape is broken before any individual dimension query is even built.
    """
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from parity_verify_a2a_vs_langgraph import ParityRow, compare_pair, write_jsonl_row

    lg_value = ["new_request", "requirements_gathering", "complete"]
    a2a_value = ["new_request", "requirements_gathering", "complete"]

    row = compare_pair(
        thread_id="REQ-20260515-ABC",
        dimension="state_sequence",
        langgraph=lg_value,
        a2a=a2a_value,
    )

    assert isinstance(row, ParityRow), "compare_pair must return a ParityRow object"
    assert row.thread_id == "REQ-20260515-ABC"
    assert row.dimension == "state_sequence"
    assert row.langgraph == lg_value
    assert row.a2a == a2a_value
    assert row.match is True, "Identical sequences must match"
    assert row.severity is None, "Matched rows have null severity"
    assert row.diff is None, "Matched rows have null diff"

    # Round-trip through JSONL writer — proves the report artifact shape works
    log_path = tmp_path / "test_parity.jsonl"
    write_jsonl_row(row, log_path)

    assert log_path.exists()
    raw = log_path.read_text().strip()
    parsed = json.loads(raw)
    # Schema contract per D4c
    assert set(parsed.keys()) >= {
        "thread_id",
        "dimension",
        "langgraph",
        "a2a",
        "match",
        "severity",
        "diff",
    }
    assert parsed["match"] is True
    assert parsed["langgraph"] == lg_value
    assert parsed["a2a"] == a2a_value


# ---------------------------------------------------------------------------
# Cycle 2 — dimension 1: state_sequence query against research_requests.state_history
# ---------------------------------------------------------------------------


async def test_dimension_1_state_sequence_returns_ordered_state_names(clean_database):
    """fetch_state_sequence(thread_id, db_session) returns ordered state names
    from research_requests.state_history for the given row.

    The harness uses LangGraph thread_id as the lookup key. ResearchRequest.id
    is the canonical thread_id surface (REQ-YYYYMMDD-XXXXXXXX); the LangGraph
    checkpointer sets thread_id = request_id per workflow invocation.

    state_history is a JSON list of {state, timestamp} entries persisted
    chronologically as the workflow progresses. fetch_state_sequence sorts
    by timestamp defensively (don't rely on file order) and returns the
    `state` string from each entry.
    """
    import sys
    from datetime import datetime, timedelta

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from parity_verify_a2a_vs_langgraph import fetch_state_sequence

    from app.database import get_db_session
    from app.database.models import ResearchRequest

    request_id = "REQ-20260516-PARITYC2"
    base_ts = datetime(2026, 5, 16, 10, 0, 0)
    state_history = [
        {"state": "new_request", "timestamp": base_ts.isoformat()},
        {
            "state": "requirements_gathering",
            "timestamp": (base_ts + timedelta(seconds=5)).isoformat(),
        },
        {
            "state": "feasibility_validation",
            "timestamp": (base_ts + timedelta(seconds=10)).isoformat(),
        },
        {"state": "complete", "timestamp": (base_ts + timedelta(seconds=15)).isoformat()},
    ]

    async with get_db_session() as session:
        session.add(
            ResearchRequest(
                id=request_id,
                researcher_name="parity-harness-cycle2",
                researcher_email="cycle2@parity.test",
                initial_request="parity-harness synthetic row",
                current_state="complete",
                state_history=state_history,
            )
        )
        await session.commit()

        result = await fetch_state_sequence(thread_id=request_id, db_session=session)

    assert result == [
        "new_request",
        "requirements_gathering",
        "feasibility_validation",
        "complete",
    ], "ordered state names must be lifted directly from state_history"


async def test_dimension_1_state_sequence_returns_empty_list_for_unknown_thread_id(clean_database):
    """Unknown thread_id returns []. The harness uses [] as a signal that the
    orchestrator never persisted a row for this thread_id — the caller
    (compare_pair) then decides whether that's a parity-row signal or a
    harness error.
    """
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from parity_verify_a2a_vs_langgraph import fetch_state_sequence

    from app.database import get_db_session

    async with get_db_session() as session:
        result = await fetch_state_sequence(thread_id="REQ-DOES-NOT-EXIST", db_session=session)

    assert result == [], "unknown thread_id must return [] (not None, not raise)"


async def test_dimension_1_state_sequence_sorts_out_of_order_timestamps(clean_database):
    """state_history is sorted by timestamp ascending before extracting names.

    Defensive sort: even if a future code path appends out-of-order (e.g., a
    backfill script or a clock-skew event), the harness produces deterministic
    output. Same shape across orchestrators is what dim 1 parity needs.
    """
    import sys
    from datetime import datetime, timedelta

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from parity_verify_a2a_vs_langgraph import fetch_state_sequence

    from app.database import get_db_session
    from app.database.models import ResearchRequest

    request_id = "REQ-20260516-PARITYC2X"
    base_ts = datetime(2026, 5, 16, 10, 0, 0)
    # Insertion order is intentionally NOT chronological
    state_history = [
        {"state": "complete", "timestamp": (base_ts + timedelta(seconds=15)).isoformat()},
        {"state": "new_request", "timestamp": base_ts.isoformat()},
        {
            "state": "feasibility_validation",
            "timestamp": (base_ts + timedelta(seconds=10)).isoformat(),
        },
        {
            "state": "requirements_gathering",
            "timestamp": (base_ts + timedelta(seconds=5)).isoformat(),
        },
    ]

    async with get_db_session() as session:
        session.add(
            ResearchRequest(
                id=request_id,
                researcher_name="parity-harness-cycle2-sort",
                researcher_email="cycle2sort@parity.test",
                initial_request="parity-harness synthetic out-of-order row",
                current_state="complete",
                state_history=state_history,
            )
        )
        await session.commit()

        result = await fetch_state_sequence(thread_id=request_id, db_session=session)

    assert result == [
        "new_request",
        "requirements_gathering",
        "feasibility_validation",
        "complete",
    ], "fetcher must sort by timestamp ascending before extracting state names"
