"""#205: data elements dispatch on a canonical ID, not the LLM's display string.

REQ-20261030-B2B6AD86 delivered zero rows: the requirements LLM wrote
"Demographics" (the dispatch only knew the exact form label) and
"Conditions/Diagnoses" had no dispatch at all. Executed live via the adapter.
"""

import pytest

from app.agents.extraction_agent import (
    FORM_DATA_ELEMENTS,
    DataExtractionAgent,
    canonical_data_element,
)


@pytest.fixture(autouse=True)
def _delivery_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DELIVERY_PATH", str(tmp_path))


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Demographics", "demographics"),
        ("Demographics (age, gender, race)", "demographics"),
        ("demographics", "demographics"),
        ("Conditions/Diagnoses", "diagnoses"),
        ("Diagnoses (ICD codes)", "diagnoses"),
        ("Procedures (CPT/HCPCS codes)", "procedures"),
        ("Lab Results (LOINC codes)", "lab_results"),
        ("lab_results", "lab_results"),
        # Spellings the requirements LLM produces (review of #205)
        ("Diagnoses/Conditions", "diagnoses"),
        ("condition", "diagnoses"),
        ("laboratory results", "lab_results"),
        ("demographic data", "demographics"),
        ("patient demographics", "demographics"),
        ("age", "demographics"),
        ("gender", "demographics"),
        ("Clinical Notes", None),
        ("Medication history", None),
        ("clinical_data", None),
    ],
)
def test_names_resolve_to_canonical_elements(name, expected):
    assert canonical_data_element(name) == expected


def test_every_form_option_dispatches():
    assert FORM_DATA_ELEMENTS and all(canonical_data_element(o) for o in FORM_DATA_ELEMENTS)


async def _patients(view: str, n: int = 3) -> list:
    from app.adapters.sql_on_fhir import SQLonFHIRAdapter

    rows = await SQLonFHIRAdapter().execute_sql(
        f"SELECT DISTINCT patient_id FROM sqlonfhir.{view} LIMIT {n}"  # nosec B608 - test constant
    )
    return [r["patient_id"] for r in rows]


@pytest.mark.requires_services
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,view",
    [
        ("Demographics", "patient_demographics"),
        ("Conditions/Diagnoses", "condition_diagnoses"),
        ("Procedures", "procedure_history"),
        ("Lab Results", "observation_labs"),
    ],
)
async def test_llm_normalized_names_extract_rows_for_the_cohort(name, view):
    ids = await _patients(view)
    agent = DataExtractionAgent()

    rows = await agent._extract_data_element(name, ids, {})
    preview = await agent._extract_data_element_preview(name, ids, {}, limit=2)

    assert rows and {r["patient_id"] for r in rows} <= set(ids)
    assert 0 < len(preview) <= 2


@pytest.mark.requires_services
@pytest.mark.asyncio
async def test_a_time_period_filters_on_the_element_date_column():
    ids = await _patients("condition_diagnoses", 20)
    agent = DataExtractionAgent()

    everything = await agent._extract_data_element("Diagnoses", ids, {})
    nothing = await agent._extract_data_element(
        "Diagnoses", ids, {"start": "1800-01-01", "end": "1800-12-31"}
    )

    assert everything and nothing == []


@pytest.mark.requires_services
@pytest.mark.asyncio
async def test_procedures_honour_a_time_period():
    # Synthea records procedures as performedPeriod, so performed_datetime is
    # almost always NULL; filtering on it alone returned nothing (#205 review).
    ids = await _patients("procedure_history", 50)

    rows = await DataExtractionAgent()._extract_data_element(
        "Procedures", ids, {"start": "1900-01-01", "end": "2100-12-31"}
    )

    assert rows


@pytest.mark.requires_services
@pytest.mark.asyncio
async def test_the_end_date_includes_that_whole_day():
    # A procedure performed at a time of day; BETWEEN on ISO text dropped every
    # timed value on the end day. Found in the database, not hardcoded, so this
    # holds on the local corpus and on CI's seed (whose conditions carry no dates).
    from app.adapters.sql_on_fhir import SQLonFHIRAdapter

    rows = await SQLonFHIRAdapter().execute_sql(
        "SELECT patient_id, COALESCE(performed_datetime, performed_period_start) AS performed "
        "FROM sqlonfhir.procedure_history "
        "WHERE COALESCE(performed_datetime, performed_period_start) LIKE '____-__-__T%' "
        "ORDER BY 2 DESC LIMIT 1"
    )
    assert rows, "vacuous: no timed procedure dates in this corpus"
    patient_id, performed = rows[0]["patient_id"], rows[0]["performed"]
    day = performed[:10]

    extracted = await DataExtractionAgent()._extract_data_element(
        "Procedures", [patient_id], {"start": day, "end": day}
    )

    assert any(
        (r["performed_datetime"] or r["performed_period_start"]) == performed for r in extracted
    )
