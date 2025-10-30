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

        ttl_seconds = int(ttl_hours * 3600)

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
