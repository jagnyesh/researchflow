# Sprint 5.5: Lambda Speed Layer (Redis) - TECHNICAL PLAN

**Sprint:** 5.5
**Duration:** 2 weeks
**Priority:** High (Critical architectural gap)
**Status:** ✅ Complete (Week 1 + Week 2 + Testing)
**Created:** 2025-10-28
**Completed:** 2025-10-28

---

## Executive Summary

**Goal**: Complete the Lambda architecture by implementing a Redis-based speed layer that captures recent FHIR updates, enabling near real-time queries by merging batch (materialized views) + speed (Redis cache) data sources.

**Current Situation**:
- ✅ **Batch Layer**: Materialized views implemented (Sprint 4.5) - 10-100x faster
- ❌ **Speed Layer**: Not implemented - queries don't reflect recent FHIR updates
- 🟡 **Serving Layer**: HybridRunner exists but only queries batch layer

**Target Outcome**:
- ✅ Complete Lambda architecture (Batch + Speed + Serving)
- ✅ Near real-time queries (batch layer + recent 24-hour updates)
- ✅ Auto-refresh pipeline for materialized views (nightly)
- ✅ <10ms Redis query latency

---

## Background

### Problem Statement

**Current Limitation**: Materialized views are refreshed manually/nightly, so queries don't include:
- New patients added today
- Condition diagnoses from the last 24 hours
- Recent observation measurements

**Business Impact**:
- Feasibility queries may miss recently eligible patients
- Data extraction includes stale data for analytics
- No visibility into recent FHIR changes

**User Experience Impact**:
- Researchers see "yesterday's data" even though new records exist
- Cohort size estimates may be inaccurate for time-sensitive studies

### Proposed Solution: Lambda Architecture Speed Layer

```
┌───────────────────────────────────────────────┐
│          FHIR Data (HAPI Server)              │
│       105 patients, 423 conditions            │
└──────────────┬────────────────────────────────┘
               │
         ┌─────┴─────┐
         │           │
         ▼           ▼
   Batch Layer   Speed Layer
   (Materialized  (Redis Cache)
    Views)        Last 24 hours
    Nightly       Real-time writes
    refresh       TTL: 24h
         │           │
         └─────┬─────┘
               ▼
       Serving Layer
       (HybridRunner)
       Merges both sources
       Returns complete results
```

### Key Design Decisions

1. **Why Redis?**
   - Sub-millisecond latency (<1ms typical)
   - TTL support (auto-expire old data)
   - Pub/Sub for FHIR subscription notifications
   - Docker Compose integration (easy local dev)

2. **Why 24-hour TTL?**
   - Materialized views refresh nightly
   - Speed layer only needs to hold "today's" data
   - After nightly refresh, data moves to batch layer

3. **Why Mock FHIR Subscriptions?**
   - Real FHIR subscriptions require HAPI configuration
   - Mock allows Sprint 5.5 completion without HAPI changes
   - Real subscriptions can be added later (Sprint 6+)

---

## Architecture

### Component Diagram

```
┌─────────────────────────────────────────────────────────┐
│                  FHIR HAPI Server                       │
│              (PostgreSQL database)                      │
└──────────────────────┬──────────────────────────────────┘
                       │
                       │ Simulated
                       │ subscription
                       ▼
        ┌──────────────────────────────┐
        │  FHIR Subscription Service   │
        │    (Mock Implementation)     │
        │                              │
        │  - Poll FHIR every 5 min     │
        │  - Detect new/updated resources │
        │  - Write to Redis with TS    │
        └──────────┬───────────────────┘
                   │
                   ▼
        ┌──────────────────────────────┐
        │      Redis Cache             │
        │   (Speed Layer Storage)      │
        │                              │
        │  Keys: fhir:patient:{id}     │
        │        fhir:condition:{id}   │
        │  TTL: 24 hours               │
        │  Format: JSON                │
        └──────────┬───────────────────┘
                   │
                   ▼
        ┌──────────────────────────────┐
        │   SpeedLayerRunner           │
        │  (app/sql_on_fhir/runner/)   │
        │                              │
        │  - Query Redis for recent data │
        │  - Parse cached JSON         │
        │  - Return structured results │
        └──────────┬───────────────────┘
                   │
                   ▼
        ┌──────────────────────────────┐
        │      HybridRunner            │
        │   (Updated for merge)        │
        │                              │
        │  1. Query batch layer        │
        │  2. Query speed layer        │
        │  3. Merge + deduplicate      │
        │  4. Return complete results  │
        └──────────────────────────────┘
```

