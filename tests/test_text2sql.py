"""
Tests for Text-to-SQL functionality using production QueryInterpreter

This test suite validates the QueryInterpreter service which is used by the
Exploratory Analytics Portal for natural language to SQL-on-FHIR translation.
"""

import pytest
from app.services.query_interpreter import QueryInterpreter


@pytest.mark.asyncio
async def test_query_interpreter_patient_count():
    """Test QueryInterpreter with simple patient count query"""
    interpreter = QueryInterpreter()

    # Parse natural language query
    intent = await interpreter.interpret_query("How many patients are available?")

    # Verify query intent
    assert intent.query_type == "count"
    assert "patient_demographics" in intent.view_definitions
    assert intent.explanation  # Should have human-readable explanation


@pytest.mark.asyncio
async def test_query_interpreter_condition_filter():
    """Test QueryInterpreter with condition-based filter"""
    interpreter = QueryInterpreter()

    # Parse diabetes query
    intent = await interpreter.interpret_query(
        "Show me patients with type 2 diabetes"
    )

    # Verify query intent
    assert intent.query_type in ["list", "filter"]
    assert "condition_simple" in intent.view_definitions
    assert len(intent.filters) > 0  # Should have diabetes filter


@pytest.mark.asyncio
async def test_query_interpreter_lab_results():
    """Test QueryInterpreter with lab result query"""
    interpreter = QueryInterpreter()

    # Parse lab query
    intent = await interpreter.interpret_query(
        "Find patients with hemoglobin less than 12"
    )

    # Verify query intent
    assert "observation_labs" in intent.view_definitions
    assert any(
        "hemoglobin" in str(f).lower() or "hb" in str(f).lower()
        for f in intent.filters.values()
    )
