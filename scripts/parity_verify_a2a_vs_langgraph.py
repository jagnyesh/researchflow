#!/usr/bin/env python3
"""Sprint 7.2 Phase 1 — A2A vs LangGraph structural-parity verification harness.

Drives 30 formal-portal requests through each USE_LANGGRAPH_WORKFLOW value
(false=A2A, true=LangGraph), captures evidence from three signal sources
(DB, LangSmith, audit_logs) per the D4a hybrid methodology, and emits a
JSONL report with bounded/blocking severity per comparison row.

Sprint 7.2 close gate: 0 rows with severity=blocking.

One-shot tool. Deleted at sprint close per the migration-helper pattern
(precedent: scripts/migrate_to_langgraph.py deleted in Phase 6c).

Per D4a, five structural-parity dimensions:
  1. state_sequence       — research_requests.state_history JSON
  2. agent_execution_order — LangSmith trace (per-orchestrator branch)
  3. approval_gate_triggers — approvals table join
  4. final_state          — research_requests.current_state + final_state
  5. audit_trail_shape    — audit_logs grouped by thread_id

Output schema per D4c (self-describing JSONL):
  {"thread_id": "...", "dimension": "...",
   "langgraph": <value>, "a2a": <value>,
   "match": true|false, "severity": null|"bounded"|"blocking",
   "diff": null|"<rationale>"}

Pre-flight check (re-confirmed 2026-05-15): LangSmith retention covers both
LangGraph (Sprint 8.4 era) and A2A (2026-05-04 era) traces. Dimension 2
query is per-orchestrator-branched: LangGraph reads tree-walk depth-1
children; A2A reads sibling roots sorted by start_time, filtered by
metadata.thread_id.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, List, Literal, Optional


# ---------------------------------------------------------------------------
# Schema (D4c)
# ---------------------------------------------------------------------------


Severity = Literal["bounded", "blocking"]


@dataclass
class ParityRow:
    """A single (thread_id, dimension) comparison row.

    Self-describing per D4c: a reader can verify the match assessment by
    inspecting `langgraph` and `a2a` raw values directly. Severity encoding
    makes the bounded-vs-blocking rule from the original ADR concrete and
    harness-enforced.
    """

    thread_id: str
    dimension: str
    langgraph: Any
    a2a: Any
    match: bool
    severity: Optional[Severity] = None
    diff: Optional[str] = None


# ---------------------------------------------------------------------------
# Cycle 1 — tracer bullet: compare_pair + JSONL writer
# ---------------------------------------------------------------------------


def compare_pair(
    thread_id: str,
    dimension: str,
    langgraph: Any,
    a2a: Any,
) -> ParityRow:
    """Build a ParityRow comparing one dimension's evidence between the two
    orchestrators.

    For Cycle 1 (tracer bullet): simple equality comparison. Bounded-vs-
    blocking classification rules (cycle 7) will extend this with per-
    dimension permitted-diff lists.
    """
    matched = langgraph == a2a
    return ParityRow(
        thread_id=thread_id,
        dimension=dimension,
        langgraph=langgraph,
        a2a=a2a,
        match=matched,
        severity=None if matched else "blocking",
        diff=None if matched else f"Raw values differ at dimension {dimension!r}",
    )


def write_jsonl_row(row: ParityRow, log_path: Path) -> None:
    """Append one ParityRow as a JSON line.

    Parent dir created if absent. JSON-serialized via dataclasses.asdict so
    every field is self-describing in the output line.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a") as f:
        f.write(json.dumps(asdict(row)) + "\n")


# ---------------------------------------------------------------------------
# Cycle 2 — dimension 1: state_sequence query
# ---------------------------------------------------------------------------


async def fetch_state_sequence(thread_id: str, db_session) -> List[str]:
    """Return ordered state names from `research_requests.state_history` for the
    row identified by `thread_id`.

    LangGraph's checkpointer sets `thread_id == request_id` per workflow
    invocation; `ResearchRequest.id` (String PK, `REQ-YYYYMMDD-XXXXXXXX`
    format) is the lookup key for both orchestrators.

    `state_history` is a JSON list of `{"state": <name>, "timestamp": <ISO>}`
    entries persisted chronologically as the workflow progresses. This
    fetcher sorts by `timestamp` ascending defensively (don't rely on file
    order — clock skew, backfill scripts, or future code paths could append
    out of order).

    Returns `[]` if no row matches `thread_id`. The caller (compare_pair)
    decides whether `[]` is a parity-row signal (orchestrator never
    persisted) or a harness error.
    """
    from sqlalchemy import select

    from app.database.models import ResearchRequest

    result = await db_session.execute(
        select(ResearchRequest.state_history).where(ResearchRequest.id == thread_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return []
    entries = row if isinstance(row, list) else json.loads(row)
    entries = sorted(entries, key=lambda e: e.get("timestamp", ""))
    return [e["state"] for e in entries]


# ---------------------------------------------------------------------------
# Cycles 3-6 (TBD): one dimension query per cycle
# Cycle 7 (TBD): bounded-vs-blocking severity classifier
# Cycle 8 (driver): subprocess plumbing for 30-request drive per flag value
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    # Driver entry point (Cycle 8). For Cycle 1, just confirm the module imports.
    print("Sprint 7.2 Phase 1 parity verifier — driver not yet wired (Cycle 8).")
