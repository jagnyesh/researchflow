"""
Unit Tests for RedisClient (Speed Layer)

Tests the Redis client CRUD operations for FHIR resource caching.
Uses local Redis instance (localhost:6379).

Test Coverage:
- Connection/disconnection
- Resource caching with TTL
- Resource retrieval
- Resource scanning with filters
- TTL expiration
- Error handling
"""

import pytest
import asyncio
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
import sys

# Add project to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.cache.redis_client import RedisClient


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
def sample_patient():
    """Sample FHIR Patient resource"""
    return {
        "resourceType": "Patient",
        "id": "test-patient-001",
        "gender": "male",
        "birthDate": "1980-01-15",
        "name": [{
            "family": "Test",
            "given": ["John"]
        }]
    }


@pytest.fixture
def sample_condition():
    """Sample FHIR Condition resource"""
    return {
        "resourceType": "Condition",
        "id": "test-condition-001",
        "subject": {
            "reference": "Patient/test-patient-001"
        },
        "code": {
            "coding": [{
                "system": "http://snomed.info/sct",
                "code": "73211009",
                "display": "Diabetes mellitus"
            }],
            "text": "Diabetes mellitus"
        },
        "onsetDateTime": "2023-01-15"
    }


# ============================================================================
# Test 1: Connection Management
# ============================================================================

@pytest.mark.asyncio
async def test_connect_disconnect():
    """Test Redis connection and disconnection"""
    print("\n" + "="*60)
    print("TEST 1: Connection Management")
    print("="*60)

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/1")
    client = RedisClient(redis_url=redis_url)

    # Test connection
    connection = await client.connect()
    assert connection is not None, "❌ Failed to connect to Redis"
    print("✓ Successfully connected to Redis")

    # Test disconnect
    await client.disconnect()
    assert client._client is None, "❌ Client not properly disconnected"
    print("✓ Successfully disconnected from Redis")

    print("\n✅ TEST PASSED")


# ============================================================================
# Test 2: Set and Get FHIR Resource
# ============================================================================

@pytest.mark.asyncio
async def test_set_and_get_fhir_resource(redis_client, sample_patient):
    """Test setting and retrieving a FHIR resource"""
    print("\n" + "="*60)
    print("TEST 2: Set and Get FHIR Resource")
    print("="*60)

    # Set resource
    success = await redis_client.set_fhir_resource(
        resource_type="Patient",
        resource_id="test-patient-001",
        resource_data=sample_patient,
        ttl_hours=1
    )
    assert success, "❌ Failed to set FHIR resource"
    print("✓ Successfully cached Patient resource")

    # Get resource
    retrieved = await redis_client.get_fhir_resource(
        resource_type="Patient",
        resource_id="test-patient-001"
    )
    assert retrieved is not None, "❌ Failed to retrieve FHIR resource"
    assert retrieved["id"] == "test-patient-001", "❌ Retrieved wrong resource"
    assert retrieved["gender"] == "male", "❌ Resource data corrupted"
    print(f"✓ Successfully retrieved Patient: {retrieved['id']}")

    print("\n✅ TEST PASSED")


# ============================================================================
# Test 3: Scan Recent Resources
# ============================================================================

@pytest.mark.asyncio
async def test_scan_recent_resources(redis_client, sample_patient, sample_condition):
    """Test scanning for recent resources of a specific type"""
    print("\n" + "="*60)
    print("TEST 3: Scan Recent Resources")
    print("="*60)

    # Cache multiple resources
    await redis_client.set_fhir_resource("Patient", "patient-001", sample_patient)
    await redis_client.set_fhir_resource("Patient", "patient-002", {**sample_patient, "id": "patient-002"})
    await redis_client.set_fhir_resource("Condition", "condition-001", sample_condition)

    print("✓ Cached 2 Patients and 1 Condition")

    # Scan for Patient resources
    patients = await redis_client.scan_recent_resources(resource_type="Patient")
    assert len(patients) == 2, f"❌ Expected 2 patients, found {len(patients)}"
    print(f"✓ Found {len(patients)} Patient resources")

    # Scan for Condition resources
    conditions = await redis_client.scan_recent_resources(resource_type="Condition")
    assert len(conditions) == 1, f"❌ Expected 1 condition, found {len(conditions)}"
    print(f"✓ Found {len(conditions)} Condition resources")

    print("\n✅ TEST PASSED")


# ============================================================================
# Test 4: Scan with Time Filter
# ============================================================================

@pytest.mark.asyncio
async def test_scan_with_time_filter(redis_client, sample_patient):
    """Test scanning resources with 'since' time filter"""
    print("\n" + "="*60)
    print("TEST 4: Scan with Time Filter")
    print("="*60)

    # Cache a resource
    await redis_client.set_fhir_resource("Patient", "old-patient", sample_patient)

    # Wait 2 seconds
    await asyncio.sleep(2)

    # Mark time
    cutoff_time = datetime.utcnow()

    # Cache another resource
    await redis_client.set_fhir_resource("Patient", "new-patient", {**sample_patient, "id": "new-patient"})

    print("✓ Cached resources before and after cutoff time")

    # Scan for resources since cutoff (should only get new-patient)
    recent = await redis_client.scan_recent_resources(
        resource_type="Patient",
        since=cutoff_time
    )

    # Should only find the new patient
    assert len(recent) == 1, f"❌ Expected 1 recent patient, found {len(recent)}"
    assert recent[0]["id"] == "new-patient", "❌ Wrong patient returned"
    print(f"✓ Time filter working: found {len(recent)} resource(s) after cutoff")

    print("\n✅ TEST PASSED")


