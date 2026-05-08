"""Tests for app/schemas/mcp.py — Phase 2.3 Issue #5."""

import pytest
from pydantic import ValidationError

from app.schemas.mcp import ContextRequest


def test_minimum_valid():
    r = ContextRequest(request_id="REQ-1", context={"k": "v"})
    assert r.request_id == "REQ-1"


def test_required_missing_request_id():
    with pytest.raises(ValidationError):
        ContextRequest(context={"k": "v"})


def test_required_missing_context():
    with pytest.raises(ValidationError):
        ContextRequest(request_id="REQ-1")


def test_request_id_too_long():
    with pytest.raises(ValidationError):
        ContextRequest(request_id="x" * 201, context={})


def test_context_bounded_dict():
    big = {f"k{i}": i for i in range(101)}
    with pytest.raises(ValidationError):
        ContextRequest(request_id="REQ-1", context=big)


def test_extra_field_rejected():
    with pytest.raises(ValidationError):
        ContextRequest(request_id="REQ-1", context={}, hidden=True)
