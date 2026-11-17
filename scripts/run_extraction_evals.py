"""#136: measure the Requirements Agent's concept-extraction accuracy (ADR 0040).

Sends each case in tests/eval/fixtures/extraction_cases.json through the live
extraction path (RequirementsAgent._criteria_to_structured, billed Haiku calls),
scores the concepts the way SQLGenerator reads them, and writes JSONL evidence
to logs/extraction_evals.jsonl.

    ./.venv/bin/python -m scripts.run_extraction_evals [--fail-under PCT]

Exit codes: 0 complete; 1 accuracy below --fail-under; 2 the run can't be
trusted (no cases, executed != cases in the fixture, a bad fixture, or no live
LLM client).
"""

import argparse
import asyncio
import json
import re
import subprocess  # nosec B404 - fixed git command, no input
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.utils.sql_generator import SQLGenerator  # noqa: E402

CASES = ROOT / "tests" / "eval" / "fixtures" / "extraction_cases.json"
LOG = ROOT / "logs" / "extraction_evals.jsonl"

EXIT_OK, EXIT_BELOW_THRESHOLD, EXIT_INTEGRITY = 0, 1, 2
LISTS = ("inclusion", "exclusion")

# Markers SQLGenerator._build_criteria_conditions reads; they have no named constants.
_EXCLUDED = re.compile(r"\bexcluded\b", re.I)
_DRUG_CLASS = re.compile(r"\bdrug[\s-]+class(?:es)?\b", re.I)
# Report-only: no consumer reads timing from details yet (ADR 0040).
_WITHIN = re.compile(r"\b(?:last|past)\s+(\d+)\s+(day|week|month|year)s?\b", re.I)


_RECORD_TYPES = ("condition", "medication", "procedure", "lab")
_POLARITIES = ("has", "excluded", "family_history")
_AGE_OPS = (">", ">=", "<", "<=", "BETWEEN", "AND", "OR")


class ExtractionShapeError(Exception):
    """Extraction returned a different number of criteria than it was sent."""


class FixtureError(Exception):
    """The case set can't be scored as written."""


