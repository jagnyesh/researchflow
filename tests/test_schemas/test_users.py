"""Tests for app/schemas/users.py — Phase 2.3 Issue #6."""

import pytest
from pydantic import ValidationError

from app.schemas.users import PasswordChange, UserCreate, UserUpdate


# --- UserCreate ---


def test_create_minimum_valid():
    u = UserCreate(email="bob@example.edu", full_name="Bob", password="hunter2")
    assert u.role == "researcher"  # default
    assert u.department is None


def test_create_with_all_fields():
    u = UserCreate(
        email="bob@example.edu",
        full_name="Bob",
        department="Cardiology",
        role="data_steward",
        password="hunter2",
    )
    assert u.role == "data_steward"


@pytest.mark.parametrize("role", ["researcher", "data_steward", "admin"])
def test_create_role_literal_accepts_known(role):
    u = UserCreate(email="b@c.co", full_name="B", role=role, password="x")
    assert u.role == role


@pytest.mark.parametrize("role", ["superuser", "owner", "guest", ""])
def test_create_role_literal_rejects_unknown(role):
    with pytest.raises(ValidationError):
        UserCreate(email="b@c.co", full_name="B", role=role, password="x")


def test_create_required_email_missing():
    with pytest.raises(ValidationError):
        UserCreate(full_name="Bob", password="x")


def test_create_email_must_be_valid():
    with pytest.raises(ValidationError):
        UserCreate(email="not-an-email", full_name="Bob", password="x")


def test_create_extra_field_rejected():
    with pytest.raises(ValidationError):
        UserCreate(email="b@c.co", full_name="B", password="x", is_super_admin=True)


# --- UserUpdate ---


def test_update_all_optional():
    u = UserUpdate()
    assert u.full_name is None
    assert u.department is None
    assert u.role is None
    assert u.is_active is None


def test_update_partial():
    u = UserUpdate(department="Endocrinology", is_active=False)
    assert u.department == "Endocrinology"
    assert u.is_active is False


def test_update_role_literal_enforced():
    with pytest.raises(ValidationError):
        UserUpdate(role="god-mode")


def test_update_extra_field_rejected():
    with pytest.raises(ValidationError):
        UserUpdate(department="X", inject="bad")


# --- PasswordChange ---


def test_password_change_valid():
    p = PasswordChange(current_password="old", new_password="new")
    assert p.new_password == "new"


def test_password_change_missing_current():
    with pytest.raises(ValidationError):
        PasswordChange(new_password="new")


def test_password_change_empty_rejected():
    with pytest.raises(ValidationError):
        PasswordChange(current_password="", new_password="new")


def test_password_change_over_cap_rejected():
    with pytest.raises(ValidationError):
        PasswordChange(current_password="ok", new_password="x" * 201)


def test_password_change_extra_field_rejected():
    with pytest.raises(ValidationError):
        PasswordChange(current_password="a", new_password="b", reset_token="bypass")
