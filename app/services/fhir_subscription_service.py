"""Speed-layer poller for the Lambda Architecture's near-real-time tier."""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List

from app.cache.redis_client import RedisClient
from app.clients.hapi_db_client import HAPIDBClient

logger = logging.getLogger(__name__)


class FHIRSubscriptionService:
    """Speed-layer for the Lambda Architecture: polls HAPI's hfj_resource for
    recent changes and writes them to Redis with a 24-hour TTL.

    The class name (`FHIRSubscriptionService`) is a misnomer — it does NOT
    use HAPI's Subscription resource. Per /office-hours decision Q4 (2026-05-09,
    issue #17), we ship polling as the production speed-layer pattern. The
    Subscription resource exists on this HAPI instance but the activation
    worker isn't enabled in the docker-compose config, and enabling it would
    require docker-compose changes + webhook auth + idempotency — 3-4 days
    of work to ship "real-time push" when polling at 30s satisfies the
    Lambda Architecture's "<1 minute freshness" guarantee.

    HybridRunner reads from this Redis cache and merges with materialized-view
    results to serve cohort queries with batch-layer scale + speed-layer
    freshness.

    Cache keys: `fhir:<lowercase-type>:<fhir-id>` (matches RedisClient's key
    format). The fhir-id is HAPI's `hfj_resource.fhir_id` column — the FHIR
    logical id, NOT the internal `res_id` bigint. Downstream consumers
    (HybridRunner, SpeedLayerRunner) match against materialized-view rows by
    FHIR id, so cache keys must use the same identifier.
    """

    # Resource types polled, with per-type TTL. Observations get a shorter TTL
    # because they're high-volume and individually less important to retain;
    # Patient/Condition are referenced by every cohort query.
    _POLLED_TYPES: Dict[str, int] = {
        "Patient": 24,
        "Condition": 24,
        "Observation": 12,
    }

    def __init__(
        self,
        hapi_client: HAPIDBClient,
        redis_client: RedisClient,
        poll_interval_seconds: int = 30,
    ):
        self.hapi_client = hapi_client
        self.redis_client = redis_client
        # Issue #17: dropped from 300s (5min) to 30s. The Lambda Architecture's
        # "<1 minute freshness" claim requires polling at least once per minute;
        # 30s gives margin. Older callers that passed poll_interval_minutes will
        # break — that's intentional, the unit changed.
        self.poll_interval_seconds = poll_interval_seconds
        # Backward-compat alias for any code still reading .poll_interval
        self.poll_interval = poll_interval_seconds
        self.last_sync_time = datetime.utcnow() - timedelta(hours=24)
        self._running = False

    async def start(self):
        """Run the polling loop until stop() is called."""
        self._running = True
        logger.info("[FHIRSubscriptionService] Starting (interval=%ds)", self.poll_interval_seconds)

        while self._running:
            try:
                await self._poll_and_cache()
                await asyncio.sleep(self.poll_interval_seconds)
            except Exception as e:
                logger.error(f"[FHIRSubscriptionService] Error: {e}")
                await asyncio.sleep(60)  # Wait 1 min before retry

    def stop(self):
        """Stop the polling loop after the current iteration."""
        self._running = False
        logger.info("[FHIRSubscriptionService] Stopped")

    async def _poll_and_cache(self):
        """One polling cycle: fetch recent resources for each tracked type and
        write them to Redis. Updates `last_sync_time` after a successful run.

        Per-type errors are logged but don't abort the cycle — one failed
        resource type shouldn't drop all the others.
        """
        logger.info("[FHIRSubscriptionService] Polling for recent FHIR changes...")

        cycle_started_at = datetime.utcnow()
        per_type_counts: Dict[str, int] = {}

        for resource_type, ttl_hours in self._POLLED_TYPES.items():
            count = await self._fetch_and_cache(resource_type, ttl_hours)
            per_type_counts[resource_type] = count

        total_cached = sum(per_type_counts.values())
        logger.info(
            "[FHIRSubscriptionService] Cached %d resources (%s)",
            total_cached,
            ", ".join(f"{k}: {v}" for k, v in per_type_counts.items()),
        )

        # Advance the sync watermark only after a full successful cycle —
        # a partial failure leaves the watermark stale so the missed window
        # gets re-polled next cycle.
        self.last_sync_time = cycle_started_at

    async def _fetch_and_cache(self, resource_type: str, ttl_hours: int) -> int:
        """Fetch resources of `resource_type` updated since last sync, write
        each to Redis keyed by FHIR logical id. Returns count cached.

        Issue #17 fixes three bugs from the prior implementation:
        - SQL placeholder `%s` (psycopg2) → `$1` (asyncpg, what the HAPIDBClient
          actually uses). The prior code crashed at every poll cycle with
          "syntax error at %".
        - `res_text_vc` is on `hfj_res_ver`, NOT `hfj_resource`. The prior SQL
          referenced a non-existent column. Now JOINs the version table.
        - Cache key uses `r.fhir_id` (FHIR logical id) not the internal
          `res_id` bigint. Without this fix, downstream consumers that match
          against materialized-view ids find nothing.
        """
        sql = """
            SELECT r.fhir_id, v.res_text_vc
            FROM hfj_resource r
            JOIN hfj_res_ver v ON v.res_id = r.res_id AND v.res_ver = r.res_ver
            WHERE r.res_type = $1
              AND r.res_deleted_at IS NULL
              AND r.res_updated > $2
            ORDER BY r.res_updated DESC
            LIMIT 100
        """

        try:
            results = await self.hapi_client.execute_query(
                sql, (resource_type, self.last_sync_time)
            )
        except Exception as e:
            logger.error("Failed to fetch recent %s resources: %s", resource_type, e)
            return 0

        cached = 0
        for row in results:
            fhir_id = row.get("fhir_id")
            if not fhir_id:
                logger.warning("%s row missing fhir_id; skipping", resource_type)
                continue

            raw = row.get("res_text_vc")
            try:
                resource_data = json.loads(raw) if isinstance(raw, str) else raw
            except (TypeError, ValueError) as e:
                logger.warning("Failed to parse %s/%s JSON: %s", resource_type, fhir_id, e)
                continue

            try:
                await self.redis_client.set_fhir_resource(
                    resource_type, fhir_id, resource_data, ttl_hours=ttl_hours
                )
                cached += 1
            except Exception as e:
                logger.warning("Failed to cache %s/%s: %s", resource_type, fhir_id, e)

        return cached
