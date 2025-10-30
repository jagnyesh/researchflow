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
        """
        Fetch patients updated since last sync.

        Uses HAPI FHIR database structure to query recent Patient resources.
        """
        query = """
            SELECT
                res_id as id,
                res_text_vc as resource
            FROM hfj_resource
            WHERE res_type = 'Patient'
              AND res_updated > %s
            ORDER BY res_updated DESC
            LIMIT 100
        """

        try:
            results = await self.hapi_client.execute_query(
                query,
                (self.last_sync_time,)
            )

            resources = []
            for row in results:
                try:
                    import json
                    resource = json.loads(row['resource']) if isinstance(row['resource'], str) else row['resource']
                    resources.append(resource)
                except Exception as e:
                    logger.warning(f"Failed to parse Patient resource: {e}")

            return resources
        except Exception as e:
            logger.error(f"Failed to fetch recent patients: {e}")
            return []

    async def _fetch_recent_conditions(self) -> List[Dict[str, Any]]:
        """
        Fetch conditions updated since last sync.

        Uses HAPI FHIR database structure to query recent Condition resources.
        """
        query = """
            SELECT
                res_id as id,
                res_text_vc as resource
            FROM hfj_resource
            WHERE res_type = 'Condition'
              AND res_updated > %s
            ORDER BY res_updated DESC
            LIMIT 100
        """

        try:
            results = await self.hapi_client.execute_query(
                query,
                (self.last_sync_time,)
            )

            resources = []
            for row in results:
                try:
                    import json
                    resource = json.loads(row['resource']) if isinstance(row['resource'], str) else row['resource']
                    resources.append(resource)
                except Exception as e:
                    logger.warning(f"Failed to parse Condition resource: {e}")

            return resources
        except Exception as e:
            logger.error(f"Failed to fetch recent conditions: {e}")
            return []

    async def _fetch_recent_observations(self) -> List[Dict[str, Any]]:
        """
        Fetch observations updated since last sync.

        Uses HAPI FHIR database structure to query recent Observation resources.
        """
        query = """
            SELECT
                res_id as id,
                res_text_vc as resource
            FROM hfj_resource
            WHERE res_type = 'Observation'
              AND res_updated > %s
            ORDER BY res_updated DESC
            LIMIT 100
        """

        try:
            results = await self.hapi_client.execute_query(
                query,
                (self.last_sync_time,)
            )

            resources = []
            for row in results:
                try:
                    import json
                    resource = json.loads(row['resource']) if isinstance(row['resource'], str) else row['resource']
                    resources.append(resource)
                except Exception as e:
                    logger.warning(f"Failed to parse Observation resource: {e}")

            return resources
        except Exception as e:
            logger.error(f"Failed to fetch recent observations: {e}")
            return []
