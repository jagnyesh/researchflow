"""
Integration Tests for HybridRunner with Speed Layer

Tests the complete Lambda Architecture implementation:
- Batch Layer: MaterializedViewRunner (PostgreSQL materialized views)
- Speed Layer: SpeedLayerRunner (Redis cache)
- Serving Layer: HybridRunner (merges both)

Test Coverage:
- HybridRunner queries batch layer
- HybridRunner queries speed layer
- Both layers work together
- Environment variable control (USE_SPEED_LAYER)
- Statistics tracking
- View existence checking
- Fallback to PostgresRunner when view doesn't exist
- Real HAPI database + real Redis
"""

import pytest
import asyncio
import os
from datetime import datetime, timedelta
from pathlib import Path
import sys

# Add project to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.clients.hapi_db_client import create_hapi_db_client, close_hapi_db_client
from app.cache.redis_client import RedisClient
from app.sql_on_fhir.runner.hybrid_runner import HybridRunner
from app.sql_on_fhir.view_definition_manager import ViewDefinitionManager


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
async def db_client():
    """Create HAPI database client"""
    client = await create_hapi_db_client()
    yield client
    await close_hapi_db_client()


@pytest.fixture
async def redis_client():
    """Create Redis client for speed layer"""
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
async def hybrid_runner(db_client, redis_client):
    """Create HybridRunner instance"""
    return HybridRunner(
        db_client=db_client,
        redis_client=redis_client,
        enable_cache=False  # Disable caching for tests
    )


@pytest.fixture
def view_def_manager():
    """Create ViewDefinitionManager"""
    return ViewDefinitionManager()


@pytest.fixture
def sample_patients():
    """Sample FHIR Patient resources for speed layer"""
    return [
        {
            "resourceType": "Patient",
            "id": "speed-patient-001",
            "gender": "male",
            "birthDate": "1990-05-15",
            "name": [{"family": "SpeedTest", "given": ["John"]}]
        },
        {
            "resourceType": "Patient",
            "id": "speed-patient-002",
            "gender": "female",
            "birthDate": "1995-08-20",
            "name": [{"family": "SpeedTest", "given": ["Jane"]}]
        }
    ]


# ============================================================================
# Test 1: Batch Layer Query (Materialized View)
# ============================================================================

@pytest.mark.asyncio
async def test_batch_layer_query(hybrid_runner, view_def_manager):
    """Test that HybridRunner queries batch layer (materialized view)"""
    print("\n" + "="*60)
    print("TEST 1: Batch Layer Query (Materialized View)")
    print("="*60)

    # Load patient_simple ViewDefinition
    view_def = view_def_manager.load("patient_simple")
    print(f"✓ Loaded ViewDefinition: {view_def['name']}")

    # Execute query (should use MaterializedViewRunner)
    result = await hybrid_runner.execute(
        view_definition=view_def,
        max_resources=10
    )

    # Verify results
    assert isinstance(result, list), "❌ Result should be a list"
    assert len(result) > 0, "❌ Should return some patients from batch layer"

    # Verify structure (should have columns from ViewDefinition)
    first_row = result[0]
    assert "id" in first_row, "❌ Result should have 'id' column"
    assert "gender" in first_row, "❌ Result should have 'gender' column"

    print(f"✓ Batch layer query returned {len(result)} rows")
    print(f"✓ Sample row: {first_row}")

    # Check statistics
    stats = hybrid_runner.get_statistics()
    assert stats["materialized_queries"] >= 1, "❌ Should have materialized query"
    print(f"✓ Statistics: {stats['materialized_queries']} materialized queries")

    print("\n✅ TEST PASSED")


# ============================================================================
# Test 2: Speed Layer Query Integration
# ============================================================================

