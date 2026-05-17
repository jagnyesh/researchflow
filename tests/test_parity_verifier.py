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


# ---------------------------------------------------------------------------
# Cycle 3 — dimension 2: agent_execution_order from LangSmith
# Per ADR 0024 D4: per-orchestrator query branch.
#   LangGraph: filter execute_task chain spans, sort by start_time, extract
#              agent name from `agent=*-agent` tag
#   A2A: filter is_root=True chain runs, sort by start_time, return run.name
# ---------------------------------------------------------------------------


def _mk_run(name, start_time, run_type="chain", tags=None, metadata=None):
    """Build a synthetic Mock run object with the attributes the fetcher reads."""
    from unittest.mock import MagicMock

    run = MagicMock()
    run.name = name
    run.start_time = start_time
    run.run_type = run_type
    run.tags = tags or []
    run.metadata = metadata or {}
    return run


def test_dimension_2_agent_execution_order_langgraph_happy_path():
    """LangGraph trace shape: depth-1 children of the `LangGraph` root are
    state nodes, depth-2 `execute_task` chain spans carry the agent name in
    their `agent=*-agent` tag. The fetcher should sort by start_time and
    return the ordered list of agent names.

    Per ADR 0024 D4 pre-flight (2026-05-15): this branch returns the agents
    in invocation order; that's what dimension 2 parity needs.
    """
    from datetime import datetime
    from pathlib import Path
    from unittest.mock import MagicMock
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from parity_verify_a2a_vs_langgraph import fetch_agent_execution_order

    thread_id = "REQ-20260516-PARITYC3"
    base_ts = datetime(2026, 5, 16, 10, 0, 0)
    # Synthetic LangGraph trace: 3 execute_task spans (one per agent run)
    # plus some noise (the root span, a non-execute_task chain span, an LLM
    # leaf) to exercise the filter logic.
    runs = [
        _mk_run(
            name="LangGraph",
            start_time=base_ts,
            tags=["portal:formal"],
            metadata={"thread_id": thread_id},
        ),
        _mk_run(
            name="execute_task",
            start_time=base_ts.replace(second=10),
            tags=["portal:formal", "agent=requirements-agent"],
            metadata={"thread_id": thread_id},
        ),
        _mk_run(
            name="execute_task",
            start_time=base_ts.replace(second=20),
            tags=["portal:formal", "agent=phenotype-agent"],
            metadata={"thread_id": thread_id},
        ),
        # Noise: a different state-node chain span (not execute_task)
        _mk_run(
            name="requirements_gathering",
            start_time=base_ts.replace(second=5),
            tags=["portal:formal"],
            metadata={"thread_id": thread_id},
        ),
        # Noise: an LLM leaf at deeper depth
        _mk_run(
            name="ChatAnthropic",
            start_time=base_ts.replace(second=11),
            run_type="llm",
            tags=["portal:formal", "agent=requirements-agent"],
            metadata={"thread_id": thread_id},
        ),
        _mk_run(
            name="execute_task",
            start_time=base_ts.replace(second=30),
            tags=["portal:formal", "agent=qa-agent"],
            metadata={"thread_id": thread_id},
        ),
        # Noise: wrong thread_id (should be filtered out)
        _mk_run(
            name="execute_task",
            start_time=base_ts.replace(second=12),
            tags=["portal:formal", "agent=delivery-agent"],
            metadata={"thread_id": "REQ-OTHER-THREAD"},
        ),
    ]
    mock_client = MagicMock()
    mock_client.list_runs.return_value = iter(runs)

    result = fetch_agent_execution_order(
        thread_id=thread_id,
        orchestrator="langgraph",
        langsmith_client=mock_client,
    )

    assert result == [
        "requirements-agent",
        "phenotype-agent",
        "qa-agent",
    ], "LangGraph branch must return execute_task agents in start_time order, filtered by thread_id"


