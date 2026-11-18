"""#136: measure the Requirements Agent's concept-extraction accuracy (ADR 0040).

Sends each case in tests/eval/fixtures/extraction_cases.json through the live
extraction path (RequirementsAgent._criteria_to_structured, billed Haiku calls),
scores the concepts the way SQLGenerator reads them, and writes JSONL evidence
to logs/extraction_evals.jsonl.

    ./.venv/bin/python -m scripts.run_extraction_evals [--fail-under PCT]

#137 (ADR 0041) adds recorded wire responses. CI runs --replay, which answers
every model call from tests/eval/fixtures/extraction_recording.json with no API
key. A re-baseline runs --repeat 5 --record: five billed live runs, run 1 saved
as the recording, and the lowest pass rate printed for --fail-under.

Exit codes: 0 complete; 1 accuracy below --fail-under; 2 the run can't be
trusted (no cases, fewer than --min-cases, executed != cases in the fixture, a
bad fixture or recording, no live LLM client, every case errored, a replayed
request with no recorded response or a recorded response never requested, an
untrusted run in a --repeat, or the evidence log can't be written).
"""

import argparse
import asyncio
import contextlib
import hashlib
import json
import math
import os
import re
import subprocess  # nosec B404 - fixed git command, no input
import sys
from collections import defaultdict, deque
from datetime import datetime, timezone
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from anthropic.resources.messages.messages import AsyncMessages  # noqa: E402
from anthropic.types import Message  # noqa: E402

from app.utils.sql_generator import SQLGenerator  # noqa: E402

CASES = ROOT / "tests" / "eval" / "fixtures" / "extraction_cases.json"
LOG = ROOT / "logs" / "extraction_evals.jsonl"
RECORDING = ROOT / "tests" / "eval" / "fixtures" / "extraction_recording.json"
# A key no real API accepts, so a replay that missed the patch couldn't bill.
REPLAY_KEY = "replay-placeholder-not-a-key"  # nosec B105 - not a credential

EXIT_OK, EXIT_BELOW_THRESHOLD, EXIT_INTEGRITY = 0, 1, 2
LISTS = ("inclusion", "exclusion")

# Markers SQLGenerator._build_criteria_conditions reads; they have no named constants.
_EXCLUDED = re.compile(r"\bexcluded\b", re.I)
_DRUG_CLASS = re.compile(r"\bdrug[\s-]+class(?:es)?\b", re.I)
# Report-only: no consumer reads timing from details yet (ADR 0040).
_WITHIN = re.compile(r"\b(?:last|past)\s+(\d+)\s+(day|week|month|year)s?\b", re.I)


_FIXTURE_KEYS = ("format", "cases")
_CASE_KEYS = ("id", "signoff") + LISTS
_CRITERION_KEYS = ("criterion", "expected")
_CONCEPT_KEYS = ("type", "terms", "polarity", "age", "gender", "temporal_within")
_RECORD_TYPES = ("condition", "medication", "procedure", "lab")
_POLARITIES = ("has", "excluded", "family_history")


class ExtractionShapeError(Exception):
    """Extraction returned a different number of criteria than it was sent."""


class FixtureError(Exception):
    """The case set can't be scored as written."""


def _text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


_LOWER, _UPPER = (">", ">="), ("<", "<=")


