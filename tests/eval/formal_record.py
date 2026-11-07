"""#239: record and replay for the formal gold set.

record: each approved case's request goes through the live Requirements
Agent (the formal-portal path, from_formal_portal=True), exactly as a real
request does. Its structured requirements are saved to a fixture, then
scored. Needs ANTHROPIC_API_KEY and running HAPI; makes billed calls.

replay: loads the recorded requirements (no API key) and scores them against
whatever HAPI is up. This is what CI runs.

Only cases whose oracle an informatician approved (signoff == "approved")
are recorded or scored.
"""

import json
import re
import subprocess  # nosec B404 - fixed git command, no input
from pathlib import Path
from typing import Dict, List, Optional

from tests.eval.formal_cases import FORMAL_CASES, FormalCase
from tests.eval.formal_harness import CaseScore, pass_at_1, score_case, write_jsonl

RECORDING = Path(__file__).parent / "fixtures" / "recorded_requirements_formal.json"


def approved_cases() -> List[FormalCase]:
    return [c for c in FORMAL_CASES if c.signoff == "approved"]


def load_recording(path: Path = RECORDING) -> Dict[str, Dict]:
    return json.loads(path.read_text()) if path.exists() else {}


def _commit() -> str:
    return subprocess.run(  # nosec B603 B607
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()


async def _requirements_from_agent(case: FormalCase) -> Dict:
    from app.agents.requirements_agent import RequirementsAgent

    result = await RequirementsAgent().execute_task(
        "gather_requirements",
        {
            "request_id": f"GOLD-{case.id}",
            "initial_request": case.request["initial_request"],
            "from_formal_portal": True,
            "researcher_info": {
                "name": "Gold Set",
                "email": "gold-set@example.test",
                "irb_number": "IRB-GOLD-0001",
                "structured_requirements": case.request["structured_requirements"],
            },
        },
    )
    return result["structured_requirements"]


def touched_views(case: FormalCase, requirements: Dict) -> set:
    """The sqlonfhir views the case's generated SQL and oracle read."""
    from app.utils.sql_generator import SQLGenerator

    sql, _ = SQLGenerator(use_materialized_views=True).generate_phenotype_sql(
        requirements, count_only=False
    )
    return set(re.findall(r"sqlonfhir\.(\w+)", sql + case.oracle_sql))


async def _score_all(recording: Dict[str, Dict], evidence: Path) -> List[CaseScore]:
    cases = approved_cases()
    scores = [await score_case(c, recording[c.id]) for c in cases]
    views = set().union(*(touched_views(c, recording[c.id]) for c in cases)) if cases else set()
    write_jsonl(scores, evidence, commit=_commit(), batch_anchor_ts=await _batch_anchor_ts(views))
    return scores


async def _batch_anchor_ts(views: set) -> Optional[str]:
    """MAX(refreshed_at) over the views the cases read (ADR 0027's batch_anchor_ts)."""
    from app.adapters.sql_on_fhir import SQLonFHIRAdapter

    try:
        [row] = await SQLonFHIRAdapter().execute_sql(
            "SELECT max(refreshed_at) AS ts FROM sqlonfhir.mv_refresh_metadata"
            " WHERE view_name = ANY(:views)",
            {"views": sorted(views)},
        )
    except Exception:  # nosec B110 - the anchor is citation metadata; absent is recorded as None
        return None
    return row["ts"].isoformat() if row["ts"] else None


async def record(evidence: Path) -> List[CaseScore]:
    from app.database import init_db

    await init_db()  # the agent saves requirements to the app DB
    recording = {c.id: await _requirements_from_agent(c) for c in approved_cases()}
    RECORDING.parent.mkdir(parents=True, exist_ok=True)
    RECORDING.write_text(json.dumps(recording, indent=2, sort_keys=True, default=str) + "\n")
    return await _score_all(recording, evidence)


async def replay(evidence: Path) -> List[CaseScore]:
    return await _score_all(load_recording(), evidence)


def summary(scores: List[CaseScore]) -> str:
    lines = [f"Pass@1: {pass_at_1(scores):.2f} ({sum(s.passed for s in scores)}/{len(scores)})"]
    for s in scores:
        state = "PASS" if s.passed else ("VACUOUS" if s.vacuous else "FAIL")
        lines.append(
            f"  {s.id}: {state} sql={s.sql_count} oracle={s.oracle_count} mismatch={s.mismatch}"
            + (f" ref={s.error_ref}" if s.error_ref else "")
        )
    return "\n".join(lines)
