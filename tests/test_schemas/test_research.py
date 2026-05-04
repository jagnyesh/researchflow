"""Tests for app/schemas/research.py — Phase 2.3 Issue #5."""

import pytest
from pydantic import ValidationError

from app.schemas.research import RequestProcessingTrigger, ResearchRequestSubmission


def _valid_submission(**overrides) -> dict:
    base = {
        "researcher_name": "Dr. Alice Smith",
        "researcher_email": "alice@example.edu",
        "irb_number": "IRB-2024-001",
        "initial_request": "Find all diabetes patients with HbA1c > 7",
    }
    base.update(overrides)
    return base


# --- happy path ---


def test_minimum_valid_submission():
    body = _valid_submission()
    req = ResearchRequestSubmission(**body)
    assert req.researcher_name == "Dr. Alice Smith"
    assert req.researcher_email == "alice@example.edu"
    assert req.researcher_department is None
    assert req.structured_requirements is None


def test_full_valid_submission():
    body = _valid_submission(
        researcher_department="Cardiology",
        structured_requirements={"resources": ["Patient"], "filters": [{"age": ">18"}]},
    )
    req = ResearchRequestSubmission(**body)
    assert req.researcher_department == "Cardiology"
    assert req.structured_requirements == {
        "resources": ["Patient"],
        "filters": [{"age": ">18"}],
    }


# --- required-missing ---


@pytest.mark.parametrize(
    "missing",
    ["researcher_name", "researcher_email", "irb_number", "initial_request"],
)
def test_required_field_missing(missing):
    body = _valid_submission()
    body.pop(missing)
    with pytest.raises(ValidationError) as exc_info:
        ResearchRequestSubmission(**body)
    assert any(e["type"] == "missing" and e["loc"][-1] == missing for e in exc_info.value.errors())


# --- email validation (was bare str before Phase 2.3) ---


@pytest.mark.parametrize("bad_email", ["not-an-email", "missing-at.com", "@example.com", ""])
def test_rejects_invalid_email(bad_email):
    with pytest.raises(ValidationError):
        ResearchRequestSubmission(**_valid_submission(researcher_email=bad_email))


# --- IRB regex ---


@pytest.mark.parametrize(
    "good_irb",
    ["IRB-001", "IRB-2024-001", "IRB-2024-HF-001", "IRB-2025-001", "IRB-2025-E2E-TEST-001"],
)
def test_accepts_known_irb_formats(good_irb):
    req = ResearchRequestSubmission(**_valid_submission(irb_number=good_irb))
    assert req.irb_number == good_irb


@pytest.mark.parametrize("bad_irb", ["hello", "12345", "REQ-2024-001", "irb-2024-001"])
def test_rejects_garbage_irb(bad_irb):
    with pytest.raises(ValidationError):
        ResearchRequestSubmission(**_valid_submission(irb_number=bad_irb))


# --- length caps ---


def test_initial_request_at_50k_passes():
    body = _valid_submission(initial_request="x" * 50000)
    req = ResearchRequestSubmission(**body)
    assert len(req.initial_request) == 50000


def test_initial_request_over_50k_rejects():
    body = _valid_submission(initial_request="x" * 50001)
    with pytest.raises(ValidationError):
        ResearchRequestSubmission(**body)


def test_researcher_name_over_200_rejects():
    body = _valid_submission(researcher_name="x" * 201)
    with pytest.raises(ValidationError):
        ResearchRequestSubmission(**body)


# --- BoundedDict on structured_requirements ---


def test_structured_requirements_at_100_keys_passes():
    big = {f"k{i}": i for i in range(100)}
    req = ResearchRequestSubmission(**_valid_submission(structured_requirements=big))
    assert len(req.structured_requirements) == 100


def test_structured_requirements_over_100_keys_rejects():
    big = {f"k{i}": i for i in range(101)}
    with pytest.raises(ValidationError):
        ResearchRequestSubmission(**_valid_submission(structured_requirements=big))


# --- extra-fields-forbidden (PHIInputModel base) ---


def test_extra_field_rejected():
    body = _valid_submission(is_admin=True)
    with pytest.raises(ValidationError) as exc_info:
        ResearchRequestSubmission(**body)
    assert any(e["type"] == "extra_forbidden" for e in exc_info.value.errors())


# --- RequestProcessingTrigger ---


def test_processing_trigger_default_no_skip():
    trig = RequestProcessingTrigger()
    assert trig.skip_conversation is False
    assert trig.structured_requirements is None


def test_processing_trigger_with_dict():
    trig = RequestProcessingTrigger(
        structured_requirements={"resources": ["Patient"]}, skip_conversation=True
    )
    assert trig.skip_conversation is True


def test_processing_trigger_extra_field_rejected():
    with pytest.raises(ValidationError):
        RequestProcessingTrigger(skip_conversation=False, secret_admin_flag=True)
