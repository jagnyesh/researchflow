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
