"""Tests for app/schemas/sql_on_fhir.py — Phase 2.3 Issue #5 (tracer bullet)."""

import pytest
from pydantic import ValidationError

from app.schemas.sql_on_fhir import SQLQueryRequest


# --- 1. happy path ---


def test_accepts_simple_select():
    req = SQLQueryRequest(sql="SELECT 1")
    assert req.sql == "SELECT 1"


def test_accepts_complex_query():
    req = SQLQueryRequest(sql="SELECT * FROM patient WHERE id = 'abc' AND age > 18;")
    assert req.sql.startswith("SELECT")


# --- 2. required field missing ---


def test_rejects_missing_sql():
    with pytest.raises(ValidationError) as exc_info:
        SQLQueryRequest()
    assert any(e["type"] == "missing" for e in exc_info.value.errors())


# --- 3. boundary: LongText cap (50,000 chars) ---


def test_accepts_at_50k_cap():
    sql = "SELECT '" + ("x" * 49991) + "'"  # exactly 50000 chars
    assert len(sql) == 50000
    req = SQLQueryRequest(sql=sql)
    assert len(req.sql) == 50000


def test_rejects_one_over_50k():
    sql = "x" * 50001
    with pytest.raises(ValidationError):
        SQLQueryRequest(sql=sql)


# --- 4. type rejection ---


def test_rejects_int_for_sql():
    with pytest.raises(ValidationError):
        SQLQueryRequest(sql=12345)


def test_rejects_list_for_sql():
    with pytest.raises(ValidationError):
        SQLQueryRequest(sql=["SELECT 1"])


# --- PHIInputModel base behavior: extra fields forbidden ---


def test_rejects_extra_fields():
    """Defends against attacker submitting {sql: '...', is_admin: true}."""
    with pytest.raises(ValidationError) as exc_info:
        SQLQueryRequest(sql="SELECT 1", is_admin=True)
    assert any(e["type"] == "extra_forbidden" for e in exc_info.value.errors())


# --- PHIInputModel base behavior: whitespace stripped ---


def test_strips_whitespace_around_sql():
    req = SQLQueryRequest(sql="  SELECT 1  ")
    assert req.sql == "SELECT 1"


# --- inherits from PHIInputModel ---


def test_inherits_phi_input_model():
    from app.schemas import PHIInputModel

    assert issubclass(SQLQueryRequest, PHIInputModel)