def test_dimension_2_agent_execution_order_a2a_happy_path():
    """A2A trace shape: each agent invocation produces an INDEPENDENT root
    run (run_type='chain'). The harness reads is_root=True chain runs,
    filters by thread_id, sorts by start_time, and returns run.name verbatim.

    Per ADR 0024 D4 pre-flight: A2A's `WorkflowEngine.determine_next_step`
    is NOT @traceable, so state transitions don't appear in LangSmith;
    only the agent calls themselves do, as disconnected roots.
    """
    from datetime import datetime
    from pathlib import Path
    from unittest.mock import MagicMock
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from parity_verify_a2a_vs_langgraph import fetch_agent_execution_order

    thread_id = "REQ-20260516-PARITYC3A2A"
    base_ts = datetime(2026, 5, 16, 10, 0, 0)
    runs = [
        # Three agent roots for this thread
        _mk_run(
            name="RequirementsAgent",
            start_time=base_ts,
            metadata={"thread_id": thread_id},
        ),
        _mk_run(
            name="PhenotypeAgent",
            start_time=base_ts.replace(second=10),
            metadata={"thread_id": thread_id},
        ),
        _mk_run(
            name="QAAgent",
            start_time=base_ts.replace(second=20),
            metadata={"thread_id": thread_id},
        ),
        # Noise: wrong thread
        _mk_run(
            name="DeliveryAgent",
            start_time=base_ts.replace(second=5),
            metadata={"thread_id": "REQ-OTHER"},
        ),
        # Noise: an llm-typed root (not a chain) — should be filtered out
        _mk_run(
            name="ChatAnthropic",
            start_time=base_ts.replace(second=15),
            run_type="llm",
            metadata={"thread_id": thread_id},
        ),
    ]
    mock_client = MagicMock()
    mock_client.list_runs.return_value = iter(runs)

    result = fetch_agent_execution_order(
        thread_id=thread_id,
        orchestrator="a2a",
        langsmith_client=mock_client,
    )

    assert result == [
        "RequirementsAgent",
        "PhenotypeAgent",
        "QAAgent",
    ], "A2A branch must return chain roots in start_time order, filtered by thread_id, excluding llm leaves"

    # Confirm the query was made for ROOT runs only (A2A trace shape).
    call_kwargs = mock_client.list_runs.call_args.kwargs
    assert call_kwargs.get("is_root") is True, "A2A branch must query is_root=True"


def test_dimension_2_agent_execution_order_unknown_thread_returns_empty():
    """No matching runs → returns []. Same contract as dimension 1: empty
    list signals the orchestrator never persisted runs for this thread_id;
    the caller (compare_pair) decides parity-row semantics."""
    from pathlib import Path
    from unittest.mock import MagicMock
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from parity_verify_a2a_vs_langgraph import fetch_agent_execution_order

    mock_client = MagicMock()
    mock_client.list_runs.return_value = iter([])

    for orchestrator in ("langgraph", "a2a"):
        result = fetch_agent_execution_order(
            thread_id="REQ-DOES-NOT-EXIST",
            orchestrator=orchestrator,
            langsmith_client=mock_client,
        )
        assert result == [], f"{orchestrator}: unknown thread_id must return []"


def test_dimension_2_agent_execution_order_invalid_orchestrator_raises():
    """Unknown orchestrator name → ValueError. The harness's caller passes
    the literal flag value being tested ("langgraph" vs "a2a"); anything
    else is a harness bug and should fail loudly."""
    from pathlib import Path
    from unittest.mock import MagicMock
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from parity_verify_a2a_vs_langgraph import fetch_agent_execution_order

    mock_client = MagicMock()
    with pytest.raises(ValueError, match="Unknown orchestrator"):
        fetch_agent_execution_order(
            thread_id="REQ-ANY",
            orchestrator="bogus",
            langsmith_client=mock_client,
        )


# ---------------------------------------------------------------------------
# Cycle 4 — dimension 3: approval_gate_triggers from approvals table
# Per ADR 0024 D4: approvals table joined on request_id. Same shape for
# both orchestrators (DB rows are written by ApprovalBridge which both
# orchestrators delegate to). Ordered list of approval_type strings.
# ---------------------------------------------------------------------------


