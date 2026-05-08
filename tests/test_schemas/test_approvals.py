"""Tests for app/schemas/approvals.py — Phase 2.3 Issue #5."""

import pytest
from pydantic import ValidationError

from app.schemas.approvals import ApprovalResponse, ScopeChangeRequest


# --- ApprovalResponse ---


def test_approval_minimum_valid():
    r = ApprovalResponse(decision="approve", reviewer="alice")
    assert r.decision == "approve"
    assert r.notes is None
    assert r.modifications is None


@pytest.mark.parametrize("d", ["approve", "reject", "modify"])
def test_approval_decision_literal_accepts_known(d):
    r = ApprovalResponse(decision=d, reviewer="alice")
    assert r.decision == d


@pytest.mark.parametrize("d", ["approved", "yes", "no", "rubber-stamp", ""])
def test_approval_decision_literal_rejects_unknown(d):
    with pytest.raises(ValidationError):
        ApprovalResponse(decision=d, reviewer="alice")


def test_approval_with_modifications():
    r = ApprovalResponse(
        decision="modify",
        reviewer="alice@example.edu",
        notes="Tighten the inclusion criteria",
        modifications={"min_age": 18, "include_genders": ["M", "F"]},
    )
    assert r.modifications["min_age"] == 18


def test_approval_extra_field_rejected():
    with pytest.raises(ValidationError):
        ApprovalResponse(decision="approve", reviewer="alice", overridden=True)


def test_approval_required_missing():
    with pytest.raises(ValidationError) as exc_info:
        ApprovalResponse(reviewer="alice")
    assert any(
        e["type"] == "missing" and e["loc"][-1] == "decision" for e in exc_info.value.errors()
    )


def test_approval_modifications_bounded_dict():
    big = {f"k{i}": i for i in range(101)}
    with pytest.raises(ValidationError):
        ApprovalResponse(decision="modify", reviewer="alice", modifications=big)


# --- ScopeChangeRequest ---


def test_scope_change_minimum_valid():
    s = ScopeChangeRequest(
        request_id="REQ-20260504-ABC12345",
        requested_by="alice@example.edu",
        requested_changes={"add_resource": "Observation"},
    )
    assert s.reason is None


def test_scope_change_with_reason():
    s = ScopeChangeRequest(
        request_id="REQ-20260504-ABC12345",
        requested_by="alice@example.edu",
        requested_changes={"add_resource": "Observation"},
        reason="IRB amendment approved expanded scope",
    )
    assert s.reason.startswith("IRB amendment")


def test_scope_change_rejects_invalid_email():
    with pytest.raises(ValidationError):
        ScopeChangeRequest(
            request_id="REQ-20260504-ABC12345",
            requested_by="not-an-email",
            requested_changes={"x": 1},
        )


def test_scope_change_required_changes_missing():
    with pytest.raises(ValidationError) as exc_info:
        ScopeChangeRequest(request_id="REQ-20260504-ABC12345", requested_by="alice@example.edu")
    assert any(
        e["type"] == "missing" and e["loc"][-1] == "requested_changes"
        for e in exc_info.value.errors()
    )


def test_scope_change_extra_field_rejected():
    with pytest.raises(ValidationError):
        ScopeChangeRequest(
            request_id="REQ-20260504-ABC12345",
            requested_by="alice@example.edu",
            requested_changes={"x": 1},
            backdoor=True,
        )


def test_scope_change_changes_bounded_dict():
    deep = {"a": {"b": {"c": {"d": {"e": {"f": "too deep"}}}}}}
    with pytest.raises(ValidationError):
        ScopeChangeRequest(
            request_id="REQ-1",
            requested_by="alice@example.edu",
            requested_changes=deep,
        )