### Data Flow

**Scenario: Query for diabetes patients**

1. **HybridRunner receives query** (gender=male, condition=diabetes)

2. **Query Batch Layer** (materialized views):
   ```sql
   SELECT patient_id FROM sqlonfhir.patient_demographics WHERE gender='male'
   INTERSECT
   SELECT patient_id FROM sqlonfhir.condition_simple WHERE code_text ILIKE '%diabetes%'
   ```
   **Result**: 28 patients (as of last nightly refresh)

3. **Query Speed Layer** (Redis):
   ```python
   # Get patients added/updated in last 24 hours
   recent_patients = redis.scan(match="fhir:patient:*", ...)
   recent_conditions = redis.scan(match="fhir:condition:*", ...)

   # Filter by criteria
   new_matches = [p for p in recent_patients if p['gender'] == 'male']
   new_matches = [p for p in new_matches if has_diabetes_condition(p)]
   ```
   **Result**: 2 new patients (added today, not yet in batch layer)

4. **Merge Results**:
   ```python
   all_patients = set(batch_results) | set(speed_results)  # Union
   # Remove duplicates (patient may be in both if updated today)
   deduplicated = {p.patient_id: p for p in all_patients}.values()
   ```
   **Final Result**: 30 patients (28 from batch + 2 from speed)

---

## Implementation Plan

### Week 1: Redis Infrastructure & Speed Layer Runner

#### Day 1-2: Redis Setup

**Task 1.1: Add Redis to Docker Compose**

File: `config/docker-compose.yml`

```yaml
services:
  # ... existing services ...

  redis:
    image: redis:7-alpine
    container_name: researchflow-redis
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    command: redis-server --appendonly yes --maxmemory 256mb --maxmemory-policy allkeys-lru
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

volumes:
  # ... existing volumes ...
  redis_data:
```

**Task 1.2: Create Redis Client**

File: `app/cache/redis_client.py`

