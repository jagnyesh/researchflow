"""Tests for app/schemas/a2a.py — Phase 2.3 Issue #6."""

import pytest
from pydantic import ValidationError

from app.schemas.a2a import TokenRequest


def test_minimum_valid():
    r = TokenRequest(client_id="agent-x", client_secret="agent-x")
    assert r.client_id == "agent-x"


def test_required_missing_id():
    with pytest.raises(ValidationError):
        TokenRequest(client_secret="x")


def test_required_missing_secret():
    with pytest.raises(ValidationError):
        TokenRequest(client_id="x")


def test_rejects_empty_id():
    with pytest.raises(ValidationError):
        TokenRequest(client_id="", client_secret="x")


def test_rejects_too_long_id():
    with pytest.raises(ValidationError):
        TokenRequest(client_id="x" * 201, client_secret="x")


def test_extra_field_rejected():
    with pytest.raises(ValidationError):
        TokenRequest(client_id="a", client_secret="b", grant_type="password")