def _age(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _bound(value, ops) -> bool:
    return isinstance(value, list) and len(value) == 2 and value[0] in ops and _age(value[1])


def _valid_age(age) -> bool:
    """The shapes SQLGenerator._parse_age_details returns, in JSON. It returns AND
    as (lower, upper) and OR as (upper, lower), so no other order can ever match."""
    if not (isinstance(age, list) and len(age) == 2):
        return False
    op, value = age
    if op in _LOWER + _UPPER:
        return _age(value)
    if not (isinstance(value, list) and len(value) == 2):
        return False
    if op == "BETWEEN":
        return all(_age(v) for v in value)
    if op == "AND":
        lower, upper = value
        if not (_bound(lower, _LOWER) and _bound(upper, _UPPER)):
            return False
    elif op == "OR":
        upper, lower = value
        if not (_bound(upper, _UPPER) and _bound(lower, _LOWER)):
            return False
    else:
        return False
    # The parser's own shape check, in whole years: AND must admit an age and OR
    # must leave one out.
    youngest = lower[1] + (lower[0] == ">")
    oldest = upper[1] - (upper[0] == "<")
    return youngest <= oldest if op == "AND" else oldest + 1 < youngest


def _check_keys(where: str, obj: dict, allowed: tuple) -> None:
    # A misspelled key would be ignored, and its criteria never sent or scored.
    unknown = sorted(set(obj) - set(allowed))
    if unknown:
        raise FixtureError(f"{where}: unknown keys {', '.join(unknown)}")


def _check_expected(where: str, expected) -> None:
    if not isinstance(expected, dict):
        raise FixtureError(f"{where}: an expected concept is not an object")
    _check_keys(where, expected, _CONCEPT_KEYS)
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
    _check_keys("the fixture", fixture, _FIXTURE_KEYS)
    seen = set()
    for n, case in enumerate(cases):
        case_id = case.get("id") if isinstance(case, dict) else None
        where = f"case {case_id or n}"
        if not _text(case_id) or case_id in seen:
            raise FixtureError(f"{where}: every case needs a unique id")
        seen.add(case_id)
        _check_keys(where, case, _CASE_KEYS)
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
        _check_keys(where, item, _CRITERION_KEYS)
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


def _demographic(term_text: str, details, details_text: str, in_exclusion: bool) -> tuple:
    unbuildable = ("demographic", "unbuildable", _norm(term_text))
    if details and not isinstance(details, str):
        return unbuildable  # the generator calls details.lower() and raises
    if not isinstance(details, str):
        details_text = ""  # the generator reads empty details as none
    if not in_exclusion and _EXCLUDED.search(details_text):
        return unbuildable  # the generator fails any concept marked excluded in an inclusion list
    if "age" in term_text.lower():
        op, value = SQLGenerator._parse_age_details(details_text)
        return ("age", op, _as_tuple(value)) if op is not None else unbuildable
    sql, params = SQLGenerator()._build_demographic_clause(term_text, details_text)
    if sql.startswith("p.gender"):
        return ("gender", "=", next(iter(params.values())))
    return unbuildable


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
        return _demographic(term_text, details, details_text, in_exclusion)

    # The generator's order: the excluded marker, then a drug class, then family history.
    polarity = "has"
    if _EXCLUDED.search(details_text) and not in_exclusion:
        # In an exclusion list the marker restates the list (ADR 0036).
        polarity = "excluded"
    elif concept_type == "medication" and _DRUG_CLASS.search(details_text):
        # A class name matches no prescription, so the generator fails it in either
        # list; no fixture polarity can match this one.
        polarity = "drug_class"
    elif concept_type == "condition" and SQLGenerator._FAMILY_HISTORY.search(
        f"{term_text} {details_text}"
    ):
        polarity = "family_history"
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
    """HEAD, with -dirty when the tree has uncommitted or untracked changes, so a
    run made from uncommitted code doesn't claim a commit that didn't hold it."""
    try:
        commit = subprocess.run(  # nosec B603 B607
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
        status = subprocess.run(  # nosec B603 B607
            ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return commit + ("-dirty" if status.strip() else "")


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
    lines = []
    for result in results:
        row = {"ts": ts, "git_commit": commit, **result}
        row.pop("tally")
        lines.append(json.dumps(row))
    lines.append(json.dumps({"ts": ts, "git_commit": commit, "summary": summary}))
    # Every row is JSON before the first write, so a row that can't be written
    # leaves no case rows without their summary row (#526 finding 22).
    path.parent.mkdir(parents=True, exist_ok=True)
    start = path.stat().st_size if path.exists() else 0
    try:
        with path.open("a") as log:
            log.write("".join(line + "\n" for line in lines))
    except OSError:
        # A disk-full error can land partway through; cut the log back to the
        # earlier runs rather than leave a torn one.
        os.truncate(path, start)
        raise


# --- Recorded wire responses (ADR 0041) -------------------------------------------

_RECORDING_KEYS = ("format", "recorded_at", "git_commit", "calls")
_CALL_KEYS = ("request_sha256", "model", "system_sha256", "user", "response")
_RECORDING_FORMAT = {
    "about": (
        "Recorded Anthropic API responses for one live run of "
        "scripts/run_extraction_evals.py (ADR 0041). CI replays them with no API key. "
        "Regenerate with --repeat 5 --record; never edit by hand."
    ),
    "calls[]": "One outbound AsyncMessages.create call, in call order.",
    "calls[].request_sha256": (
        "SHA-256 of the whole request: model, max_tokens, temperature, system, messages."
    ),
    "calls[].system_sha256": "The system prompt, by hash only.",
    "calls[].user": "The last user message, for review. Synthetic criteria only.",
    "calls[].response": "The response's text, stop reason and token usage.",
}


class ReplayMiss(Exception):
    """A request the recording has no response for."""


def _canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _request_key(kwargs: dict) -> str:
    return _sha256(_canonical_json(kwargs))


def _user_text(kwargs: dict) -> str:
    content = (kwargs.get("messages") or [{}])[-1].get("content", "")
    return content if isinstance(content, str) else _canonical_json(content)


def _recorder(calls: list, failures: list, original):
    async def create(self, *args, **kwargs):
        try:
            response = await original(self, *args, **kwargs)
        except Exception as e:
            # The agent's fallback can recover the case, but the failed request has
            # no response to record, so this recording could never replay.
            failures.append(type(e).__name__)
            raise
        calls.append(
            {
                "request_sha256": _request_key(kwargs),
                "model": kwargs.get("model"),
                "system_sha256": _sha256(_canonical_json(kwargs.get("system"))),
                "user": _user_text(kwargs),
                "response": {
                    "text": "".join(b.text for b in response.content if b.type == "text"),
                    "stop_reason": response.stop_reason,
                    "usage": response.usage.model_dump(exclude_none=True),
                },
            }
        )
        return response

    return create


class _Replay:
    """Answers each request from the recording, in call order for repeated requests."""

    def __init__(self, calls: list):
        self.queues = defaultdict(deque)
        for call in calls:
            self.queues[call["request_sha256"]].append(call)
        self.misses = 0

    def create(self, original):
        async def create(_self, *args, **kwargs):
            queue = self.queues.get(_request_key(kwargs))
            if not queue:
                self.misses += 1
                raise ReplayMiss()
            call = queue.popleft()
            return Message.model_validate(
                {
                    "id": "msg_replay",
                    "type": "message",
                    "role": "assistant",
                    "model": call["model"],
                    "content": [{"type": "text", "text": call["response"]["text"]}],
                    "stop_reason": call["response"]["stop_reason"],
                    "stop_sequence": None,
                    "usage": call["response"]["usage"],
                }
            )

        return create

    def problem(self):
        # The agent absorbs a miss as a failed call, so the replay counts its own.
        unused = sum(len(q) for q in self.queues.values())
        if self.misses:
            return (
                f"INTEGRITY: {self.misses} request(s) have no recorded response; "
                "a prompt, the model or a case changed, so re-baseline"
            )
        if unused:
            return (
                f"INTEGRITY: {unused} recorded response(s) were never requested; "
                "the extraction calls no longer match the recording, so re-baseline"
            )
        return None


def load_recording(path: Path) -> list:
    """The recording's calls, or FixtureError if it can't be replayed as written."""
    try:
        recording = json.loads(Path(path).read_text())
    except (OSError, ValueError) as e:
        raise FixtureError(f"can't read the recording {path}: {type(e).__name__}") from e
    calls = recording.get("calls") if isinstance(recording, dict) else None
    if not (isinstance(calls, list) and calls):
        raise FixtureError("the recording has no calls")
    _check_keys("the recording", recording, _RECORDING_KEYS)
    for n, call in enumerate(calls):
        where = f"recorded call {n}"
        if not isinstance(call, dict):
            raise FixtureError(f"{where} is not an object")
        _check_keys(where, call, _CALL_KEYS)
        response = call.get("response")
        if not (
            _text(call.get("request_sha256"))
            and _text(call.get("model"))
            and isinstance(response, dict)
            and isinstance(response.get("text"), str)
            and isinstance(response.get("usage"), dict)
        ):
            raise FixtureError(f"{where} lacks a key, a model or a response")
    return calls


def _write_recording(path: Path, calls: list) -> None:
    recording = {
        "format": _RECORDING_FORMAT,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit(),
        "calls": calls,
    }
    text = json.dumps(recording, indent=1) + "\n"
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(text)


@contextlib.contextmanager
def _create_patched(make):
    """Replace AsyncMessages.create with make(original) for the block, if make is set."""
    if make is None:
        yield
        return
    original = AsyncMessages.create
    AsyncMessages.create = make(original)
    try:
        yield
    finally:
        AsyncMessages.create = original


def _live_extract(api_key=None):
    """The portal's extraction path, or None when LLMClient has no API key (it
    would answer every call with canned output). api_key replaces the key from
    the environment; replay passes a placeholder no real API accepts."""
    from app.agents.requirements_agent import RequirementsAgent
    from app.utils.llm_client import LLMClient

    agent = RequirementsAgent()
    if api_key is not None:
        agent.llm_client = LLMClient(api_key=api_key)
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


def _positive(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError(f"{text} is not a whole number of at least 1")
    return value


def _prepare(args, extract) -> tuple:
    """(cases, extract, replay), or None after printing why the run can't start."""
    try:
        cases = load_cases(args.cases)
    except FixtureError as e:
        print(f"INTEGRITY: the fixture is malformed: {e}")
        return None
    if not cases:
        print(f"INTEGRITY: the fixture holds 0 cases ({args.cases})")
        return None
    if args.min_cases is not None and len(cases) < args.min_cases:
        # Deleting cases keeps executed equal to expected (ADR 0040), so CI pins a floor.
        print(
            f"INTEGRITY: the fixture holds {len(cases)} cases, "
            f"fewer than --min-cases {args.min_cases}"
        )
        return None
    replay = None
    if args.replay:
        try:
            replay = _Replay(load_recording(args.replay))
        except FixtureError as e:
            print(f"INTEGRITY: the recording is malformed: {e}")
            return None
    if extract is None:
        extract = _live_extract(REPLAY_KEY) if replay else _live_extract()
        if extract is None:
            print("INTEGRITY: no live LLM client (ANTHROPIC_API_KEY is empty); not scoring")
            return None
    return cases, extract, replay


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
    parser.add_argument(
        "--min-cases",
        type=_positive,
        default=None,
        metavar="N",
        help="exit 2 when the fixture holds fewer than N cases",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--replay",
        type=Path,
        nargs="?",
        const=RECORDING,
        metavar="PATH",
        help=f"answer every model call from a recording, no API key (default {RECORDING.name})",
    )
    mode.add_argument(
        "--record",
        type=Path,
        nargs="?",
        const=RECORDING,
        metavar="PATH",
        help="live: save run 1's model responses as the recording",
    )
    parser.add_argument(
        "--repeat",
        type=_positive,
        default=1,
        metavar="K",
        help="live: run the whole case set K times and report the lowest pass rate",
    )
    args = parser.parse_args(argv)
    if args.replay and args.repeat > 1:
        parser.error("--repeat measures live runs; a replay gives the same answers every time")
    try:
        return _main(args, extract)
    except Exception as e:
        # Python's default exit code 1 would read as below --fail-under. The class
        # only: a message can carry criterion text or raw model output.
        print(f"INTEGRITY: the run failed: {type(e).__name__}")
        return EXIT_INTEGRITY


def _main(args, extract) -> int:
    prepared = _prepare(args, extract)
    if prepared is None:
        return EXIT_INTEGRITY
    cases, extract, replay = prepared
    mode = "replay" if replay else "record" if args.record else "live"

    runs, recorded = [], None
    for run in range(1, args.repeat + 1):
        if args.repeat > 1:
            print(f"--- run {run} of {args.repeat}")
        calls, failures = ([], []) if args.record and run == 1 else (None, None)
        make = (
            replay.create
            if replay
            else partial(_recorder, calls, failures) if calls is not None else None
        )
        with _create_patched(make):
            code, results = _run_once(args, cases, extract, replay, mode, run)
        if calls is not None:
            if code == EXIT_INTEGRITY:
                print("INTEGRITY: run 1 can't be trusted, so no recording was written")
            elif failures:
                print(
                    f"INTEGRITY: {len(failures)} call(s) failed while recording, so the "
                    "recording couldn't replay; no recording was written"
                )
                code = EXIT_INTEGRITY
            else:
                recorded = calls
            if code == EXIT_INTEGRITY and args.repeat > 1:
                # Every later run is billed, and the re-baseline can only exit 2.
                print("INTEGRITY: stopping before run 2: the recorded run can't be trusted")
                return EXIT_INTEGRITY
        runs.append((code, results))
    code = _report_repeats(runs, len(cases)) if args.repeat > 1 else runs[0][0]
    if recorded is not None:
        # Written only once every run is trusted, so a failed re-baseline leaves
        # the committed recording as it was.
        if code == EXIT_INTEGRITY:
            print("INTEGRITY: a run can't be trusted, so no recording was written")
        else:
            _write_recording(args.record, recorded)
            print(f"recorded {len(recorded)} calls to {args.record}")
    return code


def _run_once(args, cases, extract, replay, mode, run) -> tuple:
    results = []
    try:
        asyncio.run(run_cases(cases, extract, results))
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass  # the count check below reports the partial run
    summary = _summary(results, len(cases))
    problem = replay.problem() if replay else None
    if problem:
        code, message = EXIT_INTEGRITY, problem
    else:
        code, message = _verdict(results, len(cases), args.fail_under)
    # The log carries the verdict so a reader can drop runs that measured nothing.
    summary.update(mode=mode, run=run, exit_code=code)
    summary["integrity_failure"] = message if code == EXIT_INTEGRITY else None
    _report(summary, results)
    if message:
        print(message)
    try:
        _write_log(args.log, results, summary)
    except OSError as e:
        print(f"INTEGRITY: can't write the evidence log {args.log}: {type(e).__name__}")
        return EXIT_INTEGRITY, results
    return code, results


def _report_repeats(runs: list, expected: int) -> int:
    """Each run's pass rate, the lowest over trusted runs, and the cases that flipped."""
    trusted = [results for code, results in runs if code != EXIT_INTEGRITY]
    print(f"re-baseline: {len(trusted)} of {len(runs)} runs trusted")
    rates = []
    for n, (code, results) in enumerate(runs, 1):
        passed = sum(r["pass"] for r in results)
        note = " (untrusted)" if code == EXIT_INTEGRITY else ""
        if code != EXIT_INTEGRITY:
            rates.append(100.0 * passed / expected)
        print(f"  run {n}: {passed}/{expected} passed{note}")
    outcomes = defaultdict(set)
    for results in trusted:
        for r in results:
            outcomes[r["case_id"]].add(r["pass"])
    flipped = sorted(case_id for case_id, seen in outcomes.items() if len(seen) > 1)
    print(f"  flipped between runs: {', '.join(flipped) if flipped else 'none'}")
    if len(trusted) != len(runs):
        print("INTEGRITY: a re-baseline needs every run trusted")
        return EXIT_INTEGRITY
    lowest = math.floor(min(rates) * 10) / 10
    print(f"  lowest pass rate {min(rates):.1f}%: set --fail-under {lowest:.1f}")
    return max(code for code, _ in runs)


def _verdict(results: list, expected: int, fail_under) -> tuple:
    """(exit code, message). Integrity failures first: a run that can't be trusted
    has no accuracy."""
    if len(results) != expected:
        return (
            EXIT_INTEGRITY,
            f"INTEGRITY: executed {len(results)} of the fixture's {expected} cases",
        )
    if all(r["error"] for r in results):
        # An expired key or an outage, not a 0% extractor.
        return EXIT_INTEGRITY, "INTEGRITY: every case errored, so nothing was measured"
    accuracy = 100.0 * sum(r["pass"] for r in results) / expected
    if fail_under is not None and accuracy < fail_under:
        return (
            EXIT_BELOW_THRESHOLD,
            f"FAIL: accuracy {accuracy:.1f}% is below --fail-under {fail_under:g}",
        )
    return EXIT_OK, None


if __name__ == "__main__":
    sys.exit(main())