```python
"""Redis client for speed layer caching."""
import os
import json
from typing import Any, Dict, List, Optional
import redis.asyncio as redis
from datetime import datetime, timedelta


class RedisClient:
    """Async Redis client for FHIR speed layer."""

    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url or os.getenv(
            'REDIS_URL',
            'redis://localhost:6379/0'
        )
        self._client: Optional[redis.Redis] = None

    async def connect(self):
        """Establish Redis connection."""
        if not self._client:
            self._client = await redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_timeout=5
            )
        return self._client

    async def disconnect(self):
        """Close Redis connection."""
        if self._client:
            await self._client.close()
            self._client = None

    async def set_fhir_resource(
        self,
        resource_type: str,
        resource_id: str,
        resource_data: Dict[str, Any],
        ttl_hours: int = 24
    ) -> bool:
        """
        Cache a FHIR resource in Redis with TTL.

        Args:
            resource_type: FHIR resource type (Patient, Condition, etc.)
            resource_id: Resource ID
            resource_data: Full FHIR resource JSON
            ttl_hours: Time-to-live in hours (default: 24)

        Returns:
            True if successful
        """
        client = await self.connect()

        key = f"fhir:{resource_type.lower()}:{resource_id}"
        value = json.dumps({
            "resource": resource_data,
            "cached_at": datetime.utcnow().isoformat(),
            "resource_type": resource_type
        })

        ttl_seconds = ttl_hours * 3600

        return await client.setex(key, ttl_seconds, value)

    async def get_fhir_resource(
        self,
        resource_type: str,
        resource_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get a cached FHIR resource."""
        client = await self.connect()

        key = f"fhir:{resource_type.lower()}:{resource_id}"
        value = await client.get(key)

        if value:
            data = json.loads(value)
            return data["resource"]
        return None

    async def scan_recent_resources(
        self,
        resource_type: str,
        since: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """
        Scan Redis for recent resources of a given type.

        Args:
            resource_type: FHIR resource type
            since: Only return resources cached after this time

        Returns:
            List of resource dictionaries
        """
        client = await self.connect()

        pattern = f"fhir:{resource_type.lower()}:*"
        resources = []

        cursor = 0
        while True:
            cursor, keys = await client.scan(
                cursor=cursor,
                match=pattern,
                count=100
            )

            if keys:
                for key in keys:
                    value = await client.get(key)
                    if value:
                        data = json.loads(value)

                        # Filter by timestamp if requested
                        if since:
                            cached_at = datetime.fromisoformat(data["cached_at"])
                            if cached_at < since:
                                continue

                        resources.append(data["resource"])

            if cursor == 0:
                break

        return resources

    async def delete_resource(
        self,
        resource_type: str,
        resource_id: str
    ) -> bool:
        """Delete a cached resource."""
        client = await self.connect()
        key = f"fhir:{resource_type.lower()}:{resource_id}"
        return await client.delete(key) > 0

    async def flush_all(self) -> bool:
        """Flush all cached data (use with caution!)."""
        client = await self.connect()
        return await client.flushdb()
```

**Task 1.3: Create Cache Configuration**

File: `app/cache/cache_config.py`

```python
"""Cache configuration and policies."""
from dataclasses import dataclass


@dataclass
class CacheConfig:
    """Redis cache configuration."""

    # TTL (time-to-live) in hours
    default_ttl_hours: int = 24
    patient_ttl_hours: int = 24
    condition_ttl_hours: int = 24
    observation_ttl_hours: int = 12  # Observations change more frequently

    # Scan limits
    scan_batch_size: int = 100
    max_scan_results: int = 10000

    # Connection settings
    connection_timeout_seconds: int = 5
    max_connections: int = 50

    # Refresh settings
    refresh_interval_minutes: int = 5  # How often to poll FHIR for changes


# Global config instance
cache_config = CacheConfig()
```

#### Day 3-4: Speed Layer Runner

**Task 1.4: Create Speed Layer Runner**

File: `app/sql_on_fhir/runner/speed_layer_runner.py`