# ============================================================================
# Test 5: TTL Expiration
# ============================================================================

@pytest.mark.asyncio
async def test_ttl_expiration(redis_client, sample_patient):
    """Test that resources expire after TTL"""
    print("\n" + "="*60)
    print("TEST 5: TTL Expiration")
    print("="*60)

    # Set resource with very short TTL (2 seconds)
    await redis_client.set_fhir_resource(
        resource_type="Patient",
        resource_id="expiring-patient",
        resource_data=sample_patient,
        ttl_hours=2/3600  # 2 seconds
    )
    print("✓ Cached resource with 2-second TTL")

    # Verify it exists
    retrieved = await redis_client.get_fhir_resource("Patient", "expiring-patient")
    assert retrieved is not None, "❌ Resource should exist initially"
    print("✓ Resource exists immediately after caching")

    # Wait for expiration
    print("  Waiting 3 seconds for TTL expiration...")
    await asyncio.sleep(3)

    # Verify it's gone
    expired = await redis_client.get_fhir_resource("Patient", "expiring-patient")
    assert expired is None, "❌ Resource should have expired"
    print("✓ Resource properly expired after TTL")

    print("\n✅ TEST PASSED")


# ============================================================================
# Test 6: Delete Resource
# ============================================================================

@pytest.mark.asyncio
async def test_delete_resource(redis_client, sample_patient):
    """Test deleting a cached resource"""
    print("\n" + "="*60)
    print("TEST 6: Delete Resource")
    print("="*60)

    # Cache resource
    await redis_client.set_fhir_resource("Patient", "deleteme", sample_patient)
    print("✓ Cached resource")

    # Verify it exists
    retrieved = await redis_client.get_fhir_resource("Patient", "deleteme")
    assert retrieved is not None, "❌ Resource should exist"

    # Delete it
    deleted = await redis_client.delete_resource("Patient", "deleteme")
    assert deleted, "❌ Delete operation failed"
    print("✓ Successfully deleted resource")

    # Verify it's gone
    gone = await redis_client.get_fhir_resource("Patient", "deleteme")
    assert gone is None, "❌ Resource should be deleted"
    print("✓ Resource properly removed from cache")

    print("\n✅ TEST PASSED")


# ============================================================================
# Test 7: Multiple Resource Types
# ============================================================================

@pytest.mark.asyncio
async def test_multiple_resource_types(redis_client, sample_patient, sample_condition):
    """Test caching different FHIR resource types"""
    print("\n" + "="*60)
    print("TEST 7: Multiple Resource Types")
    print("="*60)

    # Cache different resource types
    resources = {
        "Patient": sample_patient,
        "Condition": sample_condition,
        "Observation": {
            "resourceType": "Observation",
            "id": "obs-001",
            "code": {"text": "HbA1c"},
            "valueQuantity": {"value": 6.5}
        }
    }

    for resource_type, resource in resources.items():
        await redis_client.set_fhir_resource(
            resource_type, resource["id"], resource
        )

    print(f"✓ Cached {len(resources)} different resource types")

    # Verify each type can be scanned independently
    for resource_type in resources.keys():
        found = await redis_client.scan_recent_resources(resource_type)
        assert len(found) == 1, f"❌ Expected 1 {resource_type}, found {len(found)}"
        print(f"✓ Found {len(found)} {resource_type} resource(s)")

    print("\n✅ TEST PASSED")


# ============================================================================
# Test 8: Error Handling - Non-existent Resource
# ============================================================================

@pytest.mark.asyncio
async def test_get_nonexistent_resource(redis_client):
    """Test retrieving a resource that doesn't exist"""
    print("\n" + "="*60)
    print("TEST 8: Get Non-existent Resource")
    print("="*60)

    # Try to get resource that doesn't exist
    result = await redis_client.get_fhir_resource("Patient", "does-not-exist")
    assert result is None, "❌ Should return None for non-existent resource"
    print("✓ Correctly returned None for non-existent resource")

    print("\n✅ TEST PASSED")


# ============================================================================
# Test 9: Flush All (Cleanup)
# ============================================================================

@pytest.mark.asyncio
async def test_flush_all(redis_client, sample_patient):
    """Test flushing all cached data"""
    print("\n" + "="*60)
    print("TEST 9: Flush All")
    print("="*60)

    # Cache multiple resources
    for i in range(5):
        await redis_client.set_fhir_resource(
            "Patient",
            f"patient-{i}",
            {**sample_patient, "id": f"patient-{i}"}
        )

    print("✓ Cached 5 Patient resources")

    # Verify they exist
    patients = await redis_client.scan_recent_resources("Patient")
    assert len(patients) == 5, f"❌ Expected 5 patients, found {len(patients)}"

    # Flush all
    success = await redis_client.flush_all()
    assert success, "❌ Flush operation failed"
    print("✓ Flushed all cached data")

    # Verify all gone
    patients_after = await redis_client.scan_recent_resources("Patient")
    assert len(patients_after) == 0, f"❌ Expected 0 patients after flush, found {len(patients_after)}"
    print("✓ All resources successfully removed")

    print("\n✅ TEST PASSED")


# ============================================================================
# Run all tests
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