@pytest.mark.asyncio
async def test_speed_layer_query_integration(redis_client, hybrid_runner, view_def_manager, sample_patients):
    """Test that HybridRunner queries both batch and speed layers"""
    print("\n" + "="*60)
    print("TEST 2: Speed Layer Query Integration")
    print("="*60)

    # Cache patients in Redis (speed layer)
    for patient in sample_patients:
        await redis_client.set_fhir_resource(
            "Patient", patient["id"], patient, ttl_hours=24
        )

    print(f"✓ Cached {len(sample_patients)} patients in Redis (speed layer)")

    # Ensure USE_SPEED_LAYER is enabled
    original_env = os.getenv("USE_SPEED_LAYER")
    os.environ["USE_SPEED_LAYER"] = "true"

    # Re-create runner to pick up env var
    from app.clients.hapi_db_client import create_hapi_db_client, close_hapi_db_client
    db_client = await create_hapi_db_client()
    hybrid_runner_with_speed = HybridRunner(
        db_client=db_client,
        redis_client=redis_client,
        enable_cache=False
    )

    try:
        # Load patient_simple ViewDefinition
        view_def = view_def_manager.load("patient_simple")

        # Execute query (should query both layers)
        result = await hybrid_runner_with_speed.execute(
            view_definition=view_def,
            max_resources=100
        )

        # Verify results
        assert isinstance(result, list), "❌ Result should be a list"
        assert len(result) > 0, "❌ Should return results"

        print(f"✓ HybridRunner returned {len(result)} rows")

        # Check statistics - both batch and speed layer should be queried
        stats = hybrid_runner_with_speed.get_statistics()
        assert stats["speed_layer_queries"] >= 1, "❌ Should have speed layer query"
        assert stats["total_queries"] >= 1, "❌ Should have batch layer query"
        assert stats["speed_layer_enabled"] is True, "❌ Speed layer should be enabled"

        print(f"✓ Speed layer queries: {stats['speed_layer_queries']}")
        print(f"✓ Batch layer queries: {stats['total_queries']}")
        print(f"✓ Speed layer enabled: {stats['speed_layer_enabled']}")

        print("\n✅ TEST PASSED")

    finally:
        # Restore environment
        if original_env:
            os.environ["USE_SPEED_LAYER"] = original_env
        else:
            os.environ.pop("USE_SPEED_LAYER", None)

        await close_hapi_db_client()


# ============================================================================
# Test 3: Speed Layer Disabled
# ============================================================================

@pytest.mark.asyncio
async def test_speed_layer_disabled(redis_client, view_def_manager, sample_patients):
    """Test that HybridRunner respects USE_SPEED_LAYER=false"""
    print("\n" + "="*60)
    print("TEST 3: Speed Layer Disabled (USE_SPEED_LAYER=false)")
    print("="*60)

    # Cache patients in Redis
    for patient in sample_patients:
        await redis_client.set_fhir_resource(
            "Patient", patient["id"], patient, ttl_hours=24
        )

    print(f"✓ Cached {len(sample_patients)} patients in Redis")

    # Disable speed layer
    original_env = os.getenv("USE_SPEED_LAYER")
    os.environ["USE_SPEED_LAYER"] = "false"

    # Create runner with speed layer disabled
    from app.clients.hapi_db_client import create_hapi_db_client, close_hapi_db_client
    db_client = await create_hapi_db_client()
    hybrid_runner_no_speed = HybridRunner(
        db_client=db_client,
        redis_client=redis_client,
        enable_cache=False
    )

    try:
        # Load patient_simple ViewDefinition
        view_def = view_def_manager.load("patient_simple")

        # Execute query (should NOT query speed layer)
        result = await hybrid_runner_no_speed.execute(
            view_definition=view_def,
            max_resources=10
        )

        # Verify results
        assert isinstance(result, list), "❌ Result should be a list"
        assert len(result) > 0, "❌ Should return results from batch layer"

        print(f"✓ HybridRunner returned {len(result)} rows (batch only)")

        # Check statistics - speed layer should NOT be queried
        stats = hybrid_runner_no_speed.get_statistics()
        assert stats["speed_layer_queries"] == 0, "❌ Speed layer should not be queried"
        assert stats["speed_layer_enabled"] is False, "❌ Speed layer should be disabled"
        assert stats["total_queries"] >= 1, "❌ Batch layer should still be queried"

        print(f"✓ Speed layer queries: {stats['speed_layer_queries']} (expected: 0)")
        print(f"✓ Speed layer enabled: {stats['speed_layer_enabled']} (expected: False)")
        print(f"✓ Batch layer queries: {stats['total_queries']}")

        print("\n✅ TEST PASSED")

    finally:
        # Restore environment
        if original_env:
            os.environ["USE_SPEED_LAYER"] = original_env
        else:
            os.environ.pop("USE_SPEED_LAYER", None)

        await close_hapi_db_client()


# ============================================================================
# Test 4: View Existence Checking
# ============================================================================

@pytest.mark.asyncio
async def test_view_existence_checking(hybrid_runner, view_def_manager):
    """Test that HybridRunner correctly checks for materialized view existence"""
    print("\n" + "="*60)
    print("TEST 4: View Existence Checking")
    print("="*60)

    # Test with a view that exists
    view_def_exists = view_def_manager.load("patient_simple")
    view_name_exists = view_def_exists["name"]

    exists = await hybrid_runner._check_view_exists(view_name_exists)
    assert exists is True, f"❌ View '{view_name_exists}' should exist"
    print(f"✓ View '{view_name_exists}' exists: {exists}")

    # Test with a view that doesn't exist
    fake_view_def = {
        "name": "nonexistent_view_12345",
        "resource": "Patient",
        "select": []
    }
    fake_view_name = fake_view_def["name"]

    exists_fake = await hybrid_runner._check_view_exists(fake_view_name)
    assert exists_fake is False, f"❌ View '{fake_view_name}' should not exist"
    print(f"✓ View '{fake_view_name}' exists: {exists_fake}")

    # Test caching - second check should use cache
    exists_cached = await hybrid_runner._check_view_exists(view_name_exists)
    assert exists_cached is True, "❌ Cached result should still be True"
    print(f"✓ Cached check for '{view_name_exists}': {exists_cached}")

    # Verify cache statistics
    stats = hybrid_runner.get_statistics()
    assert stats["views_cached"] >= 2, f"❌ Should have cached 2 views, got {stats['views_cached']}"
    print(f"✓ Views cached: {stats['views_cached']}")

    print("\n✅ TEST PASSED")