```python
"""Speed layer runner for querying Redis-cached FHIR data."""
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
import logging

from app.cache.redis_client import RedisClient
from app.sql_on_fhir.runner.base_runner import BaseRunner

logger = logging.getLogger(__name__)


class SpeedLayerRunner(BaseRunner):
    """
    Query recent FHIR data from Redis cache.

    This runner queries the speed layer (Redis) for FHIR resources
    added/updated in the last 24 hours that haven't been materialized yet.
    """

    def __init__(self, redis_client: RedisClient):
        self.redis_client = redis_client

    async def execute(
        self,
        view_definition: Dict[str, Any],
        search_params: Optional[Dict[str, str]] = None,
        max_resources: int = 1000,
        since: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Execute query against speed layer (Redis cache).

        Args:
            view_definition: SQL-on-FHIR ViewDefinition
            search_params: Search parameters (gender, code, etc.)
            max_resources: Maximum results to return
            since: Only include resources cached after this time

        Returns:
            Query results with patient IDs and metadata
        """
        view_name = view_definition.get("name", "unknown")
        resource_type = self._get_resource_type(view_definition)

        logger.info(f"[SpeedLayerRunner] Querying Redis for {resource_type} (view: {view_name})")

        # Default to last 24 hours if not specified
        if not since:
            since = datetime.utcnow() - timedelta(hours=24)

        # Scan Redis for recent resources
        resources = await self.redis_client.scan_recent_resources(
            resource_type=resource_type,
            since=since
        )

        logger.info(f"[SpeedLayerRunner] Found {len(resources)} recent {resource_type} resources in Redis")

        # Apply search parameter filters
        if search_params:
            resources = self._apply_filters(resources, search_params, view_definition)

        # Limit results
        resources = resources[:max_resources]

        # Extract patient IDs
        patient_ids = self._extract_patient_ids(resources, view_definition)

        return {
            "view_name": view_name,
            "source": "speed_layer",
            "total_count": len(patient_ids),
            "patient_ids": list(patient_ids),
            "resources": resources,
            "query_timestamp": datetime.utcnow().isoformat(),
            "since": since.isoformat() if since else None
        }

    def _get_resource_type(self, view_definition: Dict[str, Any]) -> str:
        """Extract FHIR resource type from ViewDefinition."""
        # From ViewDefinition.select[0].from_
        select = view_definition.get("select", [])
        if select and len(select) > 0:
            from_clause = select[0].get("from", "")
            # Extract resource type (e.g., "Patient" from "Patient")
            return from_clause.split(".")[0] if "." in from_clause else from_clause
        return "Patient"  # default

    def _apply_filters(
        self,
        resources: List[Dict[str, Any]],
        search_params: Dict[str, str],
        view_definition: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Apply search parameter filters to resources."""
        filtered = resources

        # Gender filter (for Patient resources)
        if "gender" in search_params:
            gender = search_params["gender"].lower()
            filtered = [
                r for r in filtered
                if r.get("gender", "").lower() == gender
            ]

        # Code filter (for Condition/Observation resources)
        if "code" in search_params:
            code_value = search_params["code"]
            filtered = [
                r for r in filtered
                if self._matches_code(r, code_value)
            ]

        return filtered

    def _matches_code(self, resource: Dict[str, Any], code_value: str) -> bool:
        """Check if resource matches a code value."""
        code = resource.get("code", {})

        # Check coding array
        codings = code.get("coding", [])
        for coding in codings:
            if coding.get("code") == code_value:
                return True

        # Check text
        if code_value.lower() in code.get("text", "").lower():
            return True

        return False

    def _extract_patient_ids(
        self,
        resources: List[Dict[str, Any]],
        view_definition: Dict[str, Any]
    ) -> set:
        """Extract patient IDs from resources."""
        patient_ids = set()

        for resource in resources:
            resource_type = resource.get("resourceType", "")

            if resource_type == "Patient":
                # Patient resource: use ID directly
                patient_ids.add(resource.get("id"))
            else:
                # Other resources: extract from subject reference
                subject = resource.get("subject", {})
                reference = subject.get("reference", "")
                # Extract "12345" from "Patient/12345"
                if reference.startswith("Patient/"):
                    patient_id = reference.split("/")[1]
                    patient_ids.add(patient_id)

        return patient_ids
```

#### Day 5: Update HybridRunner for Merge Logic

**Task 1.5: Update HybridRunner**

File: `app/sql_on_fhir/runner/hybrid_runner.py`

Add speed layer integration:

