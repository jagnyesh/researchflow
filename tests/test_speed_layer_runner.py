"""
Unit Tests for SpeedLayerRunner (Lambda Architecture Speed Layer)

Tests the Redis-based speed layer query runner that retrieves
recent FHIR data not yet materialized in the batch layer.

Test Coverage:
- Resource type extraction from ViewDefinitions
- Recent resource querying with time filters
- Search parameter filtering (gender, code)
- Patient ID extraction
- Result limit handling
- Empty cache scenarios
- Multiple resource types
"""

import pytest
import asyncio
import os
from datetime import datetime, timedelta
from pathlib import Path
import sys

# Add project to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.cache.redis_client import RedisClient
from app.sql_on_fhir.runner.speed_layer_runner import SpeedLayerRunner


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
async def redis_client():
    """Create RedisClient instance for testing"""
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/1")  # Use DB 1 for tests
    client = RedisClient(redis_url=redis_url)

    # Connect
    await client.connect()

    # Clean up any existing test data
    await client.flush_all()

    yield client

    # Cleanup after test
    await client.flush_all()
    await client.disconnect()


@pytest.fixture
async def speed_runner(redis_client):
    """Create SpeedLayerRunner instance"""
    return SpeedLayerRunner(redis_client)


@pytest.fixture
def patient_view_def():
    """Sample Patient ViewDefinition"""
    return {
        "resourceType": "ViewDefinition",
        "resource": "Patient",
        "name": "patient_simple",
        "title": "Simple Patient Data",
        "status": "active",
        "select": [
            {
                "column": [
                    {"name": "id", "path": "id"},
                    {"name": "gender", "path": "gender"},
                    {"name": "birth_date", "path": "birthDate"}
                ]
            }
        ]
    }


@pytest.fixture
def condition_view_def():
    """Sample Condition ViewDefinition"""
    return {
        "resourceType": "ViewDefinition",
        "resource": "Condition",
        "name": "condition_simple",
        "title": "Patient Conditions",
        "status": "active",
        "select": [
            {
                "column": [
                    {"name": "id", "path": "id"},
                    {"name": "patient_ref", "path": "subject.reference"},
                    {"name": "code_text", "path": "code.text"}
                ]
            }
        ]
    }


@pytest.fixture
def sample_patients():
    """Sample FHIR Patient resources"""
    return [
        {
            "resourceType": "Patient",
            "id": "patient-001",
            "gender": "male",
            "birthDate": "1980-01-15",
            "name": [{"family": "Smith", "given": ["John"]}]
        },
        {
            "resourceType": "Patient",
            "id": "patient-002",
            "gender": "female",
            "birthDate": "1985-03-20",
            "name": [{"family": "Johnson", "given": ["Jane"]}]
        },
        {
            "resourceType": "Patient",
            "id": "patient-003",
            "gender": "male",
            "birthDate": "1990-07-10",
            "name": [{"family": "Williams", "given": ["Bob"]}]
        }
    ]


@pytest.fixture
def sample_conditions():
    """Sample FHIR Condition resources"""
    return [
        {
            "resourceType": "Condition",
            "id": "condition-001",
            "subject": {"reference": "Patient/patient-001"},
            "code": {
                "coding": [{
                    "system": "http://snomed.info/sct",
                    "code": "73211009",
                    "display": "Diabetes mellitus"
                }],
                "text": "Diabetes mellitus"
            },
            "clinicalStatus": {
                "coding": [{"code": "active"}]
            }
        },
        {
            "resourceType": "Condition",
            "id": "condition-002",
            "subject": {"reference": "Patient/patient-002"},
            "code": {
                "coding": [{
                    "system": "http://snomed.info/sct",
                    "code": "38341003",
                    "display": "Hypertension"
                }],
                "text": "Hypertension"
            },
            "clinicalStatus": {
                "coding": [{"code": "active"}]
            }
        },
        {
            "resourceType": "Condition",
            "id": "condition-003",
            "subject": {"reference": "Patient/patient-001"},
            "code": {
                "coding": [{
                    "system": "http://snomed.info/sct",
                    "code": "73211009",
                    "display": "Diabetes mellitus"
                }],
                "text": "Diabetes mellitus"
            },
            "clinicalStatus": {
                "coding": [{"code": "resolved"}]
            }
        }
    ]


