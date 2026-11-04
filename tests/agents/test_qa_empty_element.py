"""#205: a requested data element that extracted no rows fails QA.

Before, completeness compared element keys only, and extraction writes a key
(with []) for every requested element, so an empty delivery passed QA.
"""

import pytest

from app.agents.qa_agent import QualityAssuranceAgent


def _context(elements: dict) -> dict:
    return {
        "request_id": "REQ-1",
        "structured_requirements": {"phi_level": "identified", "data_elements": list(elements)},
        "feasibility_report": {"estimated_cohort_size": 2},
        "data_package": {
            "cohort": [{"patient_id": "p0"}, {"patient_id": "p1"}],
            "data_elements": elements,
        },
    }


def _completeness(result):
    return next(c for c in result["qa_report"]["checks"] if c["check_name"] == "completeness")


@pytest.mark.asyncio
async def test_an_empty_requested_element_fails_qa_and_is_named():
    rows = [{"patient_id": "p0", "gender": "female"}, {"patient_id": "p1", "gender": "male"}]
    result = await QualityAssuranceAgent().execute_task(
        "validate_extracted_data", _context({"demographics": rows, "medications": []})
    )

    check = _completeness(result)
    assert result["qa_report"]["overall_status"] == "failed"
    assert check["passed"] is False
    assert check["details"]["missing_elements"] == ["medications"]


@pytest.mark.asyncio
async def test_every_element_with_rows_passes_completeness():
    rows = [{"patient_id": "p0", "gender": "female"}, {"patient_id": "p1", "gender": "male"}]
    result = await QualityAssuranceAgent().execute_task(
        "validate_extracted_data", _context({"demographics": rows})
    )

    assert _completeness(result)["passed"] is True