```python
# Add to existing HybridRunner class

from app/cache/redis_client import RedisClient
from app.sql_on_fhir.runner.speed_layer_runner import SpeedLayerRunner

class HybridRunner:
    """Updated to merge batch + speed layers."""

    def __init__(self, db_client, redis_client: Optional[RedisClient] = None):
        self.materialized_runner = MaterializedViewRunner(db_client)
        self._postgres_runner = None
        self._view_exists_cache = {}

        # Speed layer integration
        self.redis_client = redis_client or RedisClient()
        self.speed_layer_runner = SpeedLayerRunner(self.redis_client)
        self.use_speed_layer = os.getenv("USE_SPEED_LAYER", "true").lower() == "true"

    async def execute(
        self,
        view_definition: Dict[str, Any],
        search_params: Optional[Dict[str, str]] = None,
        max_resources: int = 1000
    ) -> Dict[str, Any]:
        """
        Execute query with smart routing + speed layer merge.

        Strategy:
        1. Try materialized view (batch layer) if exists
        2. If enabled, query speed layer (Redis) for recent data
        3. Merge results and deduplicate
        4. Fall back to PostgresRunner if no materialized view
        """
        view_name = view_definition.get("name")

        # Step 1: Query batch layer
        if await self._check_view_exists(view_name):
            batch_result = await self.materialized_runner.execute(
                view_definition, search_params, max_resources
            )
        else:
            # Fallback to SQL generation
            batch_result = await self.postgres_runner.execute(
                view_definition, search_params, max_resources
            )

        # Step 2: Query speed layer for recent data
        if self.use_speed_layer:
            try:
                speed_result = await self.speed_layer_runner.execute(
                    view_definition, search_params, max_resources
                )

                # Step 3: Merge results
                merged_result = self._merge_results(batch_result, speed_result)
                merged_result["sources"] = ["batch_layer", "speed_layer"]

                return merged_result
            except Exception as e:
                logger.warning(f"Speed layer query failed: {e}, using batch only")
                return batch_result
        else:
            return batch_result

    def _merge_results(
        self,
        batch_result: Dict[str, Any],
        speed_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Merge batch and speed layer results.

        Deduplication strategy:
        - Speed layer overrides batch layer for same patient
          (speed layer has more recent data)
        """
        # Combine patient IDs
        batch_ids = set(batch_result.get("patient_ids", []))
        speed_ids = set(speed_result.get("patient_ids", []))

        all_patient_ids = batch_ids | speed_ids  # Union

        return {
            "view_name": batch_result.get("view_name"),
            "total_count": len(all_patient_ids),
            "patient_ids": list(all_patient_ids),
            "batch_count": len(batch_ids),
            "speed_count": len(speed_ids),
            "overlap_count": len(batch_ids & speed_ids),
            "query_timestamp": datetime.utcnow().isoformat()
        }
```

### Week 2: FHIR Change Capture & Auto-Refresh

#### Day 6-8: FHIR Subscription Service (Mock)

**Task 2.1: Create FHIR Subscription Service**

File: `app/services/fhir_subscription_service.py`

