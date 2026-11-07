"""#306: a de-identified extract meets the Safe Harbor floor; other levels are unchanged.

Rows are synthetic. The SQL layer is stubbed (`_execute_phenotype_query`,
`_extract_data_element`) so the test drives the real `extract_data` task and
reads its output package and the CSVs it writes, then hands that package to
the real QA agent.
"""

import csv
import hashlib
import hmac
import re
import string
from pathlib import Path

import pytest

from app.agents.extraction_agent import DATA_ELEMENT_SOURCES, DataExtractionAgent
from app.agents.qa_agent import (
    DEIDENTIFIED_ID_COLUMNS,
    DEIDENTIFIED_PASSTHROUGH_COLUMNS,
    DEIDENTIFIED_YEAR_COLUMNS,
    DIRECT_IDENTIFIER_COLUMNS,
    QualityAssuranceAgent,
)

# Test-only keys, built so no literal looks like a secret to the scanners.
KEY = string.ascii_lowercase + string.digits
OTHER_KEY = string.ascii_uppercase + string.digits
FULL_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

ROWS = {
    "Demographics": [
        {
            "patient_id": "101",
            "family_name": "Synthfam",
            "given_name": "Synthgiven",
            "gender": "female",
            "birth_date": "1970-04-12",
        },
        {
            "patient_id": "102",
            "family_name": "Otherfam",
            "given_name": "Othergiven",
            "gender": "male",
            "birth_date": "1985-11-30",
        },
    ],
    "Diagnoses": [
        {
            "patient_id": "101",
            "condition_id": "5001",
            "clinical_status": "active",
            "icd10_code": "E11.9",
            "onset_datetime": "2015-03-02T10:00:00+00:00",
            "recorded_date": "2015-03-03",
        }
    ],
    "Procedures": [
        {
            "patient_id": "102",
            "procedure_id": "6001",
            "cpt_code": "99213",
            "performed_datetime": None,
            "performed_period_start": "2019-07-08T09:30:00Z",
        }
    ],
    "Lab Results": [
        {
            "patient_id": "101",
            "observation_id": "7001",
            "code": "4548-4",
            "value_quantity": 7.2,
            "value_string": "2020-01-02",
            "effective_datetime": "2020-01-02T08:00:00Z",
        }
    ],
}


@pytest.fixture(autouse=True)
def _delivery_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DELIVERY_PATH", str(tmp_path))
    monkeypatch.setenv("DEIDENTIFICATION_HMAC_KEY", KEY)
    return tmp_path


def _pseudonym(column: str, value: str) -> str:
    digest = hmac.new(KEY.encode(), f"{column}:{value}".encode(), hashlib.sha256).hexdigest()
    return f"DEID-{digest[:32]}"


async def _extract(monkeypatch, phi_level: str) -> dict:
    agent = DataExtractionAgent()

    async def cohort(sql, params):
        return [{"patient_id": "101"}, {"patient_id": "102"}]

    async def element(data_element, patient_ids, time_period):
        return [dict(r) for r in ROWS[data_element]]

    monkeypatch.setattr(agent, "_execute_phenotype_query", cohort)
    monkeypatch.setattr(agent, "_extract_data_element", element)
    result = await agent.execute_task(
        "extract_data",
        {
            "request_id": "REQ-306",
            "structured_requirements": {"phi_level": phi_level, "data_elements": list(ROWS)},
            "sql_query": "SELECT 1",
        },
    )
    return result["data_package"] if "data_package" in result else result


def _package(result: dict) -> dict:
    return result.get("additional_context", {}).get("data_package") or result


def _records(package):
    return [r for recs in package["data_elements"].values() for r in recs]


def _csv_text(tmp_path: Path) -> str:
    return "\n".join(p.read_text() for p in tmp_path.rglob("*.csv"))


