"""#136: the extraction eval runner (ADR 0040). Keyless: extraction is a fake at
the agent seam, so these tests can't see wire-level drift; the live run is the
wire-level evidence."""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run_extraction_evals.py"
CASES = ROOT / "tests" / "eval" / "fixtures" / "extraction_cases.json"


def _load_runner():
    spec = importlib.util.spec_from_file_location("run_extraction_evals", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


runner = _load_runner()


def _fixture():
    return json.loads(CASES.read_text())


def _write(tmp_path, fixture):
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(fixture))
    return path


def _run(tmp_path, fixture, extract, *extra):
    log = tmp_path / "evals.jsonl"
    code = runner.main(
        ["--cases", str(_write(tmp_path, fixture)), "--log", str(log), *extra], extract=extract
    )
    return code, log


async def _never_called(criteria):
    raise AssertionError("extraction ran for a run that should have stopped first")


def _c(term, type_, details):
    return {"term": term, "type": type_, "details": details}


# Hand-written concepts in the prompt's documented shape: a correct extraction
# of every fixture criterion. Test inputs, not model output.
CORRECT = {
    "type 2 diabetes": [_c("Type 2 Diabetes Mellitus", "condition", "T2DM diagnosis")],
    "hypertension": [_c("hypertension", "condition", "active")],
    "diabetics over 65": [
        _c("diabetes mellitus", "condition", "any type"),
        _c("age", "demographic", "> 65"),
    ],
    "female": [_c("gender", "demographic", "female")],
    "older than 65": [_c("age", "demographic", "older than 65")],
    "diabetes mellitus": [_c("diabetes mellitus", "condition", "diagnosis")],
    "female patients with hypertension under 65": [
        _c("gender", "demographic", "female"),
        _c("hypertension", "condition", "diagnosis"),
        _c("age", "demographic", "< 65"),
    ],
    "65 or older": [_c("age", "demographic", ">= 65")],
    "between 50 and 60 years old": [_c("age", "demographic", "between 50 and 60")],
    "history of coronary artery bypass graft": [_c("CABG", "procedure", "history of")],
    "type 2 diabetes not on insulin": [
        _c("type 2 diabetes", "condition", "T2DM"),
        _c("insulin", "medication", "excluded"),
    ],
    "male patients over 40 on metformin": [
        _c("gender", "demographic", "male"),
        _c("age", "demographic", "> 40"),
        _c("metformin", "medication", "any dose"),
    ],
    "HbA1c above 8% in the last 6 months": [_c("HbA1c", "lab", "> 8% within last 6 months")],
    "family history of breast cancer": [_c("breast cancer", "condition", "family history")],
}


def _extractor(table):
    async def extract(criteria):
        return [copy.deepcopy(table[c]) for c in criteria]

    return extract


def _rows(log):
    return [json.loads(line) for line in log.read_text().splitlines()]


def test_correct_extraction_passes_every_case_and_logs_evidence(tmp_path, capsys):
    code, log = _run(tmp_path, _fixture(), _extractor(CORRECT))
    out = capsys.readouterr().out
    assert code == runner.EXIT_OK
    assert "executed 12 / expected 12" in out
    assert "12/12 cases passed (100.0%)" in out
    rows = [r for r in _rows(log) if "case_id" in r]
    assert [r["case_id"] for r in rows] == [c["id"] for c in _fixture()["cases"]]
    for row in rows:
        assert row["pass"] is True
        assert row["ts"] and row["git_commit"]
        for item in row["criteria"]:
            assert {"list", "criterion", "expected", "actual", "missing", "extra"} <= set(item)


def _case_row(log, case_id):
    return next(r for r in _rows(log) if r.get("case_id") == case_id)


