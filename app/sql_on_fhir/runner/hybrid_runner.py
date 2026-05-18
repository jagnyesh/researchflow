"""
Hybrid Runner - Best of Both Worlds

Intelligently routes queries to the fastest available method:
1. Check if materialized view exists in 'sqlonfhir' schema
2. If EXISTS: Use MaterializedViewRunner (5-10ms, ultra-fast)
3. If NOT EXISTS: Fall back to PostgresRunner (50-500ms, still fast)

This provides:
- Maximum performance when views are materialized
- Full compatibility when views don't exist yet
- Seamless migration path (materialize views incrementally)
- Zero configuration required

Architecture:
- Delegates to MaterializedViewRunner or PostgresRunner
- Caches view existence checks to avoid overhead
- Same interface as other runners for drop-in replacement

Performance Profile:
- View exists: 5-10ms (materialized)
- View doesn't exist: 50-500ms (postgres with transpilation)
- View check overhead: <1ms (cached after first check)
"""

import os
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from langsmith import traceable

from app.clients.hapi_db_client import HAPIDBClient
from app.sql_on_fhir.runner.materialized_view_runner import MaterializedViewRunner
from app.sql_on_fhir.transpiler import create_fhirpath_transpiler, create_column_extractor
from app.sql_on_fhir.query_builder import create_sql_query_builder
from app.cache.redis_client import RedisClient
from app.sql_on_fhir.runner.speed_layer_runner import SpeedLayerRunner

logger = logging.getLogger(__name__)


