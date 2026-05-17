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
# Cycle 3 — dimension 2: agent_execution_order from LangSmith
# Per-orchestrator query branch (ADR 0024 D4 pre-flight result):
#   LangGraph: execute_task chain spans filtered by thread_id, sorted by
#              start_time, agent name pulled from `agent=*-agent` tag
#   A2A: is_root=True chain runs filtered by thread_id, sorted by start_time,
#        names pulled from run.name (RequirementsAgent / PhenotypeAgent / ...)
# ---------------------------------------------------------------------------


def _extract_thread_id_from_run(run: Any) -> Optional[str]:
    """LangGraph sets thread_id in run metadata. Tolerates test doubles that
    expose `metadata` directly on the object (rather than via `extra`).
    Mirrors the same helper in app/services/cost_telemetry_service.py."""
    metadata = getattr(run, "metadata", None) or {}
    if isinstance(metadata, dict):
        return metadata.get("thread_id") or metadata.get("langgraph_thread_id")
    return None


def _extract_agent_name_from_tags(run: Any) -> Optional[str]:
    """Pull agent name from a tag of the form `agent=requirements-agent`."""
    tags = getattr(run, "tags", None) or []
    for tag in tags:
        if isinstance(tag, str) and tag.startswith("agent="):
            return tag.split("=", 1)[1]
    return None


def fetch_agent_execution_order(
    thread_id: str,
    orchestrator: str,
    langsmith_client: Any,
    project_name: str = "researchflow-production",
) -> List[str]:
    """Return ordered agent invocation names for `thread_id` from LangSmith.

    Per ADR 0024 D4: each orchestrator carries the same dimension-2 signal
    (which agents ran, in what order) but in different trace shapes. The
    pre-flight check (re-confirmed 2026-05-15) verified LangSmith retention
    covers both eras.

    Dispatches on `orchestrator`:
    - `"langgraph"` — query for runs tagged `portal:formal`, filter to
      `execute_task` chain spans matching `thread_id`, sort by start_time,
      extract agent name from `agent=*-agent` tag
    - `"a2a"` — query for is_root=True runs matching `thread_id`, sort by
      start_time, return run.name verbatim

    Returns [] if no matching runs (caller decides parity-row vs harness
    error semantics).
    """
    if orchestrator == "langgraph":
        runs_iter = langsmith_client.list_runs(
            project_name=project_name,
            filter='has(tags, "portal:formal")',
        )
        matching = [
            r
            for r in runs_iter
            if _extract_thread_id_from_run(r) == thread_id
            and getattr(r, "name", None) == "execute_task"
            and getattr(r, "run_type", None) == "chain"
        ]
        matching.sort(key=lambda r: getattr(r, "start_time", None) or 0)
        return [
            name
            for name in (_extract_agent_name_from_tags(r) for r in matching)
            if name is not None
        ]
    elif orchestrator == "a2a":
        # A2A trace shape: each agent invocation is its own ROOT chain run.
        # State-transition logic (WorkflowEngine.determine_next_step) is NOT
        # @traceable, so we only see the agent calls themselves as
        # disconnected roots. Filter by thread_id, exclude llm-typed roots
        # (no agent calls invoke @traceable at the LLM layer in A2A), sort
        # by start_time.
        runs_iter = langsmith_client.list_runs(
            project_name=project_name,
            is_root=True,
        )
        matching = [
            r
            for r in runs_iter
            if _extract_thread_id_from_run(r) == thread_id
            and getattr(r, "run_type", None) == "chain"
        ]
        matching.sort(key=lambda r: getattr(r, "start_time", None) or 0)
        return [getattr(r, "name", "") for r in matching]
    else:
        raise ValueError(f"Unknown orchestrator: {orchestrator!r}")


# ---------------------------------------------------------------------------
# Cycles 4-6 (TBD): one dimension query per cycle
# Cycle 7 (TBD): bounded-vs-blocking severity classifier
# Cycle 8 (driver): subprocess plumbing for 30-request drive per flag value
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    # Driver entry point (Cycle 8). For Cycle 1, just confirm the module imports.
    print("Sprint 7.2 Phase 1 parity verifier — driver not yet wired (Cycle 8).")