async def test_dimension_3_approval_gate_triggers_returns_ordered_approval_types(clean_database):
    """fetch_approval_gate_triggers returns the ordered list of approval_type
    values for a given thread_id (== ResearchRequest.id), sorted by created_at.

    Approval rows are written by ApprovalBridge as the workflow hits HITL
    pause points. For Sprint 7.2 parity verification, same approval_type
    sequence == same HITL behavior regardless of orchestrator.
    """
    from datetime import datetime, timedelta
    from pathlib import Path
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from parity_verify_a2a_vs_langgraph import fetch_approval_gate_triggers

    from app.database import get_db_session
    from app.database.models import Approval, ResearchRequest

    request_id = "REQ-20260516-PARITYC4"
    base_ts = datetime(2026, 5, 16, 10, 0, 0)

    async with get_db_session() as session:
        # Parent request row (FK target)
        session.add(
            ResearchRequest(
                id=request_id,
                researcher_name="parity-harness-cycle4",
                researcher_email="cycle4@parity.test",
                initial_request="parity-harness cycle 4 synthetic row",
                current_state="complete",
            )
        )
        # 3 approval rows in workflow order
        session.add_all(
            [
                Approval(
                    request_id=request_id,
                    approval_type="requirements",
                    submitted_at=base_ts,
                    submitted_by="requirements_agent",
                    approval_data={},
                    created_at=base_ts,
                ),
                Approval(
                    request_id=request_id,
                    approval_type="phenotype_sql",
                    submitted_at=base_ts + timedelta(seconds=10),
                    submitted_by="phenotype_agent",
                    approval_data={},
                    created_at=base_ts + timedelta(seconds=10),
                ),
                Approval(
                    request_id=request_id,
                    approval_type="qa",
                    submitted_at=base_ts + timedelta(seconds=20),
                    submitted_by="qa_agent",
                    approval_data={},
                    created_at=base_ts + timedelta(seconds=20),
                ),
            ]
        )
        await session.commit()

        result = await fetch_approval_gate_triggers(thread_id=request_id, db_session=session)

    assert result == [
        "requirements",
        "phenotype_sql",
        "qa",
    ], "approval_type sequence must be returned in created_at ascending order"


async def test_dimension_3_approval_gate_triggers_returns_empty_for_unknown_thread(clean_database):
    """No approvals for this thread_id → []. Either the thread doesn't
    exist, or the workflow never hit a HITL pause point. Same [] contract
    as dimensions 1 and 2."""
    from pathlib import Path
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from parity_verify_a2a_vs_langgraph import fetch_approval_gate_triggers

    from app.database import get_db_session

    async with get_db_session() as session:
        result = await fetch_approval_gate_triggers(
            thread_id="REQ-DOES-NOT-EXIST", db_session=session
        )

    assert result == [], "unknown thread_id must return [] (not None, not raise)"


async def test_dimension_3_approval_gate_triggers_sorts_by_created_at_not_insertion_order(
    clean_database,
):
    """Rows inserted in non-chronological order are returned in
    chronological order via ORDER BY created_at — same defensive-sort
    pattern as dimension 1's state_history sort. Protects against future
    code paths that might insert approvals out of order (e.g., backfill
    scripts or async writes from agents racing the approval bridge).
    """
    from datetime import datetime, timedelta
    from pathlib import Path
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from parity_verify_a2a_vs_langgraph import fetch_approval_gate_triggers

    from app.database import get_db_session
    from app.database.models import Approval, ResearchRequest

    request_id = "REQ-20260516-PARITYC4SORT"
    base_ts = datetime(2026, 5, 16, 10, 0, 0)

    async with get_db_session() as session:
        session.add(
            ResearchRequest(
                id=request_id,
                researcher_name="parity-harness-cycle4-sort",
                researcher_email="cycle4sort@parity.test",
                initial_request="parity-harness cycle 4 out-of-order row",
                current_state="complete",
            )
        )
        # Insertion order intentionally NOT chronological
        session.add_all(
            [
                Approval(
                    request_id=request_id,
                    approval_type="qa",
                    submitted_at=base_ts + timedelta(seconds=20),
                    submitted_by="qa_agent",
                    approval_data={},
                    created_at=base_ts + timedelta(seconds=20),
                ),
                Approval(
                    request_id=request_id,
                    approval_type="requirements",
                    submitted_at=base_ts,
                    submitted_by="requirements_agent",
                    approval_data={},
                    created_at=base_ts,
                ),
                Approval(
                    request_id=request_id,
                    approval_type="phenotype_sql",
                    submitted_at=base_ts + timedelta(seconds=10),
                    submitted_by="phenotype_agent",
                    approval_data={},
                    created_at=base_ts + timedelta(seconds=10),
                ),
            ]
        )
        await session.commit()

        result = await fetch_approval_gate_triggers(thread_id=request_id, db_session=session)

    assert result == [
        "requirements",
        "phenotype_sql",
        "qa",
    ], "fetcher must sort by created_at ascending, not by insertion order"