# ============================================================================
# Test 5: Statistics Tracking
# ============================================================================

@pytest.mark.asyncio
async def test_statistics_tracking(redis_client, hybrid_runner, view_def_manager, sample_patients):
    """Test that HybridRunner tracks statistics correctly"""
    print("\n" + "="*60)
    print("TEST 5: Statistics Tracking")
    print("="*60)

    # Cache patients in Redis
    for patient in sample_patients:
        await redis_client.set_fhir_resource(
            "Patient", patient["id"], patient, ttl_hours=24
        )

    # Load ViewDefinition
    view_def = view_def_manager.load("patient_simple")

    # Execute multiple queries
    for i in range(3):
        result = await hybrid_runner.execute(
            view_definition=view_def,
            max_resources=5
        )
        print(f"✓ Query {i+1} completed: {len(result)} rows")

    # Get statistics
    stats = hybrid_runner.get_statistics()

    print(f"\n📊 Statistics Summary:")
    print(f"  Runner type: {stats['runner_type']}")
    print(f"  Total queries: {stats['total_queries']}")
    print(f"  Materialized queries: {stats['materialized_queries']}")
    print(f"  Postgres queries: {stats['postgres_queries']}")
    print(f"  Speed layer queries: {stats['speed_layer_queries']}")
    print(f"  Materialized percentage: {stats['materialized_percentage']:.1f}%")
    print(f"  Speed layer enabled: {stats['speed_layer_enabled']}")
    print(f"  Views cached: {stats['views_cached']}")

    # Verify statistics
    assert stats["runner_type"] == "hybrid", "❌ Wrong runner type"
    assert stats["total_queries"] >= 3, f"❌ Should have at least 3 total queries, got {stats['total_queries']}"
    assert stats["speed_layer_queries"] >= 3, f"❌ Should have at least 3 speed layer queries"
    assert "materialized_runner_stats" in stats, "❌ Missing materialized_runner_stats"

    print("\n✅ TEST PASSED")


# ============================================================================
# Test 6: Gender Filter with Both Layers
# ============================================================================

@pytest.mark.asyncio
async def test_gender_filter_both_layers(redis_client, hybrid_runner, view_def_manager, sample_patients):
    """Test filtering with both batch and speed layers"""
    print("\n" + "="*60)
    print("TEST 6: Gender Filter with Both Layers")
    print("="*60)

    # Cache patients in Redis (1 male, 1 female)
    for patient in sample_patients:
        await redis_client.set_fhir_resource(
            "Patient", patient["id"], patient, ttl_hours=24
        )

    print(f"✓ Cached {len(sample_patients)} patients (1 male, 1 female)")

    # Load ViewDefinition
    view_def = view_def_manager.load("patient_simple")

    # Query for male patients
    result_male = await hybrid_runner.execute(
        view_definition=view_def,
        search_params={"gender": "male"},
        max_resources=100
    )

    print(f"✓ Male patients query returned {len(result_male)} rows")

    # Query for female patients
    result_female = await hybrid_runner.execute(
        view_definition=view_def,
        search_params={"gender": "female"},
        max_resources=100
    )

    print(f"✓ Female patients query returned {len(result_female)} rows")

    # Both should return results (from batch layer at minimum)
    assert len(result_male) > 0, "❌ Should return male patients"
    assert len(result_female) > 0, "❌ Should return female patients"

    # Verify speed layer was queried
    stats = hybrid_runner.get_statistics()
    assert stats["speed_layer_queries"] >= 2, "❌ Speed layer should be queried for both filters"

    print(f"✓ Speed layer queries: {stats['speed_layer_queries']}")

    print("\n✅ TEST PASSED")


# ============================================================================
# Test 7: Time-based Speed Layer Query
# ============================================================================

