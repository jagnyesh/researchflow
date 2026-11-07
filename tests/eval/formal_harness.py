"""#239: score the Formal Portal's phenotype SQL against gold-case oracles.

A case passes only when the generated phenotype SQL executes with its bound
parameters AND selects exactly the oracle's patients. The two sets are
compared inside Postgres; only three counts come back (SQL, oracle, and the
symmetric-difference size), so no patient id leaves the database or reaches a
log or fixture. An execution error is a fail with a log ref, never a count
(the honest-failure invariant); an oracle that selects nobody makes the case
vacuous, never a pass.

Turning a case's request into structured requirements (Requirements Agent,
record/replay) is a separate step; score_case takes the requirements.
"""

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional

from app.adapters.sql_on_fhir import SQLonFHIRAdapter
from app.schemas._errors import log_internal_error
from app.utils.sql_generator import SQLGenerator

from tests.eval.formal_cases import FormalCase
from tests.eval.formal_predicates import check_predicates

logger = logging.getLogger(__name__)


@dataclass
class CaseScore:
    id: str
    executed: bool
    passed: bool
    vacuous: bool
    sql_count: Optional[int] = None
    oracle_count: Optional[int] = None
    mismatch: Optional[int] = None
    error_ref: Optional[str] = None
    # #242: "; "-joined canonical predicates (no patient data), "" when none.
    missing_predicates: str = ""
    extra_predicates: str = ""


def _label(predicate) -> str:
    kind, op, value = predicate
    if kind == "unrecognized":
        return f"unrecognized: {op}"
    if kind == "condition":
        return f"condition {op} {value}"
    return f"{kind} {op} {value}"


def _labels(predicates) -> str:
    return "; ".join(sorted(_label(p) for p in predicates))


def _comparison_sql(phenotype_sql: str, oracle_sql: str) -> str:
    # Both fragments are trusted code (the generator's output with bound
    # params, and a checked-in oracle); nothing here comes from a request.
    # One plain SELECT: SQLonFHIRAdapter runs SELECT statements only (no WITH).
    generated = f"SELECT DISTINCT patient_id FROM ({phenotype_sql}) AS generated"
    oracle = f"SELECT DISTINCT patient_id FROM ({oracle_sql}) AS oracle"
    return f"""SELECT
        (SELECT count(*) FROM ({generated}) s) AS sql_count,
        (SELECT count(*) FROM ({oracle}) o) AS oracle_count,
        (SELECT count(*) FROM ({generated} EXCEPT {oracle}) extra)
      + (SELECT count(*) FROM ({oracle} EXCEPT {generated}) missing) AS mismatch
    """  # nosec B608


def case_passes(mismatch: int, vacuous: bool, missing, extra) -> bool:
    """Every rule passes: same patients, a non-empty oracle, and exactly the
    requested predicates (#242)."""
    return mismatch == 0 and not vacuous and not missing and not extra


async def score_case(case: FormalCase, requirements: Dict) -> CaseScore:
    try:
        sql, params = SQLGenerator(use_materialized_views=True).generate_phenotype_sql(
            requirements, count_only=False
        )
        [row] = await SQLonFHIRAdapter().execute_sql(_comparison_sql(sql, case.oracle_sql), params)
    except Exception as exc:
        ref = log_internal_error(logger, f"Gold case {case.id} failed", exc)
        return CaseScore(id=case.id, executed=False, passed=False, vacuous=False, error_ref=ref)

    vacuous = row["oracle_count"] == 0
    missing, extra = check_predicates(case, sql, params)
    return CaseScore(
        id=case.id,
        executed=True,
        passed=case_passes(row["mismatch"], vacuous, missing, extra),
        vacuous=vacuous,
        sql_count=row["sql_count"],
        oracle_count=row["oracle_count"],
        mismatch=row["mismatch"],
        missing_predicates=_labels(missing),
        extra_predicates=_labels(extra),
    )


def pass_at_1(scores: List[CaseScore]) -> float:
    """Passed cases over all cases run: vacuous and failed cases count against it."""
    return sum(s.passed for s in scores) / len(scores) if scores else 0.0


def write_jsonl(
    scores: List[CaseScore], path: Path, *, commit: str, batch_anchor_ts: Optional[str]
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as out:
        for score in scores:
            record = {**asdict(score), "commit": commit, "batch_anchor_ts": batch_anchor_ts}
            out.write(json.dumps(record) + "\n")
    return path