# ---------------------------------------------------------------------------
# Cycle 5 — dimension 4: final_state classification
# Per ADR 0024 D4: SUCCESS / NEEDS_HUMAN_REVIEW / FAILED bucket per request.
# Bucket-level comparison (not raw current_state) so cross-orchestrator
# semantic equivalence holds (e.g., LangGraph's `complete` == A2A's
# `delivered` both = SUCCESS).
# ---------------------------------------------------------------------------


async def test_dimension_4_final_state_returns_success_for_complete(clean_database):
    """`current_state='complete'` (LangGraph's terminal SUCCESS) classifies
    into the SUCCESS bucket. Tracer bullet for the dimension-4 fetcher +
    classifier shape.
    """
    from pathlib import Path
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from parity_verify_a2a_vs_langgraph import fetch_final_state_bucket

    from app.database import get_db_session
    from app.database.models import ResearchRequest

    request_id = "REQ-20260516-PARITYC5"

    async with get_db_session() as session:
        session.add(
            ResearchRequest(
                id=request_id,
                researcher_name="parity-harness-cycle5",
                researcher_email="cycle5@parity.test",
                initial_request="parity-harness cycle 5 synthetic row",
                current_state="complete",
            )
        )
        await session.commit()

        result = await fetch_final_state_bucket(thread_id=request_id, db_session=session)

    assert result == "SUCCESS", "current_state='complete' must classify as SUCCESS"


async def test_dimension_4_final_state_classifies_other_terminal_buckets(clean_database):
    """The classifier handles all 3 named buckets per ADR 0024 D4:
    SUCCESS, NEEDS_HUMAN_REVIEW, FAILED. Cross-orchestrator parity requires
    that A2A's historical `delivered` terminal maps to the same SUCCESS
    bucket as LangGraph's `complete` — otherwise old A2A rows and new
    LangGraph rows would never compare equal in dimension 4.
    """
    from pathlib import Path
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from parity_verify_a2a_vs_langgraph import fetch_final_state_bucket

    from app.database import get_db_session
    from app.database.models import ResearchRequest

    cases = [
        # (request_id_suffix, current_state, expected_bucket, reason)
        ("HR", "human_review", "NEEDS_HUMAN_REVIEW", "LangGraph escalation terminal"),
        ("QF", "qa_failed", "FAILED", "LangGraph QA-failure terminal"),
        ("ERR", "error", "FAILED", "A2A error terminal (historical)"),
        (
            "DEL",
            "delivered",
            "SUCCESS",
            "A2A historical SUCCESS — must match LangGraph's `complete`",
        ),
        ("NF", "not_feasible", "SUCCESS", "LangGraph cohort-too-small (workflow ran normally)"),
    ]

    async with get_db_session() as session:
        for suffix, current_state, _, _ in cases:
            session.add(
                ResearchRequest(
                    id=f"REQ-20260516-PARITYC5{suffix}",
                    researcher_name="parity-harness-cycle5b",
                    researcher_email="cycle5b@parity.test",
                    initial_request=f"parity-harness cycle 5b synthetic row ({current_state})",
                    current_state=current_state,
                )
            )
        await session.commit()

        for suffix, _, expected_bucket, reason in cases:
            result = await fetch_final_state_bucket(
                thread_id=f"REQ-20260516-PARITYC5{suffix}", db_session=session
            )
            assert result == expected_bucket, f"{reason}: expected {expected_bucket}, got {result}"