def _text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _age(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _bound(value) -> bool:
    return (
        isinstance(value, list) and len(value) == 2 and value[0] in _AGE_OPS[:4] and _age(value[1])
    )


def _valid_age(age) -> bool:
    """The shapes SQLGenerator._parse_age_details returns, in JSON."""
    if not (isinstance(age, list) and len(age) == 2):
        return False
    op, value = age
    if op in _AGE_OPS[:4]:
        return _age(value)
    pair = isinstance(value, list) and len(value) == 2
    if op == "BETWEEN":
        return pair and all(_age(v) for v in value)
    return op in ("AND", "OR") and pair and all(_bound(v) for v in value)


def _check_expected(where: str, expected) -> None:
    if not isinstance(expected, dict):
        raise FixtureError(f"{where}: an expected concept is not an object")
    concept_type = expected.get("type")
    if concept_type in _RECORD_TYPES:
        terms = expected.get("terms")
        if not (isinstance(terms, list) and terms and all(_text(t) for t in terms)):
            raise FixtureError(f"{where}: a {concept_type} needs a non-empty terms list")
        if expected.get("polarity") not in _POLARITIES:
            raise FixtureError(f"{where}: polarity must be one of {', '.join(_POLARITIES)}")
    elif concept_type == "demographic":
        if "age" in expected:
            if not _valid_age(expected["age"]):
                raise FixtureError(
                    f"{where}: age must be [op, value] as _parse_age_details returns it"
                )
        elif expected.get("gender") not in ("female", "male"):
            raise FixtureError(f"{where}: a demographic needs an age or a gender of female or male")
    else:
        raise FixtureError(f"{where}: unknown concept type")
    within = expected.get("temporal_within")
    if within is not None and not (
        isinstance(within, list) and len(within) == 2 and isinstance(within[0], int)
    ):
        raise FixtureError(f"{where}: temporal_within must be [N, unit]")


def load_cases(path: Path) -> list:
    """The fixture's cases, or FixtureError if any part of it can't be scored."""
    try:
        fixture = json.loads(Path(path).read_text())
    except (OSError, ValueError) as e:
        raise FixtureError(f"can't read {path}: {type(e).__name__}") from e
    cases = fixture.get("cases") if isinstance(fixture, dict) else None
    if not isinstance(cases, list):
        raise FixtureError("the fixture has no cases list")
    seen = set()
    for n, case in enumerate(cases):
        case_id = case.get("id") if isinstance(case, dict) else None
        where = f"case {case_id or n}"
        if not _text(case_id) or case_id in seen:
            raise FixtureError(f"{where}: every case needs a unique id")
        seen.add(case_id)
        if not _text(case.get("signoff")):
            raise FixtureError(f"{where}: no signoff")
        if not sum(_check_list(where, case.get(name, []), name) for name in LISTS):
            raise FixtureError(f"{where}: no criteria")
    return cases


def _check_list(where: str, items, list_name: str) -> int:
    """How many criteria the list holds, or FixtureError if one is malformed."""
    if not isinstance(items, list):
        raise FixtureError(f"{where}: {list_name} is not a list")
    for item in items:
        if not isinstance(item, dict) or not _text(item.get("criterion")):
            raise FixtureError(f"{where}: a criterion has no text")
        expected = item.get("expected")
        if not (isinstance(expected, list) and expected):
            raise FixtureError(f"{where}: a criterion expects no concepts")
        for concept in expected:
            _check_expected(where, concept)
    return len(items)


def _norm(text) -> str:
    return " ".join(str(text).lower().split())


def _as_tuple(value):
    if isinstance(value, (list, tuple)):
        return tuple(_as_tuple(v) for v in value)
    return value


def canonical(concept: dict, in_exclusion: bool) -> tuple:
    """The concept as SQLGenerator reads it."""
    concept_type = concept.get("type")
    if concept_type == "demographics":
        concept_type = "demographic"
    term = concept.get("term")
    term_text = term if isinstance(term, str) else ""
    details = concept.get("details")
    details_text = "" if details is None else str(details)

    if concept_type == "demographic":
        if not in_exclusion and _EXCLUDED.search(details_text):
            pass  # the generator fails any concept marked excluded in an inclusion list
        elif "age" in term_text.lower():
            op, value = SQLGenerator._parse_age_details(details_text)
            if op is not None:
                return ("age", op, _as_tuple(value))
        else:
            sql, params = SQLGenerator()._build_demographic_clause(term_text, details_text)
            if sql.startswith("p.gender"):
                return ("gender", "=", next(iter(params.values())))
        return ("demographic", "unbuildable", _norm(term_text))

    polarity = "has"
    if concept_type == "medication" and _DRUG_CLASS.search(details_text):
        # A class name matches no prescription, so the generator fails it in either
        # list; no fixture polarity can match this one.
        polarity = "drug_class"
    elif concept_type == "condition" and SQLGenerator._FAMILY_HISTORY.search(
        f"{term_text} {details_text}"
    ):
        polarity = "family_history"
    elif _EXCLUDED.search(details_text) and not in_exclusion:
        # In an exclusion list the marker restates the list (ADR 0036).
        polarity = "excluded"
    return (concept_type, _norm(term_text), polarity)


def _kind(canon: tuple) -> str:
    return "demographic" if canon[0] in ("age", "gender", "demographic") else str(canon[0])


def _matches(expected: dict, canon: tuple, in_exclusion: bool) -> bool:
    if expected["type"] == "demographic":
        if "age" in expected:
            op, value = expected["age"]
            return canon == ("age", op, _as_tuple(value))
        return canon == ("gender", "=", expected["gender"])
    polarity = expected["polarity"]
    if in_exclusion and polarity == "excluded":
        polarity = "has"
    return (
        canon[0] == expected["type"]
        and canon[2] == polarity
        and canon[1] in {_norm(t) for t in expected["terms"]}
    )


def _within(details) -> list:
    found = _WITHIN.search("" if details is None else str(details))
    return [int(found.group(1)), found.group(2).lower()] if found else None


def score_case(case: dict, actual: dict) -> dict:
    """Exact-match score for one case: every expected concept, no extras."""
    items, tally, temporal = [], defaultdict(lambda: [0, 0, 0]), []
    for list_name in LISTS:
        criteria = case.get(list_name, [])
        got = actual.get(list_name, [])
        if len(got) != len(criteria):
            raise ExtractionShapeError()
        in_exclusion = list_name == "exclusion"
        for criterion, concepts in zip(criteria, got):
            unmatched = [(canonical(c, in_exclusion), c) for c in concepts]
            actual_canon = [canon for canon, _ in unmatched]
            missing = []
            for expected in criterion["expected"]:
                hit = next((u for u in unmatched if _matches(expected, u[0], in_exclusion)), None)
                if hit is None:
                    missing.append(expected)
                    tally[expected["type"]][2] += 1
                    continue
                unmatched.remove(hit)
                tally[expected["type"]][0] += 1
                if "temporal_within" in expected:
                    want, found = expected["temporal_within"], _within(hit[1].get("details"))
                    temporal.append(
                        {
                            "criterion": criterion["criterion"],
                            "expected": want,
                            "found": found,
                            "match": found is not None
                            and found[0] == want[0]
                            and found[1].rstrip("s") == str(want[1]).lower().rstrip("s"),
                        }
                    )
            for canon, _ in unmatched:
                tally[_kind(canon)][1] += 1
            items.append(
                {
                    "list": list_name,
                    "criterion": criterion["criterion"],
                    "expected": criterion["expected"],
                    "returned": concepts,
                    "actual": actual_canon,
                    "missing": missing,
                    "extra": [canon for canon, _ in unmatched],
                }
            )
    passed = all(not i["missing"] and not i["extra"] for i in items)
    return {
        "case_id": case["id"],
        "pass": passed,
        "error": None,
        "criteria": items,
        "tally": {k: {"tp": v[0], "fp": v[1], "fn": v[2]} for k, v in tally.items()},
        "temporal": temporal,
    }


async def run_cases(cases: list, extract, results: list) -> None:
    """Appends one result per case to results, so an interrupted run keeps its count."""
    for case in cases:
        try:
            actual = {}
            for list_name in LISTS:
                criteria = [c["criterion"] for c in case.get(list_name, [])]
                actual[list_name] = await extract(criteria) if criteria else []
            result = score_case(case, actual)
        except Exception as e:
            # The class only: a message can carry criterion text or raw model output.
            result = {"case_id": case["id"], "pass": False, "error": type(e).__name__}
            # Every expected concept is a miss, so the error lowers per-type recall.
            misses = defaultdict(int)
            for list_name in LISTS:
                for criterion in case.get(list_name, []):
                    for expected in criterion["expected"]:
                        misses[expected["type"]] += 1
            tally = {kind: {"tp": 0, "fp": 0, "fn": n} for kind, n in misses.items()}
            result.update(criteria=[], tally=tally, temporal=[])
        results.append(result)


def _git_commit() -> str:
    try:
        return subprocess.run(  # nosec B603 B607
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _summary(results: list, expected: int) -> dict:
    by_type = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    for result in results:
        for kind, counts in result["tally"].items():
            for key, n in counts.items():
                by_type[kind][key] += n
    temporal = [t for r in results for t in r["temporal"]]
    passed = sum(r["pass"] for r in results)
    return {
        "executed": len(results),
        "expected": expected,
        "passed": passed,
        "accuracy_pct": round(100.0 * passed / expected, 1),
        "by_type": dict(sorted(by_type.items())),
        "temporal": {"checked": len(temporal), "matched": sum(t["match"] for t in temporal)},
    }


def _ratio(num: int, den: int) -> str:
    return f"{num / den:.2f}" if den else "n/a"


def _report(summary: dict, results: list) -> None:
    print(f"executed {summary['executed']} / expected {summary['expected']}")
    print(
        f"{summary['passed']}/{summary['expected']} cases passed ({summary['accuracy_pct']:.1f}%)"
    )
    for kind, c in summary["by_type"].items():
        print(
            f"  {kind}: precision {_ratio(c['tp'], c['tp'] + c['fp'])}, "
            f"recall {_ratio(c['tp'], c['tp'] + c['fn'])} "
            f"(tp {c['tp']}, fp {c['fp']}, fn {c['fn']})"
        )
    t = summary["temporal"]
    print(f"temporal (report-only): {t['matched']}/{t['checked']} matched")
    for result in results:
        if result["error"]:
            print(f"  FAIL {result['case_id']}: error {result['error']}")
        elif not result["pass"]:
            missing = sum(len(i["missing"]) for i in result["criteria"])
            extra = sum(len(i["extra"]) for i in result["criteria"])
            print(f"  FAIL {result['case_id']}: {missing} missing, {extra} extra")


def _write_log(path: Path, results: list, summary: dict) -> None:
    ts, commit = datetime.now(timezone.utc).isoformat(), _git_commit()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as log:
        for result in results:
            row = {"ts": ts, "git_commit": commit, **result}
            row.pop("tally")
            log.write(json.dumps(row) + "\n")
        log.write(json.dumps({"ts": ts, "git_commit": commit, "summary": summary}) + "\n")


def _live_extract():
    """The portal's extraction path, or None when LLMClient has no API key (it
    would answer every call with canned output)."""
    from app.agents.requirements_agent import RequirementsAgent

    agent = RequirementsAgent()
    if agent.llm_client.client is None:
        return None

    async def extract(criteria):
        return [c["concepts"] for c in await agent._criteria_to_structured(criteria)]

    return extract


def _percent(text: str) -> float:
    value = float(text)
    if not 0 <= value <= 100:  # also refuses nan, which compares false to every number
        raise argparse.ArgumentTypeError(f"{text} is not a percentage from 0 to 100")
    return value


def main(argv=None, extract=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cases", type=Path, default=CASES)
    parser.add_argument("--log", type=Path, default=LOG)
    parser.add_argument(
        "--fail-under",
        type=_percent,
        default=None,
        metavar="PCT",
        help="exit 1 when the case pass rate is below PCT (default: report only)",
    )
    args = parser.parse_args(argv)

    try:
        cases = load_cases(args.cases)
    except FixtureError as e:
        print(f"INTEGRITY: the fixture is malformed: {e}")
        return EXIT_INTEGRITY
    if not cases:
        print(f"INTEGRITY: the fixture holds 0 cases ({args.cases})")
        return EXIT_INTEGRITY
    if extract is None:
        extract = _live_extract()
        if extract is None:
            print("INTEGRITY: no live LLM client (ANTHROPIC_API_KEY is empty); not scoring")
            return EXIT_INTEGRITY

    results = []
    try:
        asyncio.run(run_cases(cases, extract, results))
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass  # the count check below reports the partial run
    summary = _summary(results, len(cases))
    _write_log(args.log, results, summary)
    _report(summary, results)
    return _exit_code(results, len(cases), args.fail_under)


def _exit_code(results: list, expected: int, fail_under) -> int:
    """Integrity failures first: a run that can't be trusted has no accuracy."""
    if len(results) != expected:
        print(f"INTEGRITY: executed {len(results)} of the fixture's {expected} cases")
        return EXIT_INTEGRITY
    if all(r["error"] for r in results):
        # An expired key or an outage, not a 0% extractor.
        print("INTEGRITY: every case errored, so nothing was measured")
        return EXIT_INTEGRITY
    accuracy = 100.0 * sum(r["pass"] for r in results) / expected
    if fail_under is not None and accuracy < fail_under:
        print(f"FAIL: accuracy {accuracy:.1f}% is below --fail-under {fail_under:g}")
        return EXIT_BELOW_THRESHOLD
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