# ============================================================================
# Test 1: Resource Type Extraction
# ============================================================================

@pytest.mark.asyncio
async def test_get_resource_type(speed_runner, patient_view_def, condition_view_def):
    """Test extracting resource type from ViewDefinition"""
    print("\n" + "="*60)
    print("TEST 1: Resource Type Extraction")
    print("="*60)

    # Test Patient resource
    resource_type = speed_runner._get_resource_type(patient_view_def)
    assert resource_type == "Patient", f"❌ Expected 'Patient', got '{resource_type}'"
    print("✓ Correctly extracted 'Patient' from ViewDefinition")

    # Test Condition resource
    resource_type = speed_runner._get_resource_type(condition_view_def)
    assert resource_type == "Condition", f"❌ Expected 'Condition', got '{resource_type}'"
    print("✓ Correctly extracted 'Condition' from ViewDefinition")

    # Test ViewDefinition with 'from' field
    view_def_with_from = {
        "name": "test_view",
        "select": [{"from": "Observation.subject", "column": []}]
    }
    resource_type = speed_runner._get_resource_type(view_def_with_from)
    assert resource_type == "Observation", f"❌ Expected 'Observation', got '{resource_type}'"
    print("✓ Correctly extracted 'Observation' from 'from' field")

    # Test default fallback
    empty_view_def = {"name": "empty", "select": []}
    resource_type = speed_runner._get_resource_type(empty_view_def)
    assert resource_type == "Patient", f"❌ Expected default 'Patient', got '{resource_type}'"
    print("✓ Correctly used default 'Patient' for empty ViewDefinition")

    print("\n✅ TEST PASSED")


# ============================================================================
# Test 2: Execute with Empty Cache
# ============================================================================

@pytest.mark.asyncio
async def test_execute_empty_cache(speed_runner, patient_view_def):
    """Test querying when Redis cache is empty"""
    print("\n" + "="*60)
    print("TEST 2: Execute with Empty Cache")
    print("="*60)

    # Query empty cache
    result = await speed_runner.execute(
        view_definition=patient_view_def,
        max_resources=100
    )

    # Verify structure
    assert result["view_name"] == "patient_simple", "❌ Wrong view name"
    assert result["source"] == "speed_layer", "❌ Wrong source"
    assert result["total_count"] == 0, "❌ Expected 0 results"
    assert len(result["patient_ids"]) == 0, "❌ Expected empty patient_ids"
    assert len(result["resources"]) == 0, "❌ Expected empty resources"
    assert "query_timestamp" in result, "❌ Missing query_timestamp"
    assert "since" in result, "❌ Missing since timestamp"

    print("✓ Result structure is correct")
    print(f"✓ Total count: {result['total_count']}")
    print(f"✓ Source: {result['source']}")

    print("\n✅ TEST PASSED")


# ============================================================================
# Test 3: Execute with Patient Resources
# ============================================================================

@pytest.mark.asyncio
async def test_execute_with_patients(redis_client, speed_runner, patient_view_def, sample_patients):
    """Test querying Patient resources from Redis"""
    print("\n" + "="*60)
    print("TEST 3: Execute with Patient Resources")
    print("="*60)

    # Cache sample patients
    for patient in sample_patients:
        await redis_client.set_fhir_resource(
            "Patient", patient["id"], patient, ttl_hours=24
        )

    print(f"✓ Cached {len(sample_patients)} patients in Redis")

    # Query speed layer
    result = await speed_runner.execute(
        view_definition=patient_view_def,
        max_resources=100
    )

    # Verify results
    assert result["total_count"] == 3, f"❌ Expected 3 patients, got {result['total_count']}"
    assert len(result["patient_ids"]) == 3, f"❌ Expected 3 patient IDs"
    assert len(result["resources"]) == 3, f"❌ Expected 3 resources"

    # Check patient IDs
    expected_ids = {"patient-001", "patient-002", "patient-003"}
    actual_ids = set(result["patient_ids"])
    assert actual_ids == expected_ids, f"❌ Patient IDs don't match: {actual_ids}"

    print(f"✓ Found {result['total_count']} patients")
    print(f"✓ Patient IDs: {result['patient_ids']}")

    print("\n✅ TEST PASSED")


