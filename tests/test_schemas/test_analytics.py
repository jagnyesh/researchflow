"""Tests for app/schemas/analytics.py — Phase 2.3 Issue #5."""

import pytest
from pydantic import ValidationError

from app.schemas.analytics import (
    CountRequest,
    CreateViewDefinitionRequest,
    ViewDefinitionRequest,
)


# --- ViewDefinitionRequest ---


def test_viewdef_minimum_valid():
    r = ViewDefinitionRequest(view_name="patient_demographics")
    assert r.view_name == "patient_demographics"
    assert r.search_params is None
    assert r.max_resources is None


def test_viewdef_with_search_params():
    r = ViewDefinitionRequest(
        view_name="patient_demographics",
        search_params={"gender": "F", "_count": "100"},
        max_resources=500,
    )
    assert r.max_resources == 500


def test_viewdef_required_missing():
    with pytest.raises(ValidationError):
        ViewDefinitionRequest()


def test_viewdef_view_name_too_long():
    with pytest.raises(ValidationError):
        ViewDefinitionRequest(view_name="x" * 201)


def test_viewdef_search_params_bounded():
    big = {f"k{i}": i for i in range(101)}
    with pytest.raises(ValidationError):
        ViewDefinitionRequest(view_name="ok", search_params=big)


def test_viewdef_extra_field_rejected():
    with pytest.raises(ValidationError):
        ViewDefinitionRequest(view_name="ok", overridden=True)


# --- CreateViewDefinitionRequest ---


def test_create_viewdef_minimum_valid():
    r = CreateViewDefinitionRequest(view_definition={"resource": "Patient", "select": []})
    assert r.name is None


def test_create_viewdef_required_definition():
    with pytest.raises(ValidationError):
        CreateViewDefinitionRequest()


def test_create_viewdef_definition_bounded():
    deep = {"a": {"b": {"c": {"d": {"e": {"f": "deep"}}}}}}
    with pytest.raises(ValidationError):
        CreateViewDefinitionRequest(view_definition=deep)


def test_create_viewdef_with_name():
    r = CreateViewDefinitionRequest(view_definition={"resource": "Patient"}, name="custom_view")
    assert r.name == "custom_view"


def test_create_viewdef_extra_field_rejected():
    with pytest.raises(ValidationError):
        CreateViewDefinitionRequest(view_definition={"x": 1}, secret=True)


# --- CountRequest ---


def test_count_minimum_valid():
    r = CountRequest(view_name="diabetes_cohort")
    assert r.search_params is None


def test_count_with_search_params():
    r = CountRequest(view_name="diabetes_cohort", search_params={"_count": "0"})
    assert r.search_params["_count"] == "0"


def test_count_required_missing():
    with pytest.raises(ValidationError):
        CountRequest()


def test_count_search_params_bounded():
    big = {f"k{i}": i for i in range(101)}
    with pytest.raises(ValidationError):
        CountRequest(view_name="ok", search_params=big)