class HybridRunner:
    """
    Hybrid runner that automatically selects the best execution strategy

    Uses materialized views when available (fast path), falls back to
    SQL generation when not available (compatibility path).

    This is the recommended runner type for production use.
    """

    SCHEMA_NAME = "sqlonfhir"

    def __init__(
        self,
        db_client: HAPIDBClient,
        redis_client: Optional[RedisClient] = None,
        enable_cache: bool = True,
        cache_ttl_seconds: int = 300,
    ):
        """
        Initialize hybrid runner

        Args:
            db_client: HAPI database client
            redis_client: Redis client for speed layer (optional)
            enable_cache: Enable query result caching for PostgresRunner fallback
            cache_ttl_seconds: Cache TTL in seconds
        """
        self.db_client = db_client
        self.enable_cache = enable_cache
        self.cache_ttl_seconds = cache_ttl_seconds

        # Initialize both runners
        self.materialized_runner = MaterializedViewRunner(db_client)
        self._postgres_runner = None  # Lazy initialization

        # Speed layer integration
        self.redis_client = redis_client or RedisClient()
        self.speed_layer_runner = SpeedLayerRunner(self.redis_client)
        self.use_speed_layer = os.getenv("USE_SPEED_LAYER", "true").lower() == "true"

        # Cache for view existence checks
        self._view_exists_cache: Dict[str, bool] = {}

        # Statistics
        self._materialized_queries = 0
        self._postgres_queries = 0
        self._speed_layer_queries = 0

        logger.info(
            f"Initialized HybridRunner "
            f"(materialized views: enabled, postgres fallback: enabled, "
            f"speed layer: {'enabled' if self.use_speed_layer else 'disabled'})"
        )

    async def execute(
        self,
        view_definition: Dict[str, Any],
        search_params: Optional[Dict[str, Any]] = None,
        max_resources: Optional[int] = None,
        mode: "FreshnessAnnotation" = None,
    ) -> List[Dict[str, Any]]:
        """
        Execute ViewDefinition using best available method with speed layer merge

        Args:
            view_definition: ViewDefinition resource
            search_params: Optional FHIR search parameters
            max_resources: Maximum number of resources/rows
            mode: FreshnessAnnotation routing intent (Sprint 6.5 #69).
                Defaults to EXPLORATORY for backward compatibility with
                pre-Sprint-6.5 callers; EXPLORATORY preserves the existing
                speed-merged behavior. Cycle 2 only introduces the
                parameter; cycles 3-4 specialize behavior per mode.

        Returns:
            List of rows (each row is a dict with column values)

        Strategy:
            1. Query batch layer (materialized view or PostgresRunner)
            2. If enabled, query speed layer (Redis) for recent data
            3. Merge results and deduplicate
        """
        # Cycle 2 (#69): accept mode parameter, default to EXPLORATORY for
        # backward compat. Behavior per-mode is specialized in later cycles.
        from app.sql_on_fhir.runner.freshness import FreshnessAnnotation

        if mode is None:
            mode = FreshnessAnnotation.EXPLORATORY
        view_name = view_definition.get("name")

        # Step 1: Query batch layer
        view_exists = await self._check_view_exists(view_name)

        if view_exists:
            # Fast path: Use materialized view
            logger.debug(f"Using MaterializedViewRunner for '{view_name}' (batch layer)")
            self._materialized_queries += 1

            try:
                batch_result = await self.materialized_runner.execute(
                    view_definition, search_params=search_params, max_resources=max_resources
                )
            except Exception as e:
                logger.warning(
                    f"MaterializedViewRunner failed for '{view_name}': {e}. "
                    f"Falling back to PostgresRunner"
                )
                # Fall back to PostgresRunner
                postgres_runner = await self._get_postgres_runner()
                self._postgres_queries += 1
                batch_result = await postgres_runner.execute(
                    view_definition, search_params=search_params, max_resources=max_resources
                )
        else:
            # Fallback to PostgresRunner
            logger.debug(f"Using PostgresRunner for '{view_name}' (batch layer fallback)")
            self._postgres_queries += 1
            postgres_runner = await self._get_postgres_runner()
            batch_result = await postgres_runner.execute(
                view_definition, search_params=search_params, max_resources=max_resources
            )

        # Step 2: Query speed layer for recent data (if enabled)
        if self.use_speed_layer:
            try:
                self._speed_layer_queries += 1
                speed_result = await self.speed_layer_runner.execute(
                    view_definition, search_params=search_params, max_resources=max_resources
                )

                # Step 3: Merge results (if speed layer has data)
                if speed_result.get("total_count", 0) > 0:
                    logger.debug(
                        f"Merging batch layer ({len(batch_result)} rows) with "
                        f"speed layer ({speed_result['total_count']} patients)"
                    )
                    return self._merge_batch_and_speed_results(
                        batch_result, speed_result, view_definition
                    )

            except Exception as e:
                logger.warning(f"Speed layer query failed for '{view_name}': {e}. Using batch only")

        return batch_result

    @traceable(tags=["hybrid-runner", "count"])
    async def execute_count(
        self, view_definition: Dict[str, Any], search_params: Optional[Dict[str, Any]] = None
    ) -> int:
        """
        Execute COUNT query using best available method

        Args:
            view_definition: ViewDefinition resource
            search_params: Optional FHIR search parameters

        Returns:
            Count of matching resources/rows
        """
        view_name = view_definition.get("name")

        # Check if materialized view exists
        view_exists = await self._check_view_exists(view_name)

        if view_exists:
            # Fast path: Use materialized view
            logger.debug(f"Using MaterializedViewRunner for COUNT '{view_name}' (fast path)")

            try:
                return await self.materialized_runner.execute_count(
                    view_definition, search_params=search_params
                )
            except Exception as e:
                logger.warning(
                    f"MaterializedViewRunner COUNT failed for '{view_name}': {e}. "
                    f"Falling back to PostgresRunner"
                )
                # Fall through to PostgresRunner fallback

        # Slow path: Fall back to PostgresRunner
        logger.debug(f"Using PostgresRunner for COUNT '{view_name}' (fallback)")

        postgres_runner = await self._get_postgres_runner()

        return await postgres_runner.execute_count(view_definition, search_params=search_params)

    def get_schema(self, view_definition: Dict[str, Any]) -> Dict[str, str]:
        """
        Get column schema from ViewDefinition

        Args:
            view_definition: ViewDefinition resource

        Returns:
            Dictionary mapping column names to types
        """
        return self.materialized_runner.get_schema(view_definition)

    def get_last_executed_sql(self) -> Optional[str]:
        """
        Get the last executed SQL query (for debugging)

        Returns:
            SQL query string or None
        """
        # Try materialized runner first
        sql = self.materialized_runner.get_last_executed_sql()

        if sql:
            return sql

        # Fall back to postgres runner if initialized
        if self._postgres_runner:
            return self._postgres_runner.get_last_executed_sql()

        return None

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get runner statistics

        Returns:
            Dictionary with execution stats
        """
        total_queries = self._materialized_queries + self._postgres_queries

        materialized_pct = (
            (self._materialized_queries / total_queries * 100) if total_queries > 0 else 0.0
        )

        stats = {
            "runner_type": "hybrid",
            "total_queries": total_queries,
            "materialized_queries": self._materialized_queries,
            "postgres_queries": self._postgres_queries,
            "speed_layer_queries": self._speed_layer_queries,
            "materialized_percentage": materialized_pct,
            "speed_layer_enabled": self.use_speed_layer,
            "views_cached": len(self._view_exists_cache),
        }

        # Add sub-runner stats if available
        stats["materialized_runner_stats"] = self.materialized_runner.get_statistics()

        if self._postgres_runner:
            stats["postgres_runner_stats"] = self._postgres_runner.get_statistics()

        return stats

    # Private helper methods

    async def _check_view_exists(self, view_name: str) -> bool:
        """
        Check if materialized view exists (with caching)

        Args:
            view_name: Name of the view

        Returns:
            True if view exists, False otherwise
        """
        # Check cache first
        if view_name in self._view_exists_cache:
            return self._view_exists_cache[view_name]

        # Query database
        sql = f"""
            SELECT EXISTS (
                SELECT 1
                FROM pg_matviews
                WHERE schemaname = '{self.SCHEMA_NAME}'
                  AND matviewname = '{view_name}'
            ) as exists
        """

        try:
            result = await self.db_client.execute_query(sql)
            exists = result[0]["exists"] if result else False

            # Cache result
            self._view_exists_cache[view_name] = exists

            return exists

        except Exception as e:
            logger.warning(f"Failed to check view existence for '{view_name}': {e}")
            # Don't cache failures
            return False

    async def _get_postgres_runner(self):
        """
        Get or create PostgresRunner instance (lazy initialization)

        Returns:
            PostgresRunner instance
        """
        if self._postgres_runner is None:
            # Lazy import to avoid circular dependency
            from app.sql_on_fhir.runner.postgres_runner import PostgresRunner

            # Initialize components for PostgresRunner
            transpiler = create_fhirpath_transpiler()
            extractor = create_column_extractor(transpiler)
            builder = create_sql_query_builder(transpiler, extractor)

            # Create PostgresRunner
            self._postgres_runner = PostgresRunner(
                self.db_client,
                enable_cache=self.enable_cache,
                cache_ttl_seconds=self.cache_ttl_seconds,
            )

            logger.debug("Initialized PostgresRunner for fallback")

        return self._postgres_runner

    def _merge_batch_and_speed_results(
        self,
        batch_result: List[Dict[str, Any]],
        speed_result: Dict[str, Any],
        view_definition: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Merge batch and speed layer results, deduplicating by FHIR id.

        Issue #19: previously a no-op (returned batch_result unchanged); the
        Lambda Architecture's "fresher wins" guarantee depends on this method
        actually merging. Cache resources are converted to view-def-shaped rows
        via InMemoryRunner's row-extraction logic, then deduped against the
        batch result by id.

        Dedup policy: cache version wins on id collision. The cache holds the
        most-recently-polled state of each resource (per issue #17), so it's
        fresher than the materialized view by definition. Batch rows whose id
        is in the cache are dropped; cache rows replace them. Batch rows whose
        id is NOT in the cache pass through unchanged.

        Args:
            batch_result: Rows from batch layer (materialized views)
            speed_result: Results from speed layer (Redis), shape:
                          {total_count, resources: [FHIR resource dicts], ...}
            view_definition: ViewDefinition (needed to extract column-shaped
                             rows from raw FHIR resources)

        Returns:
            Merged + deduped row list. Cache rows first (fresher), then
            non-overlapping batch rows.
        """
        cache_resources = speed_result.get("resources", [])
        if not cache_resources:
            # No-merge fast path — preserves the "no overhead when cache empty"
            # behavior that test_merge_empty_cache_returns_batch_unchanged pins.
            return batch_result

        cache_rows = self._extract_rows_from_resources(cache_resources, view_definition)
        cache_ids = {row.get("id") for row in cache_rows if row.get("id") is not None}

        # Drop batch rows whose id is in the cache (cache wins)
        deduped_batch = [row for row in batch_result if row.get("id") not in cache_ids]

        merged = cache_rows + deduped_batch
        logger.info(
            "Merge: batch=%d → %d after dedup; cache=%d → %d rows; total=%d",
            len(batch_result),
            len(deduped_batch),
            len(cache_resources),
            len(cache_rows),
            len(merged),
        )
        return merged

    def _extract_rows_from_resources(
        self, resources: List[Dict[str, Any]], view_definition: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Convert raw FHIR resources to view-def-shaped rows.

        Reuses InMemoryRunner's per-resource transformation logic
        (`_transform_resource`) so the column-extraction semantics stay
        consistent across the speed-layer-merge path and the InMemory query
        path. Reaching into a private method is intentional but a refactor
        candidate — long-term, _transform_resource should be a module-level
        function shared by both runners.

        InMemoryRunner is constructed with `fhir_client=None` because we
        only use the in-memory transformation path; the client is only
        touched by InMemoryRunner.execute() which we don't call.
        """
        from app.sql_on_fhir.runner.in_memory_runner import InMemoryRunner

        extractor = InMemoryRunner(fhir_client=None)
        all_rows: List[Dict[str, Any]] = []
        for resource in resources:
            try:
                rows = extractor._transform_resource(resource, view_definition)
                all_rows.extend(rows)
            except Exception as e:
                logger.warning(
                    "Failed to extract row from cached resource id=%s: %s",
                    resource.get("id"),
                    e,
                )
        return all_rows

    def clear_view_cache(self):
        """
        Clear the view existence cache

        Call this after creating/dropping materialized views to ensure
        the hybrid runner picks up the changes.
        """
        self._view_exists_cache.clear()
        logger.info("Cleared view existence cache")