async def _qa(package: dict, phi_level: str) -> dict:
    result = await QualityAssuranceAgent().execute_task(
        "validate_extracted_data",
        {
            "request_id": "REQ-306",
            "structured_requirements": {"phi_level": phi_level, "data_elements": list(ROWS)},
            "feasibility_report": {"estimated_cohort_size": len(package["cohort"])},
            "data_package": package,
        },
    )
    return next(c for c in result["qa_report"]["checks"] if c["check_name"] == "deidentification")


# --- extraction output boundary -------------------------------------------------


@pytest.mark.asyncio
async def test_deidentified_extract_drops_names(monkeypatch, _delivery_dir):
    package = _package(await _extract(monkeypatch, "de-identified"))

    for record in _records(package):
        assert not {"family_name", "given_name", "patient_name", "mrn", "ssn"} & set(record)
    text = _csv_text(_delivery_dir)
    assert text, "vacuous: no CSV written"
    for name in ("Synthfam", "Synthgiven", "Otherfam", "Othergiven"):
        assert name not in text


@pytest.mark.asyncio
async def test_deidentified_extract_reduces_every_date_to_the_year(monkeypatch, _delivery_dir):
    package = _package(await _extract(monkeypatch, "de-identified"))
    elements = package["data_elements"]

    for record in _records(package):
        for value in record.values():
            assert not FULL_DATE.search(str(value)), record
    assert not FULL_DATE.search(_csv_text(_delivery_dir))
    assert [r["birth_year"] for r in elements["Demographics"]] == [1970, 1985]
    dx = elements["Diagnoses"][0]
    assert (dx["onset_year"], dx["recorded_year"]) == (2015, 2015)
    px = elements["Procedures"][0]
    assert (px["performed_year"], px["performed_period_start_year"]) == (None, 2019)
    lab = elements["Lab Results"][0]
    assert (lab["effective_year"], lab["value_string"]) == (2020, 2020)


@pytest.mark.asyncio
async def test_deidentified_ids_are_keyed_hmac_pseudonyms(monkeypatch):
    package = _package(await _extract(monkeypatch, "de-identified"))
    elements = package["data_elements"]

    assert [r["patient_id"] for r in elements["Demographics"]] == [
        _pseudonym("patient_id", "101"),
        _pseudonym("patient_id", "102"),
    ]
    # Same patient, same pseudonym across elements, so researchers can join.
    assert elements["Diagnoses"][0]["patient_id"] == _pseudonym("patient_id", "101")
    assert elements["Diagnoses"][0]["condition_id"] == _pseudonym("condition_id", "5001")
    assert elements["Procedures"][0]["procedure_id"] == _pseudonym("procedure_id", "6001")
    assert elements["Lab Results"][0]["observation_id"] == _pseudonym("observation_id", "7001")


@pytest.mark.asyncio
async def test_a_different_key_gives_different_pseudonyms(monkeypatch):
    first = _package(await _extract(monkeypatch, "de-identified"))
    monkeypatch.setenv("DEIDENTIFICATION_HMAC_KEY", OTHER_KEY)
    second = _package(await _extract(monkeypatch, "de-identified"))

    a = first["data_elements"]["Demographics"][0]["patient_id"]
    b = second["data_elements"]["Demographics"][0]["patient_id"]
    assert a != b


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value",
    [None, "", "short", " " * 32, "\t" * 40, "a" * 32, "ab" * 20, "0123456789abcdef" + " " * 20],
)
async def test_deidentified_extract_fails_without_a_usable_key(
    monkeypatch, value, _delivery_dir, caplog
):
    if value is None:
        monkeypatch.delenv("DEIDENTIFICATION_HMAC_KEY")
    else:
        monkeypatch.setenv("DEIDENTIFICATION_HMAC_KEY", value)

    with pytest.raises(RuntimeError, match="DEIDENTIFICATION_HMAC_KEY"):
        await _extract(monkeypatch, "de-identified")
    assert not _csv_text(_delivery_dir)
    assert "DEIDENTIFICATION_HMAC_KEY" in caplog.text