# ============================================================================
# Test 4: Gender Filter
# ============================================================================

@pytest.mark.asyncio
async def test_gender_filter(redis_client, speed_runner, patient_view_def, sample_patients):
    """Test filtering patients by gender"""
    print("\n" + "="*60)
    print("TEST 4: Gender Filter")
    print("="*60)

    # Cache sample patients
    for patient in sample_patients:
        await redis_client.set_fhir_resource(
            "Patient", patient["id"], patient, ttl_hours=24
        )

    # Query for male patients only
    result = await speed_runner.execute(
        view_definition=patient_view_def,
        search_params={"gender": "male"},
        max_resources=100
    )

    # Verify only male patients returned
    assert result["total_count"] == 2, f"❌ Expected 2 male patients, got {result['total_count']}"

    # Verify gender of returned resources
    for resource in result["resources"]:
        assert resource["gender"] == "male", f"❌ Found non-male patient: {resource['id']}"

    print(f"✓ Filtered to {result['total_count']} male patients")
    print(f"✓ Patient IDs: {result['patient_ids']}")

    # Query for female patients
    result_female = await speed_runner.execute(
        view_definition=patient_view_def,
        search_params={"gender": "female"},
        max_resources=100
    )

    assert result_female["total_count"] == 1, f"❌ Expected 1 female patient, got {result_female['total_count']}"
    assert result_female["patient_ids"][0] == "patient-002", "❌ Wrong female patient returned"

    print(f"✓ Filtered to {result_female['total_count']} female patient")

    print("\n✅ TEST PASSED")


# ============================================================================
# Test 5: Condition Resources with Patient ID Extraction
# ============================================================================

@pytest.mark.asyncio
async def test_condition_resources(redis_client, speed_runner, condition_view_def, sample_conditions):
    """Test querying Condition resources and extracting patient IDs"""
    print("\n" + "="*60)
    print("TEST 5: Condition Resources with Patient ID Extraction")
    print("="*60)

    # Cache sample conditions
    for condition in sample_conditions:
        await redis_client.set_fhir_resource(
            "Condition", condition["id"], condition, ttl_hours=24
        )

    print(f"✓ Cached {len(sample_conditions)} conditions in Redis")

    # Query speed layer
    result = await speed_runner.execute(
        view_definition=condition_view_def,
        max_resources=100
    )

    # Verify results
    assert result["total_count"] == 2, f"❌ Expected 2 unique patients, got {result['total_count']}"
    assert len(result["resources"]) == 3, f"❌ Expected 3 condition resources"

    # Check patient IDs extracted from subject references
    expected_patient_ids = {"patient-001", "patient-002"}
    actual_patient_ids = set(result["patient_ids"])
    assert actual_patient_ids == expected_patient_ids, f"❌ Patient IDs don't match: {actual_patient_ids}"

    print(f"✓ Found {len(result['resources'])} conditions")
    print(f"✓ Extracted {result['total_count']} unique patient IDs: {result['patient_ids']}")

    print("\n✅ TEST PASSED")


# ============================================================================
# Test 6: Code Filter for Conditions
# ============================================================================

@pytest.mark.asyncio
async def test_code_filter(redis_client, speed_runner, condition_view_def, sample_conditions):
    """Test filtering conditions by code"""
    print("\n" + "="*60)
    print("TEST 6: Code Filter for Conditions")
    print("="*60)

    # Cache sample conditions
    for condition in sample_conditions:
        await redis_client.set_fhir_resource(
            "Condition", condition["id"], condition, ttl_hours=24
        )

    # Filter for diabetes (SNOMED code 73211009)
    result = await speed_runner.execute(
        view_definition=condition_view_def,
        search_params={"code": "73211009"},
        max_resources=100
    )

    # Should find 2 diabetes conditions
    assert len(result["resources"]) == 2, f"❌ Expected 2 diabetes conditions, got {len(result['resources'])}"

    # Verify all returned conditions have diabetes code
    for resource in result["resources"]:
        codes = [c["code"] for c in resource["code"]["coding"]]
        assert "73211009" in codes, f"❌ Resource doesn't have diabetes code: {resource['id']}"

    print(f"✓ Filtered to {len(result['resources'])} diabetes conditions")

    # Filter for hypertension (SNOMED code 38341003)
    result_htn = await speed_runner.execute(
        view_definition=condition_view_def,
        search_params={"code": "38341003"},
        max_resources=100
    )

    assert len(result_htn["resources"]) == 1, f"❌ Expected 1 hypertension condition, got {len(result_htn['resources'])}"
    assert result_htn["resources"][0]["id"] == "condition-002", "❌ Wrong condition returned"

    print(f"✓ Filtered to {len(result_htn['resources'])} hypertension condition")

    print("\n✅ TEST PASSED")