async def test_dimension_4_final_state_in_progress_for_non_terminal(clean_database):
    """A row in a non-terminal state classifies as IN_PROGRESS. The harness
    is supposed to read AFTER all 30 drives finish; if any row is still
    mid-flight, the parity report should surface that (the comparison will
    still work — both orchestrators must reach the same bucket — but
    IN_PROGRESS is itself a useful diagnostic signal).
    """
    from pathlib import Path
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from parity_verify_a2a_vs_langgraph import fetch_final_state_bucket

    from app.database import get_db_session
    from app.database.models import ResearchRequest

    request_id = "REQ-20260516-PARITYC5MID"

    async with get_db_session() as session:
        session.add(
            ResearchRequest(
                id=request_id,
                researcher_name="parity-harness-cycle5c",
                researcher_email="cycle5c@parity.test",
                initial_request="parity-harness cycle 5c mid-flight row",
                current_state="phenotype_review",  # Non-terminal HITL pause
            )
        )
        await session.commit()

        result = await fetch_final_state_bucket(thread_id=request_id, db_session=session)

    assert result == "IN_PROGRESS", "non-terminal current_state must classify as IN_PROGRESS"


async def test_dimension_4_final_state_returns_none_for_unknown_thread(clean_database):
    """No row for thread_id → None. Unlike dimensions 1-3 (which return [])
    dimension 4 returns a single string-or-None. compare_pair handles both
    shapes via raw equality."""
    from pathlib import Path
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from parity_verify_a2a_vs_langgraph import fetch_final_state_bucket

    from app.database import get_db_session

    async with get_db_session() as session:
        result = await fetch_final_state_bucket(thread_id="REQ-DOES-NOT-EXIST", db_session=session)

    assert result is None, "unknown thread_id must return None (not raise, not 'UNKNOWN')"


# ---------------------------------------------------------------------------
# Cycle 6 — dimension 5: audit_trail_shape from audit_logs
# Per ADR 0024 D4: audit_logs grouped by thread_id (request_id). Same shape
# for both orchestrators because audit rows are written by the shared
# Sprint 6.1 audit middleware. Ordered list of event_type strings sorted
# by timestamp ascending.
# ---------------------------------------------------------------------------


async def test_dimension_5_audit_trail_shape_returns_ordered_event_types(clean_database):
    """fetch_audit_trail_shape returns the ordered list of event_type
    strings for a given thread_id (== request_id on AuditLog).

    Audit rows are written by the Sprint 6.1 audit middleware (Redis-queue
    pipeline). Sort by timestamp ascending — workflow-chronological order.
    Same query for both orchestrators since the audit pipeline is shared.
    """
    from datetime import datetime, timedelta
    from pathlib import Path
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from parity_verify_a2a_vs_langgraph import fetch_audit_trail_shape

    from app.database import get_db_session
    from app.database.models import AuditLog, ResearchRequest

    request_id = "REQ-20260516-PARITYC6"
    base_ts = datetime(2026, 5, 16, 10, 0, 0)

    async with get_db_session() as session:
        session.add(
            ResearchRequest(
                id=request_id,
                researcher_name="parity-harness-cycle6",
                researcher_email="cycle6@parity.test",
                initial_request="parity-harness cycle 6 synthetic row",
                current_state="complete",
            )
        )
        # Synthetic audit trail: workflow-relevant events for one request
        session.add_all(
            [
                AuditLog(
                    timestamp=base_ts,
                    request_id=request_id,
                    event_type="REQUEST_CREATE",
                    phi_accessed=False,
                ),
                AuditLog(
                    timestamp=base_ts + timedelta(seconds=5),
                    request_id=request_id,
                    event_type="AGENT_STARTED",
                    phi_accessed=False,
                ),
                AuditLog(
                    timestamp=base_ts + timedelta(seconds=20),
                    request_id=request_id,
                    event_type="QUERY_EXECUTE",
                    phi_accessed=True,
                ),
                AuditLog(
                    timestamp=base_ts + timedelta(seconds=30),
                    request_id=request_id,
                    event_type="DATA_DELIVER",
                    phi_accessed=True,
                ),
            ]
        )
        await session.commit()

        result = await fetch_audit_trail_shape(thread_id=request_id, db_session=session)

    assert result == [
        "REQUEST_CREATE",
        "AGENT_STARTED",
        "QUERY_EXECUTE",
        "DATA_DELIVER",
    ], "audit event_type sequence must be returned in timestamp ascending order"