@pytest.mark.asyncio
async def test_identified_extract_is_unchanged_and_needs_no_key(monkeypatch):
    monkeypatch.delenv("DEIDENTIFICATION_HMAC_KEY")
    package = _package(await _extract(monkeypatch, "identified"))

    assert package["data_elements"] == ROWS


@pytest.mark.asyncio
async def test_limited_dataset_extract_is_unchanged_and_needs_no_key(monkeypatch):
    monkeypatch.delenv("DEIDENTIFICATION_HMAC_KEY")
    package = _package(await _extract(monkeypatch, "limited_dataset"))

    # Pre-#306 behaviour: only patient_name and ssn are dropped; dates and ids stay.
    assert package["data_elements"] == ROWS


# --- QA verdict -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_qa_passes_the_deidentified_extract(monkeypatch):
    package = _package(await _extract(monkeypatch, "de-identified"))

    check = await _qa(package, "de-identified")
    assert check["passed"] is True, check["issues"]


def _deid_package(record: dict) -> dict:
    return {"cohort": [{"patient_id": "x"}], "data_elements": {"Diagnoses": [record]}}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "column",
    [
        "birth_date",
        "onset_datetime",
        "recorded_date",
        "performed_datetime",
        "performed_period_start",
        "effective_datetime",
    ],
)
async def test_qa_fails_a_full_date_column_in_a_deidentified_delivery(column):
    check = await _qa(
        _deid_package({"patient_id": _pseudonym("patient_id", "1"), column: None}),
        "de-identified",
    )

    assert check["passed"] is False
    assert column in check["details"]["identifiers_found"]


@pytest.mark.asyncio
async def test_qa_fails_a_full_date_value_under_any_column_name():
    check = await _qa(
        _deid_package({"patient_id": _pseudonym("patient_id", "1"), "value_string": "2020-01-02"}),
        "de-identified",
    )

    assert check["passed"] is False
    assert "value_string" in check["details"]["identifiers_found"]


@pytest.mark.asyncio
async def test_qa_fails_a_raw_id_in_a_deidentified_delivery():
    check = await _qa(_deid_package({"patient_id": "101", "gender": "female"}), "de-identified")

    assert check["passed"] is False
    assert "patient_id" in check["details"]["identifiers_found"]


