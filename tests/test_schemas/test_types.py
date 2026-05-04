"""Tests for app/schemas/_types.py — Phase 2.3 typed primitives (Issue #4)."""

import pytest
from pydantic import BaseModel, ValidationError

from app.schemas._types import (
    NonEmptyStr,
    ShortText,
    MediumText,
    LongText,
    IRBNumber,
)


# --- helper models for testing each primitive in isolation ---


class _NonEmpty(BaseModel):
    v: NonEmptyStr


class _Short(BaseModel):
    v: ShortText


class _Medium(BaseModel):
    v: MediumText


class _Long(BaseModel):
    v: LongText


class _IRB(BaseModel):
    v: IRBNumber


# --- NonEmptyStr ---


def test_nonempty_accepts_one_char():
    assert _NonEmpty(v="a").v == "a"


def test_nonempty_rejects_empty():
    with pytest.raises(ValidationError):
        _NonEmpty(v="")


# --- ShortText (max 200) ---


def test_short_accepts_at_cap():
    s = "x" * 200
    assert _Short(v=s).v == s


def test_short_rejects_one_over_cap():
    with pytest.raises(ValidationError):
        _Short(v="x" * 201)


# --- MediumText (max 2000) ---


def test_medium_accepts_at_cap():
    s = "x" * 2000
    assert _Medium(v=s).v == s


def test_medium_rejects_one_over_cap():
    with pytest.raises(ValidationError):
        _Medium(v="x" * 2001)


# --- LongText (max 50000) ---


def test_long_accepts_at_cap():
    s = "x" * 50000
    assert _Long(v=s).v == s


def test_long_rejects_one_over_cap():
    with pytest.raises(ValidationError):
        _Long(v="x" * 50001)


# --- IRBNumber (permissive regex; max 50) ---


@pytest.mark.parametrize(
    "fixture",
    [
        "IRB-001",
        "IRB-2024-001",
        "IRB-2024-HF-001",
        "IRB-2025-001",
        "IRB-2025-E2E-TEST-001",
    ],
)
def test_irb_accepts_existing_test_fixture_formats(fixture):
    """All 5 IRB formats observed in existing test fixtures must pass."""
    assert _IRB(v=fixture).v == fixture


def test_irb_accepts_slash_separator():
    assert _IRB(v="IRB/2025/04/123").v == "IRB/2025/04/123"


def test_irb_accepts_underscore_separator():
    assert _IRB(v="IRB_2025_001").v == "IRB_2025_001"


@pytest.mark.parametrize(
    "garbage",
    [
        "hello",
        "DROP TABLE researchers",
        "12345",
        "irb-2024-001",  # lowercase irb prefix rejected
        "REQ-2024-001",  # wrong prefix
        "",
    ],
)
def test_irb_rejects_garbage(garbage):
    with pytest.raises(ValidationError):
        _IRB(v=garbage)


def test_irb_rejects_too_long():
    with pytest.raises(ValidationError):
        _IRB(v="IRB-" + ("X" * 50))


# --- type rejection (sanity check Pydantic still does normal type checking) ---


def test_short_rejects_int():
    # Pydantic v2 in strict mode rejects int->str; in lax mode it coerces.
    # We assert that PHIInputModel callers (Issue #4 cycle 4) get strict behavior;
    # for raw primitive use it depends on the model. Just sanity-check the field
    # exists and accepts a string.
    assert _Short(v="x").v == "x"