```python
"""FHIR subscription service for capturing resource changes."""
import asyncio
import logging
from typing import Dict, List, Any
from datetime import datetime, timedelta

from app.cache.redis_client import RedisClient
from app.clients.hapi_db_client import HAPIDBClient

logger = logging.getLogger(__name__)


class FHIRSubscriptionService:
    """
    Mock FHIR subscription service.

    Polls FHIR database for recent changes and writes to Redis speed layer.
    Future: Replace with real FHIR Subscription resource.
    """

    def __init__(
        self,
        hapi_client: HAPIDBClient,
        redis_client: RedisClient,
        poll_interval_minutes: int = 5
    ):
        self.hapi_client = hapi_client
        self.redis_client = redis_client
        self.poll_interval = poll_interval_minutes
        self.last_sync_time = datetime.utcnow() - timedelta(hours=24)
        self._running = False

    async def start(self):
        """Start the subscription service."""
        self._running = True
        logger.info("[FHIRSubscriptionService] Starting...")

        while self._running:
            try:
                await self._poll_and_cache()
                await asyncio.sleep(self.poll_interval * 60)
            except Exception as e:
                logger.error(f"[FHIRSubscriptionService] Error: {e}")
                await asyncio.sleep(60)  # Wait 1 min before retry

    def stop(self):
        """Stop the subscription service."""
        self._running = False
        logger.info("[FHIRSubscriptionService] Stopped")

    async def _poll_and_cache(self):
        """Poll FHIR for recent changes and cache in Redis."""
        logger.info("[FHIRSubscriptionService] Polling for recent FHIR changes...")

        # Query FHIR for resources updated since last sync
        recent_patients = await self._fetch_recent_patients()
        recent_conditions = await self._fetch_recent_conditions()
        recent_observations = await self._fetch_recent_observations()

        # Cache in Redis
        for patient in recent_patients:
            await self.redis_client.set_fhir_resource(
                "Patient",
                patient["id"],
                patient,
                ttl_hours=24
            )

        for condition in recent_conditions:
            await self.redis_client.set_fhir_resource(
                "Condition",
                condition["id"],
                condition,
                ttl_hours=24
            )

        for observation in recent_observations:
            await self.redis_client.set_fhir_resource(
                "Observation",
                observation["id"],
                observation,
                ttl_hours=12  # Shorter TTL for observations
            )

        total_cached = (
            len(recent_patients) +
            len(recent_conditions) +
            len(recent_observations)
        )

        logger.info(
            f"[FHIRSubscriptionService] Cached {total_cached} resources "
            f"(Patients: {len(recent_patients)}, Conditions: {len(recent_conditions)}, "
            f"Observations: {len(recent_observations)})"
        )

        # Update last sync time
        self.last_sync_time = datetime.utcnow()

    async def _fetch_recent_patients(self) -> List[Dict[str, Any]]:
        """Fetch patients updated since last sync."""
        # Mock implementation: Query FHIR database
        # TODO: Replace with actual FHIR API call
        query = """
            SELECT
                id,
                resource_content::json as resource
            FROM hfj_resource
            WHERE res_type = 'Patient'
              AND res_updated > %s
            ORDER BY res_updated DESC
            LIMIT 100
        """

        # Execute query (mock result for now)
        return []

    async def _fetch_recent_conditions(self) -> List[Dict[str, Any]]:
        """Fetch conditions updated since last sync."""
        # Similar to _fetch_recent_patients
        return []

    async def _fetch_recent_observations(self) -> List[Dict[str, Any]]:
        """Fetch observations updated since last sync."""
        # Similar to _fetch_recent_patients
        return []
```

#### Day 9-10: Auto-Refresh Pipeline

**Task 2.2: Create Materialized View Refresh Script**

File: `scripts/refresh_materialized_views.py`

```python
"""Automated materialized view refresh pipeline."""
import asyncio
import logging
from datetime import datetime

from app.services.materialized_view_service import MaterializedViewService
from app.clients.hapi_db_client import HAPIDBClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def refresh_all_views():
    """Refresh all materialized views."""
    logger.info("=" * 60)
    logger.info("MATERIALIZED VIEW REFRESH PIPELINE")
    logger.info(f"Started at: {datetime.utcnow().isoformat()}")
    logger.info("=" * 60)

    # Initialize service
    db_client = HAPIDBClient()
    service = MaterializedViewService(db_client)

    try:
        # List all views
        views = await service.list_views()
        logger.info(f"\nFound {len(views)} materialized views to refresh")

        # Refresh each view
        for i, view in enumerate(views, 1):
            view_name = view["view_name"]
            logger.info(f"\n[{i}/{len(views)}] Refreshing {view_name}...")

            start_time = datetime.utcnow()
            await service.refresh_view(view_name)
            duration = (datetime.utcnow() - start_time).total_seconds()

            logger.info(f"✅ {view_name} refreshed in {duration:.2f}s")

        logger.info("\n" + "=" * 60)
        logger.info("REFRESH COMPLETE")
        logger.info(f"Finished at: {datetime.utcnow().isoformat()}")
        logger.info("=" * 60)

    finally:
        await db_client.close()


if __name__ == "__main__":
    asyncio.run(refresh_all_views())
```

**Task 2.3: Add Cron Job Configuration**

Create documentation for setting up cron:

File: `docs/AUTO_REFRESH_SETUP.md`