# ============================================================================
# Test 7: Time Filter (since parameter)
# ============================================================================

@pytest.mark.asyncio
async def test_time_filter(redis_client, speed_runner, patient_view_def, sample_patients):
    """Test filtering resources by cache time"""
    print("\n" + "="*60)
    print("TEST 7: Time Filter (since parameter)")
    print("="*60)

    # Cache old patient
    await redis_client.set_fhir_resource(
        "Patient", sample_patients[0]["id"], sample_patients[0], ttl_hours=24
    )
    print("✓ Cached 'old' patient")

    # Wait 2 seconds
    await asyncio.sleep(2)

    # Mark cutoff time
    cutoff_time = datetime.utcnow()
    print(f"✓ Marked cutoff time: {cutoff_time.isoformat()}")

    # Cache new patients
    await redis_client.set_fhir_resource(
        "Patient", sample_patients[1]["id"], sample_patients[1], ttl_hours=24
    )
    await redis_client.set_fhir_resource(
        "Patient", sample_patients[2]["id"], sample_patients[2], ttl_hours=24
    )
    print("✓ Cached 2 'new' patients after cutoff")

    # Query with since filter (should only get new patients)
    result = await speed_runner.execute(
        view_definition=patient_view_def,
        since=cutoff_time,
        max_resources=100
    )

    # Should only find 2 new patients
    assert result["total_count"] == 2, f"❌ Expected 2 new patients, got {result['total_count']}"

    expected_new_ids = {"patient-002", "patient-003"}
    actual_ids = set(result["patient_ids"])
    assert actual_ids == expected_new_ids, f"❌ Wrong patient IDs returned: {actual_ids}"

    print(f"✓ Time filter working: found {result['total_count']} patients after cutoff")
    print(f"✓ Patient IDs: {result['patient_ids']}")

    print("\n✅ TEST PASSED")


# ============================================================================
# Test 8: Max Resources Limit
# ============================================================================

@pytest.mark.asyncio
async def test_max_resources_limit(redis_client, speed_runner, patient_view_def):
    """Test max_resources limit parameter"""
    print("\n" + "="*60)
    print("TEST 8: Max Resources Limit")
    print("="*60)

    # Cache 10 patients
    for i in range(10):
        patient = {
            "resourceType": "Patient",
            "id": f"patient-{i:03d}",
            "gender": "male" if i % 2 == 0 else "female",
            "birthDate": f"1980-01-{i+1:02d}"
        }
        await redis_client.set_fhir_resource(
            "Patient", patient["id"], patient, ttl_hours=24
        )

    print("✓ Cached 10 patients in Redis")

    # Query with limit of 5
    result = await speed_runner.execute(
        view_definition=patient_view_def,
        max_resources=5
    )

    # Should only get 5 resources
    assert len(result["resources"]) == 5, f"❌ Expected 5 resources, got {len(result['resources'])}"
    assert result["total_count"] == 5, f"❌ Expected 5 patient count, got {result['total_count']}"

    print(f"✓ Limit respected: returned {len(result['resources'])} of 10 patients")

    # Query with limit of 100 (should get all 10)
    result_all = await speed_runner.execute(
        view_definition=patient_view_def,
        max_resources=100
    )

    assert len(result_all["resources"]) == 10, f"❌ Expected 10 resources, got {len(result_all['resources'])}"

    print(f"✓ No artificial limit: returned all {len(result_all['resources'])} patients")

    print("\n✅ TEST PASSED")


# ============================================================================
# Test 9: Code Text Matching
# ============================================================================