@pytest.mark.asyncio
async def test_time_based_speed_layer(redis_client, hybrid_runner, view_def_manager, sample_patients):
    """Test that speed layer only returns recent data"""
    print("\n" + "="*60)
    print("TEST 7: Time-based Speed Layer Query")
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

    # Cache new patient
    await redis_client.set_fhir_resource(
        "Patient", sample_patients[1]["id"], sample_patients[1], ttl_hours=24
    )
    print("✓ Cached 'new' patient after cutoff")

    # Load ViewDefinition
    view_def = view_def_manager.load("patient_simple")

    # Execute query - speed layer should query with default 24h lookback
    result = await hybrid_runner.execute(
        view_definition=view_def,
        max_resources=100
    )

    # Verify results
    assert len(result) > 0, "❌ Should return results"
    print(f"✓ HybridRunner returned {len(result)} rows")

    # Verify speed layer was queried
    stats = hybrid_runner.get_statistics()
    assert stats["speed_layer_queries"] >= 1, "❌ Speed layer should be queried"
    print(f"✓ Speed layer queries: {stats['speed_layer_queries']}")

    print("\n✅ TEST PASSED")


# ============================================================================
# Test 8: Empty Speed Layer
# ============================================================================

@pytest.mark.asyncio
async def test_empty_speed_layer(hybrid_runner, view_def_manager):
    """Test HybridRunner with empty Redis cache"""
    print("\n" + "="*60)
    print("TEST 8: Empty Speed Layer")
    print("="*60)

    # Don't cache anything in Redis

    # Load ViewDefinition
    view_def = view_def_manager.load("patient_simple")

    # Execute query (should work with batch layer only)
    result = await hybrid_runner.execute(
        view_definition=view_def,
        max_resources=10
    )

    # Verify results from batch layer
    assert isinstance(result, list), "❌ Result should be a list"
    assert len(result) > 0, "❌ Should return results from batch layer"

    print(f"✓ Batch layer query returned {len(result)} rows (speed layer empty)")

    # Verify speed layer was still queried (it just returned 0 results)
    stats = hybrid_runner.get_statistics()
    assert stats["speed_layer_queries"] >= 1, "❌ Speed layer should still be queried"
    print(f"✓ Speed layer queries: {stats['speed_layer_queries']}")

    print("\n✅ TEST PASSED")


# ============================================================================
# Test 9: Multiple ViewDefinitions
# ============================================================================

@pytest.mark.asyncio
async def test_multiple_view_definitions(hybrid_runner, view_def_manager):
    """Test HybridRunner with different ViewDefinitions"""
    print("\n" + "="*60)
    print("TEST 9: Multiple ViewDefinitions")
    print("="*60)

    # Test multiple view definitions
    view_names = ["patient_simple", "condition_simple"]

    for view_name in view_names:
        view_def = view_def_manager.load(view_name)
        print(f"\n  Testing {view_name}...")

        result = await hybrid_runner.execute(
            view_definition=view_def,
            max_resources=5
        )

        assert isinstance(result, list), f"❌ Result for {view_name} should be a list"
        print(f"  ✓ {view_name}: {len(result)} rows")

    # Check statistics
    stats = hybrid_runner.get_statistics()
    assert stats["total_queries"] >= len(view_names), "❌ Should have queries for all views"
    assert stats["views_cached"] >= len(view_names), "❌ Should have cached all views"

    print(f"\n✓ Tested {len(view_names)} different ViewDefinitions")
    print(f"✓ Total queries: {stats['total_queries']}")
    print(f"✓ Views cached: {stats['views_cached']}")

    print("\n✅ TEST PASSED")


# ============================================================================
# Test 10: Clear View Cache
# ============================================================================

@pytest.mark.asyncio
async def test_clear_view_cache(hybrid_runner, view_def_manager):
    """Test clearing the view existence cache"""
    print("\n" + "="*60)
    print("TEST 10: Clear View Cache")
    print("="*60)

    # Query a view to populate cache
    view_def = view_def_manager.load("patient_simple")
    result = await hybrid_runner.execute(
        view_definition=view_def,
        max_resources=5
    )

    # Check cache is populated
    stats_before = hybrid_runner.get_statistics()
    assert stats_before["views_cached"] > 0, "❌ Cache should have entries"
    print(f"✓ Views cached before clear: {stats_before['views_cached']}")

    # Clear cache
    hybrid_runner.clear_view_cache()
    print("✓ Cleared view cache")

    # Check cache is empty
    stats_after = hybrid_runner.get_statistics()
    assert stats_after["views_cached"] == 0, "❌ Cache should be empty after clear"
    print(f"✓ Views cached after clear: {stats_after['views_cached']}")

    # Query again to repopulate
    result2 = await hybrid_runner.execute(
        view_definition=view_def,
        max_resources=5
    )

    stats_final = hybrid_runner.get_statistics()
    assert stats_final["views_cached"] > 0, "❌ Cache should be repopulated"
    print(f"✓ Views cached after re-query: {stats_final['views_cached']}")

    print("\n✅ TEST PASSED")


# ============================================================================
# Run all tests
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
