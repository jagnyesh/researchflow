"""Tests for app/schemas/auth.py — Phase 2.3 Issue #6."""

import pytest
from pydantic import ValidationError

from app.schemas.auth import LoginRequest


def test_minimum_valid():
    r = LoginRequest(email="alice@example.edu", password="hunter2")
    assert r.email == "alice@example.edu"


def test_required_missing_email():
    with pytest.raises(ValidationError):
        LoginRequest(password="hunter2")


def test_required_missing_password():
    with pytest.raises(ValidationError):
        LoginRequest(email="alice@example.edu")


@pytest.mark.parametrize("bad_email", ["not-an-email", "missing-at.com", ""])
def test_rejects_invalid_email(bad_email):
    with pytest.raises(ValidationError):
        LoginRequest(email=bad_email, password="hunter2")


def test_rejects_empty_password():
    with pytest.raises(ValidationError):
        LoginRequest(email="alice@example.edu", password="")


def test_rejects_password_over_200():
    with pytest.raises(ValidationError):
        LoginRequest(email="alice@example.edu", password="x" * 201)


def test_extra_field_rejected():
    with pytest.raises(ValidationError):
        LoginRequest(email="alice@example.edu", password="hunter2", role_override="admin")
