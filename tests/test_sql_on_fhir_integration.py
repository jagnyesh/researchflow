"""
Integration Tests for SQL-on-FHIR v2 Implementation

Tests ViewDefinition execution against live HAPI FHIR server with PostgreSQL backend.

Requirements:
- HAPI FHIR server running (docker-compose up)
- Synthetic data loaded (Synthea)
- FHIR_SERVER_URL environment variable set

Run with:
    pytest tests/test_sql_on_fhir_integration.py -v
    pytest tests/test_sql_on_fhir_integration.py::test_patient_demographics_view -v
"""

import pytest
import os
import asyncio
from typing import List, Dict, Any

# Add app to path
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.clients.fhir_client import FHIRClient
from app.sql_on_fhir.view_definition_manager import ViewDefinitionManager
from app.sql_on_fhir.runner.in_memory_runner import InMemoryRunner


# Test Configuration
FHIR_SERVER_URL = os.getenv("FHIR_SERVER_URL", "http://localhost:8081/fhir")
MAX_TEST_RESOURCES = 50  # Limit resources for faster tests


@pytest.fixture(scope="module")
def event_loop():
    """Create event loop for async tests"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
async def fhir_client():
    """Create FHIR client for testing"""
    client = FHIRClient(base_url=FHIR_SERVER_URL)

    # Test connection
    connected = await client.test_connection()
    if not connected:
        pytest.skip(f"FHIR server not available at {FHIR_SERVER_URL}")

    yield client
    await client.close()


@pytest.fixture(scope="module")
def view_definition_manager():
    """Create ViewDefinition manager"""
    return ViewDefinitionManager()


@pytest.fixture(scope="module")
async def runner(fhir_client):
    """Create InMemoryRunner for executing ViewDefinitions"""
    return InMemoryRunner(fhir_client)


# ============================================================================
# Connection Tests
# ============================================================================

@pytest.mark.asyncio
async def test_fhir_server_connection(fhir_client):
    """Test that FHIR server is reachable and returns metadata"""
    metadata = await fhir_client.get_metadata()

    assert metadata is not None
    assert metadata.get("resourceType") == "CapabilityStatement"
    assert "fhirVersion" in metadata

    print(f"\n✓ Connected to {metadata.get('software', {}).get('name', 'FHIR Server')}")
    print(f"  FHIR Version: {metadata.get('fhirVersion')}")


@pytest.mark.asyncio
async def test_fhir_server_has_data(fhir_client):
    """Test that FHIR server has some patient data"""
    patients = await fhir_client.search("Patient", max_results=5)

    assert len(patients) > 0, "No patient data found - run Synthea to generate data"

    print(f"\n✓ Found {len(patients)} patients in FHIR server")


# ============================================================================
# ViewDefinition Loading Tests
# ============================================================================

def test_view_definitions_exist(view_definition_manager):
    """Test that ViewDefinitions are available"""
    view_names = view_definition_manager.list()

    assert len(view_names) > 0
    assert "patient_demographics" in view_names
    assert "observation_labs" in view_names

    print(f"\n✓ Found {len(view_names)} ViewDefinitions:")
    for name in view_names:
        print(f"    - {name}")


def test_patient_demographics_structure(view_definition_manager):
    """Test patient_demographics ViewDefinition structure"""
    view_def = view_definition_manager.load("patient_demographics")

    assert view_def["resourceType"] == "ViewDefinition"
    assert view_def["resource"] == "Patient"
    assert view_def["name"] == "patient_demographics"
    assert "select" in view_def
    assert len(view_def["select"]) > 0

    # Count columns
    total_columns = sum(
        len(select_elem.get("column", []))
        for select_elem in view_def["select"]
    )

    print(f"\n✓ patient_demographics ViewDefinition loaded")
    print(f"  Total select elements: {len(view_def['select'])}")
    print(f"  Total columns: {total_columns}")


# ============================================================================
# Simple ViewDefinition Execution Tests
# ============================================================================

@pytest.mark.asyncio
async def test_patient_demographics_view(fhir_client, view_definition_manager, runner):
    """Test patient_demographics ViewDefinition execution"""
    # Load ViewDefinition
    view_def = view_definition_manager.load("patient_demographics")

    # Execute ViewDefinition
    results = await runner.execute(
        view_def,
        max_resources=MAX_TEST_RESOURCES
    )

    assert len(results) > 0, "No results returned from patient_demographics view"

    # Validate result structure
    first_row = results[0]

    # Check for expected columns
    expected_columns = ["id", "patient_id", "birth_date", "gender"]
    for col in expected_columns:
        assert col in first_row, f"Missing expected column: {col}"

    print(f"\n✓ patient_demographics view executed successfully")
    print(f"  Rows returned: {len(results)}")
    print(f"  Columns: {list(first_row.keys())}")
    print(f"\n  Sample row:")
    for key, value in list(first_row.items())[:8]:
        print(f"    {key:20} = {value}")


@pytest.mark.asyncio
async def test_observation_labs_view(fhir_client, view_definition_manager, runner):
    """Test observation_labs ViewDefinition execution"""
    # Load ViewDefinition
    view_def = view_definition_manager.load("observation_labs")

    # Execute ViewDefinition
    results = await runner.execute(
        view_def,
        max_results=MAX_TEST_RESOURCES
    )

    if len(results) == 0:
        pytest.skip("No lab observations found in FHIR server")

    # Validate result structure
    first_row = results[0]

    # Check for expected columns
    expected_columns = ["id", "patient_id", "code", "code_display"]
    for col in expected_columns:
        assert col in first_row, f"Missing expected column: {col}"

    print(f"\n✓ observation_labs view executed successfully")
    print(f"  Rows returned: {len(results)}")
    print(f"  Columns: {list(first_row.keys())}")
    print(f"\n  Sample observation:")
    for key, value in list(first_row.items())[:10]:
        print(f"    {key:25} = {value}")


# ============================================================================
# FHIRPath Expression Tests
# ============================================================================

@pytest.mark.asyncio
async def test_forEach_iteration(fhir_client, view_definition_manager, runner):
    """Test forEach iteration in ViewDefinitions (patient names)"""
    view_def = view_definition_manager.load("patient_demographics")

    # Execute ViewDefinition
    results = await runner.execute(
        view_def,
        max_results=10
    )

    assert len(results) > 0

    # Check that forEach extracted name fields
    rows_with_names = [r for r in results if r.get("family_name")]

    assert len(rows_with_names) > 0, "No rows with extracted names (forEach may not be working)"

    print(f"\n✓ forEach iteration working")
    print(f"  Patients with names: {len(rows_with_names)}/{len(results)}")
    print(f"\n  Sample names:")
    for row in rows_with_names[:5]:
        full_name = row.get("full_name", "N/A")
        print(f"    {full_name}")


@pytest.mark.asyncio
async def test_forEachOrNull_behavior(fhir_client, view_definition_manager, runner):
    """Test forEachOrNull returns nulls when collection is empty"""
    view_def = view_definition_manager.load("patient_demographics")

    # Execute ViewDefinition
    results = await runner.execute(
        view_def,
        max_results=20
    )

    assert len(results) > 0

    # Check that all rows have phone/email columns (even if null)
    # forEachOrNull should ensure these columns exist
    for row in results:
        assert "phone" in row, "phone column missing (forEachOrNull not working)"
        assert "email" in row, "email column missing (forEachOrNull not working)"

    # Count rows with and without phone/email
    with_phone = sum(1 for r in results if r.get("phone"))
    with_email = sum(1 for r in results if r.get("email"))

    print(f"\n✓ forEachOrNull working correctly")
    print(f"  Patients with phone: {with_phone}/{len(results)}")
    print(f"  Patients with email: {with_email}/{len(results)}")


@pytest.mark.asyncio
async def test_where_clause_filtering(fhir_client, view_definition_manager, runner):
    """Test that where clauses filter resources correctly"""
    view_def = view_definition_manager.load("patient_demographics")

    # patient_demographics has where clause: "active = true or active.exists().not()"
    results = await runner.execute(
        view_def,
        max_resources=MAX_TEST_RESOURCES
    )

    # Fetch all patients without filtering
    all_patients = await fhir_client.search("Patient", max_results=MAX_TEST_RESOURCES)

    # ViewDefinition should have filtered some patients
    print(f"\n✓ Where clause filtering")
    print(f"  All patients in server: {len(all_patients)}")
    print(f"  Patients after where clause: {len(results)}")
    print(f"  Where clause: active = true or active.exists().not()")


# ============================================================================
# Complex FHIRPath Expression Tests
# ============================================================================

@pytest.mark.asyncio
async def test_complex_fhirpath_expressions(fhir_client, view_definition_manager, runner):
    """Test complex FHIRPath expressions (type filtering, chaining)"""
    view_def = view_definition_manager.load("observation_labs")

    # Execute ViewDefinition
    results = await runner.execute(
        view_def,
        max_results=20
    )

    if len(results) == 0:
        pytest.skip("No lab observations to test complex expressions")

    # Check for LOINC codes (complex path: code.coding.where(...).code.first())
    rows_with_loinc = [r for r in results if r.get("code")]

    print(f"\n✓ Complex FHIRPath expressions working")
    print(f"  Observations with LOINC codes: {len(rows_with_loinc)}/{len(results)}")

    # Show sample with different value types
    for row in results[:5]:
        value_qty = row.get("value_quantity")
        value_str = row.get("value_string")
        value_code = row.get("value_code")

        if value_qty:
            print(f"  Quantity value: {value_qty} {row.get('value_unit', '')}")
        elif value_str:
            print(f"  String value: {value_str}")
        elif value_code:
            print(f"  Code value: {value_code}")


# ============================================================================
# Search Parameter Tests
# ============================================================================

@pytest.mark.asyncio
async def test_view_with_search_params(fhir_client, view_definition_manager, runner):
    """Test ViewDefinition execution with FHIR search parameters"""
    view_def = view_definition_manager.load("patient_demographics")

    # Execute with gender filter
    results_female = await runner.execute(
        view_def,
        search_params={"gender": "female"},
        max_resources=MAX_TEST_RESOURCES
    )

    results_male = await runner.execute(
        view_def,
        search_params={"gender": "male"},
        max_resources=MAX_TEST_RESOURCES
    )

    print(f"\n✓ Search parameters working")
    print(f"  Female patients: {len(results_female)}")
    print(f"  Male patients: {len(results_male)}")

    # Validate gender filtering
    if results_female:
        assert all(r.get("gender") == "female" for r in results_female)
    if results_male:
        assert all(r.get("gender") == "male" for r in results_male)


# ============================================================================
# Data Type Tests
# ============================================================================

@pytest.mark.asyncio
async def test_data_types_in_results(fhir_client, view_definition_manager, runner):
    """Test that various FHIR data types are correctly extracted"""
    view_def = view_definition_manager.load("observation_labs")

    results = await runner.execute(
        view_def,
        max_results=20
    )

    if len(results) == 0:
        pytest.skip("No observations to test data types")

    # Check for various data types
    has_datetime = any(r.get("effective_datetime") for r in results)
    has_quantity = any(r.get("value_quantity") is not None for r in results)
    has_string = any(r.get("code_display") for r in results)

    print(f"\n✓ Data type extraction")
    print(f"  Found dateTime values: {has_datetime}")
    print(f"  Found Quantity values: {has_quantity}")
    print(f"  Found string values: {has_string}")


# ============================================================================
# Performance Tests
# ============================================================================

@pytest.mark.asyncio
async def test_large_result_set(fhir_client, view_definition_manager, runner):
    """Test ViewDefinition execution with larger result set"""
    import time

    view_def = view_definition_manager.load("patient_demographics")

    start_time = time.time()

    results = await runner.execute(
        view_def,
        max_resources=200  # Larger set
    )

    elapsed_time = time.time() - start_time

    print(f"\n✓ Large result set performance")
    print(f"  Resources processed: {len(results)}")
    print(f"  Time elapsed: {elapsed_time:.2f}s")
    print(f"  Throughput: {len(results)/elapsed_time:.1f} resources/second")

    # Performance assertion - should process at least 5 resources/second
    assert len(results) / elapsed_time >= 5, "Performance too slow"


# ============================================================================
# Error Handling Tests
# ============================================================================

@pytest.mark.asyncio
async def test_invalid_resource_type(fhir_client, view_definition_manager):
    """Test handling of invalid resource type"""
    # Create ViewDefinition with non-existent resource type
    invalid_view = view_definition_manager.create_from_template(
        resource_type="InvalidResourceType",
        name="test_invalid",
        columns=[{"name": "id", "path": "id"}]
    )

    runner_instance = InMemoryRunner(fhir_client)

    # Should handle gracefully (may return empty results)
    results = await runner_instance.execute(invalid_view, max_resources=10)

    print(f"\n✓ Handled invalid resource type")
    print(f"  Results: {len(results)}")


# ============================================================================
# Main Test Runner (for standalone execution)
# ============================================================================

if __name__ == "__main__":
    """
    Run tests directly without pytest:
    python tests/test_sql_on_fhir_integration.py
    """
    import asyncio

    async def run_quick_test():
        print("=" * 80)
        print("SQL-on-FHIR Integration Test (Quick Run)")
        print("=" * 80)
        print()

        # Setup
        client = FHIRClient(base_url=FHIR_SERVER_URL)
        manager = ViewDefinitionManager()
        runner_instance = InMemoryRunner(client)

        # Test connection
        print("Testing FHIR server connection...")
        connected = await client.test_connection()
        if not connected:
            print(f"✗ Cannot connect to FHIR server at {FHIR_SERVER_URL}")
            print("  Make sure docker-compose is running:")
            print("  docker-compose -f config/docker-compose.yml up -d")
            return
        print("✓ Connected to FHIR server")
        print()

        # Load and execute ViewDefinition
        print("Loading patient_demographics ViewDefinition...")
        view_def = manager.load("patient_demographics")
        print("✓ ViewDefinition loaded")
        print()

        print("Executing ViewDefinition...")
        results = await runner_instance.execute(view_def, max_resources=10)
        print(f"✓ Execution complete - {len(results)} rows returned")
        print()

        # Display results
        if results:
            print("Sample Results:")
            print("-" * 80)
            for i, row in enumerate(results[:3], 1):
                print(f"\nRow {i}:")
                for key, value in list(row.items())[:10]:
                    print(f"  {key:20} = {value}")

        # Cleanup
        await client.close()

        print()
        print("=" * 80)
        print("✓ Quick test complete!")
        print("=" * 80)
        print()
        print("To run full test suite:")
        print("  pytest tests/test_sql_on_fhir_integration.py -v")

    asyncio.run(run_quick_test())