@pytest.mark.asyncio
async def test_code_text_matching(redis_client, speed_runner, condition_view_def):
    """Test code filtering with text search"""
    print("\n" + "="*60)
    print("TEST 9: Code Text Matching")
    print("="*60)

    # Cache conditions with different code formats
    conditions = [
        {
            "resourceType": "Condition",
            "id": "cond-001",
            "subject": {"reference": "Patient/pat-001"},
            "code": {
                "text": "Type 2 Diabetes Mellitus"
            }
        },
        {
            "resourceType": "Condition",
            "id": "cond-002",
            "subject": {"reference": "Patient/pat-002"},
            "code": {
                "coding": [{"code": "E11.9", "display": "Type 2 diabetes"}],
                "text": "Diabetes"
            }
        },
        {
            "resourceType": "Condition",
            "id": "cond-003",
            "subject": {"reference": "Patient/pat-003"},
            "code": {
                "text": "Hypertension"
            }
        }
    ]

    for condition in conditions:
        await redis_client.set_fhir_resource(
            "Condition", condition["id"], condition, ttl_hours=24
        )

    print("✓ Cached 3 conditions with various code formats")

    # Search for "diabetes" in text
    result = await speed_runner.execute(
        view_definition=condition_view_def,
        search_params={"code": "diabetes"},
        max_resources=100
    )

    # Should find 2 conditions with "diabetes" in text
    assert len(result["resources"]) == 2, f"❌ Expected 2 diabetes conditions, got {len(result['resources'])}"

    # Verify they're the right ones
    returned_ids = {r["id"] for r in result["resources"]}
    expected_ids = {"cond-001", "cond-002"}
    assert returned_ids == expected_ids, f"❌ Wrong conditions returned: {returned_ids}"

    print(f"✓ Text search found {len(result['resources'])} conditions with 'diabetes'")

    # Search for specific code
    result_code = await speed_runner.execute(
        view_definition=condition_view_def,
        search_params={"code": "E11.9"},
        max_resources=100
    )

    assert len(result_code["resources"]) == 1, f"❌ Expected 1 condition with E11.9 code"
    assert result_code["resources"][0]["id"] == "cond-002", "❌ Wrong condition returned"

    print(f"✓ Code search found {len(result_code['resources'])} condition with 'E11.9'")

    print("\n✅ TEST PASSED")


# ============================================================================
# Test 10: Multiple Resource Types Independence
# ============================================================================

@pytest.mark.asyncio
async def test_multiple_resource_types(redis_client, speed_runner, patient_view_def, condition_view_def, sample_patients, sample_conditions):
    """Test that different resource types are queried independently"""
    print("\n" + "="*60)
    print("TEST 10: Multiple Resource Types Independence")
    print("="*60)

    # Cache both patients and conditions
    for patient in sample_patients:
        await redis_client.set_fhir_resource(
            "Patient", patient["id"], patient, ttl_hours=24
        )

    for condition in sample_conditions:
        await redis_client.set_fhir_resource(
            "Condition", condition["id"], condition, ttl_hours=24
        )

    print(f"✓ Cached {len(sample_patients)} patients and {len(sample_conditions)} conditions")

    # Query patients
    patient_result = await speed_runner.execute(
        view_definition=patient_view_def,
        max_resources=100
    )

    # Query conditions
    condition_result = await speed_runner.execute(
        view_definition=condition_view_def,
        max_resources=100
    )

    # Verify patients only has patients
    assert patient_result["total_count"] == 3, f"❌ Expected 3 patients"
    for resource in patient_result["resources"]:
        assert resource["resourceType"] == "Patient", f"❌ Found non-Patient in patient query"

    # Verify conditions only has conditions
    assert condition_result["total_count"] == 2, f"❌ Expected 2 unique patients from conditions"
    assert len(condition_result["resources"]) == 3, f"❌ Expected 3 condition resources"
    for resource in condition_result["resources"]:
        assert resource["resourceType"] == "Condition", f"❌ Found non-Condition in condition query"

    print(f"✓ Patient query returned {patient_result['total_count']} patients")
    print(f"✓ Condition query returned {len(condition_result['resources'])} conditions")
    print("✓ Resource types properly isolated")

    print("\n✅ TEST PASSED")


# ============================================================================
# Run all tests
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
