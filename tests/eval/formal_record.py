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
import logging
import re
import subprocess  # nosec B404 - fixed git command, no input
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.schemas._errors import log_internal_error

from tests.eval.formal_cases import FORMAL_CASES, FormalCase
from tests.eval.formal_harness import CaseScore, cost_summary, pass_at_1, score_case, write_jsonl
from tests.eval.harness import _trace_costs

logger = logging.getLogger(__name__)

RECORDING = Path(__file__).parent / "fixtures" / "recorded_requirements_formal.json"


def approved_cases() -> List[FormalCase]:
    return [c for c in FORMAL_CASES if c.signoff == "approved"]


def _entries(path: Optional[Path]) -> Dict[str, Tuple[Dict, Optional[float]]]:
    """{case id: (requirements, cost_usd)}. Reads the #243 {requirements,
    cost_usd} entries and the older requirements-only ones (cost unknown)."""
    path = path or RECORDING
    if not path.exists():
        return {}
    out = {}
    for case_id, entry in json.loads(path.read_text()).items():
        if set(entry) == {"requirements", "cost_usd"}:
            out[case_id] = (entry["requirements"], entry["cost_usd"])
        else:
            out[case_id] = (entry, None)
    return out


def load_recording(path: Optional[Path] = None) -> Dict[str, Dict]:
    return {case_id: req for case_id, (req, _) in _entries(path).items()}


def load_costs(path: Optional[Path] = None) -> Dict[str, Optional[float]]:
    return {case_id: cost for case_id, (_, cost) in _entries(path).items()}


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

    try:
        sql, _ = SQLGenerator(use_materialized_views=True).generate_phenotype_sql(
            requirements, count_only=False
        )
    except ValueError:
        # score_case records this as a failed case; the oracle still anchors it.
        sql = ""
    return set(re.findall(r"sqlonfhir\.(\w+)", sql + case.oracle_sql))


async def _score_all(
    recording: Dict[str, Dict], costs: Dict[str, Optional[float]], evidence: Path
) -> List[CaseScore]:
    cases = approved_cases()
    scores = [await score_case(c, recording[c.id]) for c in cases]
    for score in scores:
        score.cost_usd = costs.get(score.id)
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

    from langsmith import trace

    await init_db()  # the agent saves requirements to the app DB
    recording, run_ids = {}, {}
    for case in approved_cases():
        # One trace per case, so every LLM run it triggers is priced together (#243).
        run_ids[case.id] = str(uuid.uuid4())
        with trace(
            name="formal_gold_case",
            run_type="chain",
            run_id=run_ids[case.id],
            tags=["eval", "portal:formal", case.id],
        ):
            recording[case.id] = await _requirements_from_agent(case)
    try:
        costs = await _trace_costs(run_ids)
    except Exception as exc:
        # The agent calls are already billed; keep their requirements, unpriced.
        log_internal_error(logger, "Pricing the gold-set traces failed", exc)
        costs = {}
    entries = {i: {"requirements": req, "cost_usd": costs.get(i)} for i, req in recording.items()}
    RECORDING.parent.mkdir(parents=True, exist_ok=True)
    RECORDING.write_text(json.dumps(entries, indent=2, sort_keys=True, default=str) + "\n")
    return await _score_all(recording, costs, evidence)


async def replay(evidence: Path) -> List[CaseScore]:
    return await _score_all(load_recording(), load_costs(), evidence)


def summary(scores: List[CaseScore]) -> str:
    lines = [f"Pass@1: {pass_at_1(scores):.2f} ({sum(s.passed for s in scores)}/{len(scores)})"]
    reasons = {c.id: c.expected_fail for c in FORMAL_CASES}
    for s in scores:
        reason = reasons.get(s.id, "")
        if reason:
            # Counted as a fail in Pass@1, listed with why (#241).
            state = "UNEXPECTED-PASS" if s.passed else f"EXPECTED-FAIL ({reason})"
        else:
            state = "PASS" if s.passed else ("VACUOUS" if s.vacuous else "FAIL")
        lines.append(
            f"  {s.id}: {state} sql={s.sql_count} oracle={s.oracle_count} mismatch={s.mismatch}"
            + ("" if s.cost_usd is None else f" cost=${s.cost_usd:.6f}")
            + (f" ref={s.error_ref}" if s.error_ref else "")
        )
    costs = cost_summary(scores)
    median, per_pass = costs["median_cost_per_attempt_usd"], costs["cost_per_passing_sql_usd"]
    priced = sum(s.cost_usd is not None for s in scores)
    lines.append(f"priced attempts: {priced}/{len(scores)}")
    if median is None:
        lines += ["median cost per attempt: unknown", "cost per passing SQL: unknown"]
    else:
        lines.append(f"median cost per attempt: ${median:.6f}")
        lines.append(
            "cost per passing SQL: undefined (Pass@1 = 0)"
            if per_pass is None
            else f"cost per passing SQL: ${per_pass:.6f}"
        )
    return "\n".join(lines)