async def test_dimension_5_audit_trail_shape_returns_empty_for_unknown_thread(clean_database):
    """No audit rows for this thread_id → []. Same [] contract as
    dimensions 1, 2, 3. Could indicate: (a) workflow never fired events
    (broken audit middleware integration), (b) thread_id doesn't exist,
    or (c) thread is still mid-flight with no audit events yet."""
    from pathlib import Path
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from parity_verify_a2a_vs_langgraph import fetch_audit_trail_shape

    from app.database import get_db_session

    async with get_db_session() as session:
        result = await fetch_audit_trail_shape(thread_id="REQ-DOES-NOT-EXIST", db_session=session)

    assert result == [], "unknown thread_id must return [] (not None, not raise)"


# ---------------------------------------------------------------------------
# Cycle 7 — bounded-vs-blocking severity classifier
# Per ADR 0024 D4c: when langgraph != a2a, evaluate the diff against
# per-dimension permitted-diff rules. Rule fires → severity='bounded'
# (acceptable per close-ADR documentation). No rule fires → severity=
# 'blocking' (sprint cannot close until rationalized).
# ---------------------------------------------------------------------------


def test_compare_pair_classifies_diff_as_bounded_when_dimension_rule_fires():
    """Cycle 7 tracer: the bounded-rules registry is the extension point.
    Each dimension can register one or more rules; if any rule fires on a
    mismatch, severity is 'bounded' (with the rule's rationale as diff).

    Test injects a custom rule dict (override of production
    BOUNDED_DIFF_RULES) to avoid coupling the test to whatever rules are
    actually registered in production. Proves the dispatcher works without
    needing a concrete production rule to exist yet.
    """
    from pathlib import Path
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from parity_verify_a2a_vs_langgraph import compare_pair

    # Custom rule that always fires with a known rationale
    custom_rules = {
        "fake_dim": [lambda lg, a2a: "test-only rule fired (cycle 7a tracer)"],
    }

    row = compare_pair(
        thread_id="REQ-7A",
        dimension="fake_dim",
        langgraph=[1, 2, 3],
        a2a=[4, 5, 6],
        bounded_rules=custom_rules,
    )

    assert row.match is False, "values genuinely differ"
    assert row.severity == "bounded", "rule fired → bounded, not blocking"
    assert row.diff == "test-only rule fired (cycle 7a tracer)"


def test_compare_pair_state_sequence_preview_qa_substitution_is_bounded():
    """ADR 0024 D4c concrete example: LangGraph's `preview_qa_review` state
    is semantically equivalent to A2A's two-state `preview_qa` → `qa_review`
    subsequence. Same gate fires (preview QA review by an informatician),
    different state names per orchestrator. Should classify as bounded,
    not blocking, when this is the only difference.
    """
    from pathlib import Path
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from parity_verify_a2a_vs_langgraph import compare_pair

    lg_seq = [
        "new_request",
        "requirements_review",
        "preview_qa_review",
        "data_extraction",
        "complete",
    ]
    a2a_seq = [
        "new_request",
        "requirements_review",
        "preview_qa",
        "qa_review",
        "data_extraction",
        "complete",
    ]

    row = compare_pair(
        thread_id="REQ-7B",
        dimension="state_sequence",
        langgraph=lg_seq,
        a2a=a2a_seq,
    )

    assert row.match is False, "raw sequences differ in length and content"
    assert (
        row.severity == "bounded"
    ), "preview_qa substitution is semantically equivalent per ADR 0024 D4c"
    assert "preview_qa" in row.diff, "diff message must name the substitution"
    assert (
        "ADR 0024" in row.diff or "same gate" in row.diff
    ), "diff must explain why this is bounded"


def test_compare_pair_random_diff_remains_blocking():
    """Negative regression: when the mismatch isn't a known equivalence
    pattern, severity must stay 'blocking'. The cycle 7b rule for
    state_sequence must NOT accidentally classify unrelated diffs as
    bounded. Preserves the Sprint 7.2 close-gate semantics: 0 blocking
    rows required to ship.
    """
    from pathlib import Path
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from parity_verify_a2a_vs_langgraph import compare_pair

    # Genuinely-different terminal states — no known equivalence
    row = compare_pair(
        thread_id="REQ-7C",
        dimension="state_sequence",
        langgraph=["new_request", "complete"],
        a2a=["new_request", "qa_failed"],
    )

    assert row.match is False
    assert (
        row.severity == "blocking"
    ), "no rule applies to complete-vs-qa_failed; must stay blocking"
    assert "Raw values differ" in row.diff

    # And: a dimension with no rules registered → mismatch is blocking
    row2 = compare_pair(
        thread_id="REQ-7C-DIM4",
        dimension="final_state",
        langgraph="SUCCESS",
        a2a="FAILED",
    )

    assert row2.match is False
    assert row2.severity == "blocking", "no rules registered for final_state yet → blocking"