@pytest.mark.parametrize(
    "case_id, criterion, concepts, missing, extra",
    [
        # The negation is lost: the generator would select insulin users.
        (
            "t2dm_not_on_insulin",
            "type 2 diabetes not on insulin",
            [_c("type 2 diabetes", "condition", ""), _c("insulin", "medication", "not prescribed")],
            1,
            1,
        ),
        # The age bound is wrong.
        (
            "diabetics_over_65",
            "diabetics over 65",
            [_c("diabetes mellitus", "condition", ""), _c("age", "demographic", "> 60")],
            1,
            1,
        ),
        # An unparseable age is never the expected one.
        (
            "htn_65_or_older",
            "65 or older",
            [_c("age", "demographic", "senior")],
            1,
            1,
        ),
        # A concept the criterion doesn't hold.
        (
            "hypertension_preset",
            "hypertension",
            [_c("hypertension", "condition", ""), _c("gender", "demographic", "female")],
            0,
            1,
        ),
        # A term the owner didn't accept: bare diabetes widens a type 2 cohort.
        ("t2dm_preset", "type 2 diabetes", [_c("diabetes", "condition", "type 2")], 1, 1),
        # A family history read as the patient's own condition.
        (
            "family_history_breast_cancer",
            "family history of breast cancer",
            [_c("breast cancer", "condition", "history of")],
            1,
            1,
        ),
        # The right term with the wrong type.
        (
            "hba1c_last_6_months",
            "HbA1c above 8% in the last 6 months",
            [_c("HbA1c", "condition", "> 8%")],
            1,
            1,
        ),
        # An expected concept that never came back.
        (
            "male_over_40_on_metformin",
            "male patients over 40 on metformin",
            [_c("gender", "demographic", "male"), _c("metformin", "medication", "")],
            1,
            0,
        ),
    ],
)
def test_wrong_extraction_fails_only_its_case(
    tmp_path, capsys, case_id, criterion, concepts, missing, extra
):
    # A criterion text can recur across cases ("hypertension" is in three).
    holding = {
        c["id"]
        for c in _fixture()["cases"]
        if any(i["criterion"] == criterion for lst in runner.LISTS for i in c.get(lst, []))
    }
    assert case_id in holding
    table = dict(CORRECT, **{criterion: concepts})
    code, log = _run(tmp_path, _fixture(), _extractor(table))
    out = capsys.readouterr().out
    assert code == runner.EXIT_OK  # report-only by default
    assert f"{12 - len(holding)}/12 cases passed" in out
    row = _case_row(log, case_id)
    assert row["pass"] is False
    item = next(i for i in row["criteria"] if i["criterion"] == criterion)
    assert (len(item["missing"]), len(item["extra"])) == (missing, extra)
    cases = [r for r in _rows(log) if "case_id" in r]
    assert {r["case_id"] for r in cases if not r["pass"]} == holding


def test_excluded_marker_in_an_exclusion_list_restates_the_list(tmp_path, capsys):
    correct = _extractor(CORRECT)

    async def extract(criteria):
        if criteria == ["diabetes mellitus"]:  # htn_without_dm's exclusion list only
            return [[_c("diabetes mellitus", "condition", "excluded")]]
        return await correct(criteria)

    code, log = _run(tmp_path, _fixture(), extract)
    assert code == runner.EXIT_OK
    assert "12/12 cases passed" in capsys.readouterr().out


def test_excluded_marker_in_an_inclusion_list_is_its_own_polarity(tmp_path, capsys):
    table = dict(CORRECT, hypertension=[_c("hypertension", "condition", "excluded")])
    _, log = _run(tmp_path, _fixture(), _extractor(table))
    assert _case_row(log, "hypertension_preset")["pass"] is False


SECRET_TEXT = "raw model output that must not reach the log"


def test_extraction_error_fails_the_case_but_counts_it_executed(tmp_path, capsys):
    correct = _extractor(CORRECT)

    async def extract(criteria):
        if criteria == ["family history of breast cancer"]:
            raise ValueError(SECRET_TEXT)
        return await correct(criteria)

    code, log = _run(tmp_path, _fixture(), extract)
    out = capsys.readouterr().out
    assert code == runner.EXIT_OK
    assert "executed 12 / expected 12" in out
    assert "11/12 cases passed" in out
    row = _case_row(log, "family_history_breast_cancer")
    assert (row["pass"], row["error"]) == (False, "ValueError")
    assert SECRET_TEXT not in log.read_text() + out


def test_extraction_returning_the_wrong_number_of_criteria_fails_the_case(tmp_path):
    correct = _extractor(CORRECT)

    async def extract(criteria):
        results = await correct(criteria)
        return results[:-1] if len(criteria) == 3 and criteria[0] == "female" else results

    _, log = _run(tmp_path, _fixture(), extract)
    row = _case_row(log, "female_over_65_dm_form_split")
    assert (row["pass"], row["error"]) == (False, "ExtractionShapeError")


def test_interrupted_run_exits_integrity_failure_with_its_count(tmp_path, capsys):
    correct = _extractor(CORRECT)

    async def extract(criteria):
        if criteria == ["between 50 and 60 years old", "history of coronary artery bypass graft"]:
            raise KeyboardInterrupt  # not an Exception: the per-case handler can't absorb it
        return await correct(criteria)

    code, log = _run(tmp_path, _fixture(), extract, "--fail-under", "0")
    out = capsys.readouterr().out
    assert code == runner.EXIT_INTEGRITY  # wins over the accuracy gate
    assert "executed 6 / expected 12" in out
    assert _rows(log)[-1]["summary"]["executed"] == 6


def _one_case_wrong():
    return _extractor(dict(CORRECT, **{"type 2 diabetes": [_c("diabetes", "condition", "")]}))


def test_accuracy_below_fail_under_exits_threshold_failure(tmp_path, capsys):
    code, _ = _run(tmp_path, _fixture(), _one_case_wrong(), "--fail-under", "95")
    assert code == runner.EXIT_BELOW_THRESHOLD == 1
    assert "below --fail-under 95" in capsys.readouterr().out


def test_accuracy_at_fail_under_passes(tmp_path):
    # 11/12 = 91.7%.
    code, _ = _run(tmp_path, _fixture(), _one_case_wrong(), "--fail-under", "91.5")
    assert code == runner.EXIT_OK