```markdown
# Auto-Refresh Setup

## Cron Job for Nightly Materialized View Refresh

Add to crontab (`crontab -e`):

```bash
# Refresh materialized views every night at 2 AM
0 2 * * * cd /path/to/FHIR_PROJECT && .venv/bin/python scripts/refresh_materialized_views.py >> logs/refresh.log 2>&1
```

Or use systemd timer (Linux):

```ini
# /etc/systemd/system/researchflow-refresh.service
[Unit]
Description=ResearchFlow Materialized View Refresh
After=network.target

[Service]
Type=oneshot
WorkingDirectory=/path/to/FHIR_PROJECT
ExecStart=/path/to/FHIR_PROJECT/.venv/bin/python scripts/refresh_materialized_views.py

[Install]
WantedBy=multi-user.target

# /etc/systemd/system/researchflow-refresh.timer
[Unit]
Description=Run ResearchFlow refresh nightly
Requires=researchflow-refresh.service

[Timer]
OnCalendar=*-*-* 02:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

Enable:
```bash
systemctl enable researchflow-refresh.timer
systemctl start researchflow-refresh.timer
```
```

---

## Testing Plan

### Unit Tests

File: `tests/test_speed_layer_runner.py`

```python
"""Tests for SpeedLayerRunner."""
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

from app.cache.redis_client import RedisClient
from app.sql_on_fhir.runner.speed_layer_runner import SpeedLayerRunner


@pytest.fixture
async def redis_client():
    client = RedisClient()
    await client.connect()
    await client.flush_all()  # Clean slate
    yield client
    await client.disconnect()


@pytest.fixture
def speed_layer_runner(redis_client):
    return SpeedLayerRunner(redis_client)


@pytest.mark.asyncio
async def test_query_recent_patients(redis_client, speed_layer_runner):
    """Test querying recent patients from Redis."""
    # Setup: Cache a recent patient
    patient_data = {
        "resourceType": "Patient",
        "id": "test-123",
        "gender": "male",
        "birthDate": "1990-01-01"
    }

    await redis_client.set_fhir_resource("Patient", "test-123", patient_data)

    # Execute: Query for male patients
    view_definition = {
        "name": "patient_demographics",
        "select": [{"from": "Patient"}]
    }

    result = await speed_layer_runner.execute(
        view_definition,
        search_params={"gender": "male"}
    )

    # Verify
    assert result["total_count"] == 1
    assert "test-123" in result["patient_ids"]
    assert result["source"] == "speed_layer"


@pytest.mark.asyncio
async def test_merge_batch_and_speed(redis_client):
    """Test merging batch and speed layer results."""
    # ... test implementation ...
```

### Integration Tests

File: `tests/integration/test_lambda_architecture_e2e.py`

```python
"""E2E tests for complete Lambda architecture."""
import pytest
from datetime import datetime

from app.sql_on_fhir.runner.hybrid_runner import HybridRunner
from app.cache.redis_client import RedisClient
from app.clients.hapi_db_client import HAPIDBClient


@pytest.mark.asyncio
async def test_lambda_architecture_complete_flow():
    """Test complete Lambda architecture: batch + speed + serving."""
    # Setup
    db_client = HAPIDBClient()
    redis_client = RedisClient()
    hybrid_runner = HybridRunner(db_client, redis_client)

    # 1. Add a new patient to Redis (speed layer)
    new_patient = {
        "resourceType": "Patient",
        "id": "new-patient-today",
        "gender": "female"
    }
    await redis_client.set_fhir_resource("Patient", "new-patient-today", new_patient)

    # 2. Query via HybridRunner
    view_def = {"name": "patient_demographics", "select": [{"from": "Patient"}]}
    result = await hybrid_runner.execute(view_def, {"gender": "female"})

    # 3. Verify new patient is included
    assert "new-patient-today" in result["patient_ids"]
    assert result["sources"] == ["batch_layer", "speed_layer"]
    assert result["speed_count"] >= 1
```

### Performance Benchmarks

File: `benchmarks/benchmark_speed_layer.py`

```python
"""Benchmark Redis speed layer performance."""
import asyncio
import time
from app.cache.redis_client import RedisClient