# ---------------------------------------------------------------------------
# Cycle 8 — driver: orchestrate all 5 dimensions across thread_id pairs,
# emit JSONL report, return aggregate summary.
# Subprocess plumbing to drive_qa_traffic.py lives in the script's __main__
# block (operational glue, not unit-tested).
# ---------------------------------------------------------------------------


async def test_run_parity_verification_emits_5_rows_per_pair_all_matching(clean_database, tmp_path):
    """Cycle 8 tracer: given one (lg_thread_id, a2a_thread_id) pair with
    matching evidence across all 5 dimensions, the driver should:
    - emit exactly 5 JSONL rows (one per dimension)
    - return {"match": 5, "bounded": 0, "blocking": 0}
    - cover all 5 dimension names in the rows
    """
    from datetime import datetime, timedelta
    from pathlib import Path
    from unittest.mock import MagicMock
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from parity_verify_a2a_vs_langgraph import run_parity_verification

    from app.database import get_db_session
    from app.database.models import ResearchRequest

    base_ts = datetime(2026, 5, 16, 10, 0, 0)
    state_history = [
        {"state": "new_request", "timestamp": base_ts.isoformat()},
        {"state": "complete", "timestamp": (base_ts + timedelta(seconds=10)).isoformat()},
    ]

    async with get_db_session() as session:
        # Two synthetic rows representing the "same input" processed by
        # each orchestrator. Same state_history → dim 1 matches. Same
        # current_state → dim 4 matches. No approvals → dim 3 matches
        # ([] vs []). No audit_logs → dim 5 matches.
        for rid in ("REQ-LG-CYCLE8", "REQ-A2A-CYCLE8"):
            session.add(
                ResearchRequest(
                    id=rid,
                    researcher_name="parity-harness-cycle8",
                    researcher_email="cycle8@parity.test",
                    initial_request="parity-harness cycle 8 synthetic row",
                    current_state="complete",
                    state_history=state_history,
                )
            )
        await session.commit()

        # Mock LangSmith returning no runs → dim 2 [] vs [] → matches
        mock_client = MagicMock()
        mock_client.list_runs.return_value = iter([])

        output_path = tmp_path / "parity.jsonl"
        summary = await run_parity_verification(
            thread_pairs=[("REQ-LG-CYCLE8", "REQ-A2A-CYCLE8")],
            db_session=session,
            langsmith_client=mock_client,
            output_path=output_path,
        )

    assert summary == {
        "match": 5,
        "bounded": 0,
        "blocking": 0,
    }, "all 5 dimensions should match for synthetic-identical pair"

    raw = output_path.read_text().strip().splitlines()
    assert len(raw) == 5, "exactly 5 JSONL rows (one per dimension)"

    rows = [json.loads(line) for line in raw]
    assert {r["dimension"] for r in rows} == {
        "state_sequence",
        "agent_execution_order",
        "approval_gate_triggers",
        "final_state",
        "audit_trail_shape",
    }, "all 5 dimensions must appear"
    assert all(r["match"] is True for r in rows), "all rows should be match=True"
    assert all(r["severity"] is None for r in rows), "matched rows have null severity"


