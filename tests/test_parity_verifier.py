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
