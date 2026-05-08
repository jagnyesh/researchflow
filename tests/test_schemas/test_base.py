"""Tests for app/schemas/_base.py — Phase 2.3 PHIInputModel base class (Issue #4)."""

import pytest
from pydantic import ValidationError

from app.schemas._base import PHIInputModel
from app.schemas._types import ShortText


class _Sample(PHIInputModel):
    name: ShortText


def test_unknown_field_is_rejected():
    """`extra='forbid'` is the load-bearing config — defends against attacker-supplied keys."""
    with pytest.raises(ValidationError) as exc_info:
        _Sample(name="ok", is_admin=True)
    # The error type from Pydantic v2 for extra fields is "extra_forbidden"
    assert any(e["type"] == "extra_forbidden" for e in exc_info.value.errors())


def test_known_field_accepts_normal_value():
    assert _Sample(name="alice").name == "alice"


def test_whitespace_is_stripped():
    """`str_strip_whitespace=True` normalizes input."""
    assert _Sample(name="  alice  ").name == "alice"


def test_assignment_revalidates():
    """`validate_assignment=True` catches post-construction mutations that violate constraints."""
    s = _Sample(name="alice")
    with pytest.raises(ValidationError):
        s.name = "x" * 201  # exceeds ShortText cap


def test_phi_input_model_is_base_model_subclass():
    from pydantic import BaseModel

    assert issubclass(PHIInputModel, BaseModel)
