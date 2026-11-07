"""#209: each QA cohort/PHI check fails on a crafted mismatch.

Case from REQ-20261030-B2B6AD86 (synthetic counts only): estimate 156, real
cohort 13, preview list cut to 10 rows.
"""

import pytest

from app.agents.qa_agent import QualityAssuranceAgent

# A de-identified delivery carries HMAC pseudonyms, never source ids (#306).
PSEUDONYM = "DEID-" + "0" * 32


def _preview_package(full_cohort_size: int, preview_rows: int = 10) -> dict:
    return {
        "cohort": [{"patient_id": f"p{i}"} for i in range(preview_rows)],
        "preview_data": {},
        "metadata": {"cohort_size": full_cohort_size, "is_preview": True},
    }


@pytest.mark.asyncio
async def test_preview_check_routes_an_out_of_band_cohort_to_human_review():
    result = await QualityAssuranceAgent().execute_task(
        "validate_preview",
        {"request_id": "REQ-1", "estimated_cohort": 156, "preview_package": _preview_package(13)},
    )

    check = result["qa_report"]["checks"][0]
    assert result["preview_qa_passed"] is False
    assert result["approval_type"] == "preview_qa"
    assert check["details"]["actual_cohort_size"] == 13  # metadata, not the 10-row list


@pytest.mark.asyncio
async def test_preview_check_passes_a_cohort_inside_the_tolerance():
    result = await QualityAssuranceAgent().execute_task(
        "validate_preview",
        {"request_id": "REQ-1", "estimated_cohort": 100, "preview_package": _preview_package(95)},
    )

    assert result["preview_qa_passed"] is True


def _final_context(cohort_size: int, estimate, phi_level="identified", records=None) -> dict:
    return {
        "request_id": "REQ-1",
        "structured_requirements": {"phi_level": phi_level, "data_elements": ["demographics"]},
        "feasibility_report": {"estimated_cohort_size": estimate},
        "data_package": {
            "cohort": [{"patient_id": f"p{i}"} for i in range(cohort_size)],
            "data_elements": {"demographics": records or []},
        },
    }


def _check(result, name):
    return next(c for c in result["qa_report"]["checks"] if c["check_name"] == name)


@pytest.mark.asyncio
async def test_final_cohort_check_compares_against_the_stored_estimate():
    result = await QualityAssuranceAgent().execute_task(
        "validate_extracted_data", _final_context(cohort_size=13, estimate=156)
    )

    check = _check(result, "cohort_validation")
    assert check["details"]["estimated_size"] == 156
    assert check["passed"] is False


@pytest.mark.asyncio
async def test_deidentification_fails_on_the_name_columns_extraction_emits():
    records = [
        {"patient_id": PSEUDONYM, "family_name": "Synthetic", "given_name": "Person", "gender": "f"}
    ]
    result = await QualityAssuranceAgent().execute_task(
        "validate_extracted_data",
        _final_context(cohort_size=1, estimate=1, phi_level="de-identified", records=records),
    )

    check = _check(result, "deidentification")
    assert check["passed"] is False
    assert set(check["details"]["identifiers_found"]) == {"family_name", "given_name"}
    assert result["overall_status"] == "failed"


@pytest.mark.asyncio
async def test_deidentification_records_what_it_checked_when_clean():
    records = [{"patient_id": PSEUDONYM, "gender": "f"}]
    result = await QualityAssuranceAgent().execute_task(
        "validate_extracted_data",
        _final_context(cohort_size=1, estimate=1, phi_level="de-identified", records=records),
    )

    check = _check(result, "deidentification")
    assert check["passed"] is True
    assert check["details"]["columns_inspected"] == ["gender", "patient_id"]
    assert check["details"]["identifiers_found"] == []


@pytest.mark.asyncio
async def test_the_workflow_qa_node_hands_the_phenotype_estimate_to_qa(monkeypatch, tmp_path):
    # The final check only works if the real QA node passes the estimate stored
    # at phenotype time; its context used to omit it.
    from app.langchain_orchestrator.langgraph_workflow import FullWorkflow

    monkeypatch.setenv("DATA_DELIVERY_PATH", str(tmp_path))

    workflow = FullWorkflow(use_real_agents=True)
    state = {
        "request_id": "REQ-1",
        "estimated_cohort_size": 156,
        "requirements": {"phi_level": "identified", "data_elements": ["demographics"]},
        "extracted_data_summary": {
            "cohort": [{"patient_id": f"p{i}"} for i in range(13)],
            "data_elements": {"demographics": []},
        },
    }

    state = await workflow._handle_qa_validation(state)

    check = next(c for c in state["qa_report"]["checks"] if c["check_name"] == "cohort_validation")
    assert check["details"]["estimated_size"] == 156
    assert check["passed"] is False