def test_no_live_llm_client_refuses_to_run(tmp_path, capsys, monkeypatch):
    # An empty key, not an unset one: llm_client's load_dotenv refills an unset key
    # from .env, and would make this a billed run.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    log = tmp_path / "evals.jsonl"
    code = runner.main(["--log", str(log)])
    assert code == runner.EXIT_INTEGRITY
    assert "no live LLM client" in capsys.readouterr().out
    assert not log.exists()


def _broken(mutate):
    fixture = _fixture()
    mutate(fixture)
    return fixture


@pytest.mark.parametrize(
    "fixture",
    [
        _broken(lambda f: f["cases"][3].pop("signoff")),
        _broken(lambda f: f["cases"][3].update(signoff="  ")),
        _broken(lambda f: f["cases"][4].update(id=f["cases"][0]["id"])),
        _broken(lambda f: f["cases"][5].update(inclusion=[], exclusion=[])),
        _broken(lambda f: f["cases"][0]["inclusion"][0].update(expected=[])),
        _broken(lambda f: f["cases"][0]["inclusion"][0]["expected"][0].update(polarity="maybe")),
        _broken(lambda f: f["cases"][0]["inclusion"][0]["expected"][0].update(type="observation")),
        _broken(lambda f: f["cases"][0]["inclusion"][0]["expected"][0].update(terms=[])),
        _broken(lambda f: f["cases"][2]["inclusion"][0]["expected"][1].pop("age")),
        _broken(lambda f: f["cases"][2]["inclusion"][0]["expected"][1].update(age=[">"])),
        _broken(lambda f: f["cases"][3]["inclusion"][0]["expected"][0].update(gender="any")),
        _broken(lambda f: f.pop("cases")),
    ],
    ids=[
        "no-signoff",
        "blank-signoff",
        "duplicate-id",
        "no-criteria",
        "no-expected",
        "bad-polarity",
        "bad-type",
        "no-terms",
        "demographic-without-age-or-gender",
        "malformed-age",
        "bad-gender",
        "no-cases-key",
    ],
)
def test_malformed_fixture_exits_integrity_failure(tmp_path, capsys, fixture):
    code, log = _run(tmp_path, fixture, _never_called)
    assert code == runner.EXIT_INTEGRITY
    assert "INTEGRITY: the fixture is malformed" in capsys.readouterr().out
    assert not log.exists()


def test_checked_in_case_set_holds_the_approved_seed_cases():
    cases = runner.load_cases(CASES)
    assert len(cases) == 12
    expected = [
        e for c in cases for lst in runner.LISTS for i in c.get(lst, []) for e in i["expected"]
    ]
    assert any(e.get("polarity") == "excluded" for e in expected)  # a negation case
    assert any("temporal_within" in e for e in expected)  # a temporal case
    assert any(c.get("exclusion") for c in cases)
    assert all(c["signoff"].startswith("approved: repo owner") for c in cases)


def test_summary_reports_per_type_precision_recall_and_temporal(tmp_path, capsys):
    table = dict(
        CORRECT,
        **{
            # One extra demographic, and an HbA1c whose window is 3 months, not 6.
            "hypertension": [
                _c("hypertension", "condition", ""),
                _c("gender", "demographic", "male"),
            ],
            "HbA1c above 8% in the last 6 months": [
                _c("HbA1c", "lab", "> 8% in the past 3 months")
            ],
        },
    )
    _, log = _run(tmp_path, _fixture(), _extractor(table))
    out = capsys.readouterr().out
    summary = _rows(log)[-1]["summary"]
    # 9 demographic concepts expected (pairs 3, 6, 7 hold one; 4, 5, 10 hold two),
    # all found; the extra comes from "hypertension", which recurs in 3 cases.
    assert summary["by_type"]["demographic"] == {"tp": 9, "fp": 3, "fn": 0}
    assert summary["by_type"]["lab"] == {"tp": 1, "fp": 0, "fn": 0}
    assert summary["temporal"] == {"checked": 1, "matched": 0}
    assert "demographic: precision 0.75, recall 1.00" in out
    assert "temporal (report-only): 0/1 matched" in out
    # Timing doesn't affect pass or fail.
    assert _case_row(log, "hba1c_last_6_months")["pass"] is True


def test_unparseable_fixture_exits_integrity_failure(tmp_path, capsys):
    path = tmp_path / "cases.json"
    path.write_text("{not json")
    code = runner.main(["--cases", str(path), "--log", str(tmp_path / "l")], extract=_never_called)
    assert code == runner.EXIT_INTEGRITY


def test_emptied_fixture_exits_integrity_failure(tmp_path, capsys):
    fixture = _fixture()
    fixture["cases"] = []
    code, _ = _run(tmp_path, fixture, _never_called)
    assert code == runner.EXIT_INTEGRITY == 2
    assert "0 cases" in capsys.readouterr().out