async def test_run_parity_verification_aggregates_mixed_outcomes_across_pairs(
    clean_database, tmp_path
):
    """Two pairs: one all-matching, one with divergent final_state.
    Driver should emit 10 rows total (5 dims × 2 pairs), and summary
    should aggregate counts across all pairs.

    Pair 1: both rows have current_state='complete' → all 5 dims match
    Pair 2: lg row 'complete', a2a row 'qa_failed' → 4 dims match
            (state_sequence, agent, approval, audit all []==[] or
            same-shape); dim 4 final_state diverges SUCCESS vs FAILED →
            severity='blocking' (no bounded rule for final_state)
    """
    from datetime import datetime, timedelta
    from pathlib import Path
    from unittest.mock import MagicMock
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from parity_verify_a2a_vs_langgraph import run_parity_verification

    from app.database import get_db_session
    from app.database.models import ResearchRequest

    base_ts = datetime(2026, 5, 16, 10, 0, 0)

    # Pair 1: all matching
    pair1_history = [
        {"state": "new_request", "timestamp": base_ts.isoformat()},
        {"state": "complete", "timestamp": (base_ts + timedelta(seconds=10)).isoformat()},
    ]
    # Pair 2: A2A also has 'qa_failed' state_history + current_state to match
    # state_history vs final_state divergence creates a single blocking row
    # (state_sequence and final_state both differ for pair 2)
    pair2_lg_history = [
        {"state": "new_request", "timestamp": base_ts.isoformat()},
        {"state": "complete", "timestamp": (base_ts + timedelta(seconds=10)).isoformat()},
    ]
    pair2_a2a_history = [
        {"state": "new_request", "timestamp": base_ts.isoformat()},
        {"state": "qa_failed", "timestamp": (base_ts + timedelta(seconds=10)).isoformat()},
    ]

    async with get_db_session() as session:
        session.add(
            ResearchRequest(
                id="REQ-LG-CYCLE8B-P1",
                researcher_name="cycle8b",
                researcher_email="cycle8b@parity.test",
                initial_request="cycle 8b pair 1 lg",
                current_state="complete",
                state_history=pair1_history,
            )
        )
        session.add(
            ResearchRequest(
                id="REQ-A2A-CYCLE8B-P1",
                researcher_name="cycle8b",
                researcher_email="cycle8b@parity.test",
                initial_request="cycle 8b pair 1 a2a",
                current_state="complete",
                state_history=pair1_history,
            )
        )
        session.add(
            ResearchRequest(
                id="REQ-LG-CYCLE8B-P2",
                researcher_name="cycle8b",
                researcher_email="cycle8b@parity.test",
                initial_request="cycle 8b pair 2 lg",
                current_state="complete",
                state_history=pair2_lg_history,
            )
        )
        session.add(
            ResearchRequest(
                id="REQ-A2A-CYCLE8B-P2",
                researcher_name="cycle8b",
                researcher_email="cycle8b@parity.test",
                initial_request="cycle 8b pair 2 a2a",
                current_state="qa_failed",
                state_history=pair2_a2a_history,
            )
        )
        await session.commit()

        mock_client = MagicMock()
        mock_client.list_runs.return_value = iter([])

        output_path = tmp_path / "parity.jsonl"
        summary = await run_parity_verification(
            thread_pairs=[
                ("REQ-LG-CYCLE8B-P1", "REQ-A2A-CYCLE8B-P1"),
                ("REQ-LG-CYCLE8B-P2", "REQ-A2A-CYCLE8B-P2"),
            ],
            db_session=session,
            langsmith_client=mock_client,
            output_path=output_path,
        )

    # Pair 1: 5 matches.
    # Pair 2: dims 2,3,5 still match (LangSmith empty, no approvals, no audit).
    #         dim 1 differs (state_sequence ends differently).
    #         dim 4 differs (final_state SUCCESS vs FAILED).
    # Total: 5+3 = 8 matches, 0 bounded, 2 blocking.
    assert summary == {
        "match": 8,
        "bounded": 0,
        "blocking": 2,
    }, f"expected 8 match + 2 blocking, got {summary}"

    raw = output_path.read_text().strip().splitlines()
    assert len(raw) == 10, "5 dims × 2 pairs = 10 rows"

    # Verify the blocking rows are dim 1 and dim 4 of pair 2
    rows = [json.loads(line) for line in raw]
    blocking_rows = [r for r in rows if r["severity"] == "blocking"]
    assert len(blocking_rows) == 2
    assert {r["dimension"] for r in blocking_rows} == {
        "state_sequence",
        "final_state",
    }, "blocking rows are state_sequence and final_state divergences in pair 2"
    assert all(
        r["thread_id"] == "REQ-LG-CYCLE8B-P2" for r in blocking_rows
    ), "row.thread_id uses LangGraph id (orchestrator under test)"