@pytest.mark.asyncio
async def test_qa_still_allows_dates_and_raw_ids_in_a_limited_dataset():
    check = await _qa(
        _deid_package({"patient_id": "101", "onset_datetime": "2015-03-02T10:00:00Z"}),
        "limited_dataset",
    )

    assert check["passed"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("level", ["safe_harbor", None, "Deidentified"])
async def test_an_unrecognized_phi_level_gets_the_deidentified_treatment(monkeypatch, level):
    # The workflow's fallback stub sends "safe_harbor"; it used to skip every rule.
    package = _package(await _extract(monkeypatch, level))

    assert package["metadata"]["phi_level"] == "de-identified"
    assert (await _qa(package, "de-identified"))["passed"] is True
    for record in _records(package):
        assert "family_name" not in record and "birth_date" not in record


@pytest.mark.asyncio
@pytest.mark.parametrize("level", ["safe_harbor", None])
async def test_qa_applies_the_date_rule_to_an_unrecognized_phi_level(level):
    check = await _qa(
        _deid_package({"patient_id": _pseudonym("patient_id", "1"), "onset_datetime": None}),
        level,
    )

    assert check["passed"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("label", ["Date of Birth", "Demographics (age, gender, race)"])
async def test_the_consolidated_demographics_csv_carries_only_the_birth_year(
    monkeypatch, _delivery_dir, label
):
    agent = DataExtractionAgent()

    async def cohort(sql, params):
        return [{"patient_id": "101"}]

    async def element(data_element, patient_ids, time_period):
        return [dict(ROWS["Demographics"][0])]

    monkeypatch.setattr(agent, "_execute_phenotype_query", cohort)
    monkeypatch.setattr(agent, "_extract_data_element", element)
    await agent.execute_task(
        "extract_data",
        {
            "request_id": "REQ-306",
            "structured_requirements": {"phi_level": "de-identified", "data_elements": [label]},
            "sql_query": "SELECT 1",
        },
    )

    rows = list(csv.DictReader((_delivery_dir / "REQ-306" / "Demographics.csv").open()))
    assert len(rows) == 1 and "birth_date" not in rows[0]
    assert rows[0]["birth_year"] == "1970"
    assert rows[0]["patient_id"] == _pseudonym("patient_id", "101")
    assert not FULL_DATE.search(_csv_text(_delivery_dir))


# --- allowlist shape (review pass 1) ---------------------------------------------


def test_every_view_column_is_classified_once():
    classes = [
        DEIDENTIFIED_PASSTHROUGH_COLUMNS,
        DEIDENTIFIED_ID_COLUMNS,
        set(DEIDENTIFIED_YEAR_COLUMNS),
        DIRECT_IDENTIFIER_COLUMNS,
    ]
    for _view, columns, _date_expr in DATA_ELEMENT_SOURCES.values():
        for column in (c.strip() for c in columns.split(",")):
            assert sum(column in c for c in classes) == 1, column
    years = list(DEIDENTIFIED_YEAR_COLUMNS.values())
    assert len(set(years)) == len(years)
    assert not set(years) & (DEIDENTIFIED_PASSTHROUGH_COLUMNS | DEIDENTIFIED_ID_COLUMNS)


async def _deidentify(record: dict) -> dict:
    data = await DataExtractionAgent()._deidentify_data({"x": [dict(record)]}, "de-identified")
    return data["x"][0]


UNCLASSIFIED = {
    "Family_Name": "Synthfam",
    "Patient_ID": "101",
    "id": "101",
    "patientId": "101",
    "subject_reference": "Patient/101",
    "zip": "02139",
    "address_line": "1 Synthetic St",
    "phone_number": "555-0100",
    "extra": {"birthDate": "1970-04-12"},
}


@pytest.mark.asyncio
@pytest.mark.parametrize("column", sorted(UNCLASSIFIED))
async def test_an_unclassified_column_is_dropped_and_fails_qa(column):
    record = {"patient_id": "101", column: UNCLASSIFIED[column]}

    assert await _deidentify(record) == {"patient_id": _pseudonym("patient_id", "101")}
    check = await _qa(
        _deid_package({"patient_id": _pseudonym("patient_id", "1"), **{column: record[column]}}),
        "de-identified",
    )
    assert check["passed"] is False and column in check["details"]["identifiers_found"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value,year",
    [
        ("1980", 1980),
        ("1980-04", 1980),
        ("19800412", 1980),
        ("1980-04-12", 1980),
        ("1980-04-12T10:00:00.123+05:30", 1980),
        ("not a date", None),
        ("04/12/1980", None),
        (12, None),
    ],
)
async def test_date_columns_keep_the_year_of_partial_and_compact_dates(value, year):
    assert (await _deidentify({"birth_date": value}))["birth_year"] == year


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value",
    ["2019-20 season influenza vaccine", "seen 2020", "2020", 7.2, None],
)
async def test_passthrough_text_that_is_not_a_whole_date_is_kept(value):
    assert (await _deidentify({"code_text": value}))["code_text"] == value


@pytest.mark.asyncio
async def test_non_scalar_passthrough_values_are_dropped():
    out = await _deidentify({"value_string": {"when": "2020-01-02"}, "code": ["2020-01-02"]})

    assert out == {"value_string": None, "code": None}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "column,value",
    [
        ("birth_year", "1970-04-12"),
        ("onset_year", 20150302),
        ("value_string", {"when": "x"}),
        ("value_quantity", True),
    ],
)
async def test_qa_fails_a_value_that_is_not_safe_for_its_column(column, value):
    check = await _qa(
        _deid_package({"patient_id": _pseudonym("patient_id", "1"), column: value}),
        "de-identified",
    )

    assert check["passed"] is False and column in check["details"]["identifiers_found"]