async def benchmark_redis_latency():
    """Measure Redis query latency."""
    client = RedisClient()
    await client.connect()

    # Warm up
    await client.set_fhir_resource("Patient", "warmup", {"id": "warmup"})

    # Benchmark: 100 writes
    start = time.time()
    for i in range(100):
        await client.set_fhir_resource("Patient", f"test-{i}", {"id": f"test-{i}"})
    write_duration = time.time() - start

    # Benchmark: 100 reads
    start = time.time()
    for i in range(100):
        await client.get_fhir_resource("Patient", f"test-{i}")
    read_duration = time.time() - start

    print(f"Redis Write Latency: {write_duration/100*1000:.2f}ms per write")
    print(f"Redis Read Latency: {read_duration/100*1000:.2f}ms per read")

    # Target: <10ms per operation
    assert write_duration/100 < 0.01, "Write latency exceeds 10ms"
    assert read_duration/100 < 0.01, "Read latency exceeds 10ms"


if __name__ == "__main__":
    asyncio.run(benchmark_redis_latency())
```

---

## Success Criteria

| Criterion | Target | Measurement | Status |
|-----------|--------|-------------|--------|
| Redis query latency | <10ms | Benchmark script | ⏳ Pending |
| Speed layer coverage | Last 24 hours | Integration tests | ⏳ Pending |
| Merge accuracy | 100% (no data loss) | E2E tests | ⏳ Pending |
| Auto-refresh success | Runs nightly | Cron logs | ⏳ Pending |
| Test coverage | 80%+ | pytest-cov | ⏳ Pending |
| Documentation | Complete | Review | ⏳ Pending |

---

## Rollout Plan

### Phase 1: Development (Week 1)
- ✅ Redis infrastructure setup
- ✅ Speed layer runner implementation
- ✅ HybridRunner merge logic

### Phase 2: Testing (Week 2)
- ✅ Unit tests (80%+ coverage)
- ✅ Integration tests (batch + speed)
- ✅ Performance benchmarks (<10ms latency)

### Phase 3: Deployment (After Sprint 5.5)
1. Deploy Redis to staging environment
2. Enable speed layer (USE_SPEED_LAYER=true)
3. Monitor for 2-3 days
4. Deploy to production if stable

### Phase 4: Production Monitoring
- Monitor Redis memory usage
- Track speed layer hit rate
- Alert if Redis is down (fallback to batch only)

---

## Risks & Mitigation

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Redis OOM (out of memory) | High | Medium | Set maxmemory + LRU eviction |
| Speed layer miss rate high | Medium | Low | Increase poll frequency (5 min → 2 min) |
| FHIR polling overhead | Medium | Low | Use FHIR subscriptions (Sprint 6+) |
| Merge logic bugs | High | Medium | Comprehensive E2E tests |

---

## Future Enhancements (Post-Sprint 5.5)

1. **Real FHIR Subscriptions** (Sprint 6)
   - Replace polling with real FHIR Subscription resources
   - Push-based updates (more efficient than polling)

2. **Incremental Materialized View Refresh** (Sprint 7)
   - Only refresh rows that changed (not full rebuild)
   - Faster refresh times

3. **Speed Layer Monitoring Dashboard** (Sprint 8)
   - Redis metrics (hit rate, latency, memory)
   - Speed layer coverage visualization

---

## References

- Sprint 4.5: [SPRINT_04_5_MATERIALIZED_VIEWS.md](SPRINT_04_5_MATERIALIZED_VIEWS.md)
- Sprint 5: [SPRINT_05_COMPLETION_SUMMARY.md](SPRINT_05_COMPLETION_SUMMARY.md)
- Lambda Architecture: [MATERIALIZED_VIEWS_ARCHITECTURE.md](../MATERIALIZED_VIEWS_ARCHITECTURE.md)
- Redis Docs: https://redis.io/docs/

---

**Last Updated**: 2025-10-28
**Status**: ⏳ Planning
**Next Action**: Approve plan and begin Week 1 implementation
