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

        # Sprint 6.5 Phase 2A cycle 3 (#69): last-execution metadata
        # surfaced via sibling getters, mirroring get_last_executed_sql()
        # at line 229. Populated from sqlonfhir.mv_refresh_metadata by
        # execute() after each call.
        self._last_batch_anchor_ts: Optional[datetime] = None

        # Sprint 6.5 Phase 2A cycle 5 (#69): metrics table is created
        # lazily on first execute(); flag avoids redundant CREATE IF NOT
        # EXISTS roundtrips per call. The helper itself is idempotent.
        self._metrics_table_ensured: bool = False

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
        suppress_metrics: bool = False,
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
        import time

        from app.sql_on_fhir.runner.freshness import FreshnessAnnotation

        if mode is None:
            mode = FreshnessAnnotation.EXPLORATORY
        t_start = time.perf_counter()
        view_name = view_definition.get("name")

        # Cycle 5 (#69): track merge-side state for the metric row.
        speed_layer_hit = False
        speed_layer_rows_merged = 0

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

        # Sprint 6.5 cycle 3+4+6 (#69): populate batch_anchor_ts for both
        # FORMAL_* modes via the multi-view helper (single-element list
        # today; Sprint 6.5b will pass multi-view lists for feasibility
        # JOIN queries).
        if mode in (FreshnessAnnotation.FORMAL_DRAFT, FreshnessAnnotation.FORMAL_EXTRACTION):
            self._last_batch_anchor_ts = await self.get_batch_anchor_ts_for_views([view_name])

        # Sprint 6.5 cycle 4 (#69): FORMAL_EXTRACTION skips speed-layer
        # merge entirely. The citability contract requires batch-only
        # reads — re-running the same query against the same
        # batch_anchor_ts must be bit-identical. Speed-layer overlay
        # would break that.
        if mode == FreshnessAnnotation.FORMAL_EXTRACTION:
            final_result = batch_result
        else:
            # Step 2: Query speed layer for recent data (if enabled)
            final_result = batch_result
            if self.use_speed_layer:
                try:
                    self._speed_layer_queries += 1
                    speed_result = await self.speed_layer_runner.execute(
                        view_definition,
                        search_params=search_params,
                        max_resources=max_resources,
                    )

                    # Step 3: Merge results (if speed layer has data)
                    if speed_result.get("total_count", 0) > 0:
                        speed_layer_hit = True
                        speed_layer_rows_merged = speed_result["total_count"]
                        logger.debug(
                            f"Merging batch layer ({len(batch_result)} rows) with "
                            f"speed layer ({speed_result['total_count']} patients)"
                        )
                        final_result = self._merge_batch_and_speed_results(
                            batch_result, speed_result, view_definition
                        )

                except Exception as e:
                    logger.warning(
                        f"Speed layer query failed for '{view_name}': {e}. Using batch only"
                    )

        # Sprint 6.5 cycle 5+7 (#69): write one metric row for FORMAL_DRAFT
        # unless suppress_metrics=True (the dashboard's escape hatch to
        # avoid polluting its own polling reads — Phase 3 #73 uses this).
        # FORMAL_EXTRACTION and EXPLORATORY are not in cycle 5's scope.
        if mode == FreshnessAnnotation.FORMAL_DRAFT and not suppress_metrics:
            latency_ms = int((time.perf_counter() - t_start) * 1000)
            await self._record_metric(
                view_name=view_name,
                mode=mode,
                speed_layer_hit=speed_layer_hit,
                speed_layer_rows_merged=speed_layer_rows_merged,
                row_count=len(final_result),
                latency_ms=latency_ms,
            )

        return final_result

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

    def get_last_batch_anchor_ts(self) -> Optional[datetime]:
        """Citation anchor for the last execute() call's batch state.

        Sprint 6.5 Phase 2A cycle 3 (#69). Populated from
        sqlonfhir.mv_refresh_metadata after each FORMAL_* mode execute().
        Returns None when no qualifying execute() has run, or when the
        touched views have no recorded refreshes yet (run
        `python scripts/materialize_views.py --refresh` to seed).

        Sibling getter pattern (matches get_last_executed_sql at line ~270)
        chosen for backward compatibility — existing HybridRunner callers
        get unchanged List[Dict] return shape. If a future sprint wires
        staleness-aware agent reasoning, revisit return shape (likely to
        ExecutionResult dataclass returned from execute() directly).
        """
        return self._last_batch_anchor_ts

    async def get_batch_anchor_ts_for_views(self, view_names: List[str]) -> Optional[datetime]:
        """MAX(refreshed_at) across the named views in mv_refresh_metadata.

        Sprint 6.5 Phase 2A cycle 6 (#69). Generalizes the single-view
        lookup behind get_last_batch_anchor_ts() to handle a list of view
        names. execute() always passes a single-element list today; Phase
        4's gate uses this method directly for FORMAL_EXTRACTION assertion;
        Sprint 6.5b (#71) will pass multiple view names when wiring
        feasibility_service's multi-view JOIN queries.

        Returns None when view_names is empty OR when none of the named
        views have any rows in mv_refresh_metadata (i.e., they've never
        been refreshed since Phase 1 introduced the metadata table).
        """
        if not view_names:
            return None
        return await self.db_client.execute_scalar(
            "SELECT MAX(refreshed_at) FROM sqlonfhir.mv_refresh_metadata "
            "WHERE view_name = ANY($1::text[])",
            [view_names],
        )

    async def create_hybrid_runner_metrics_table(self) -> None:
        """CREATE TABLE IF NOT EXISTS for sqlonfhir.hybrid_runner_metrics.

        Sprint 6.5 Phase 2A cycle 5 (#69). Named helper mirroring Phase 1's
        ViewMaterializer.create_metadata_table() at
        scripts/materialize_views.py:~75 — the table-creation SQL lives in
        a reviewable, idempotent function, never inlined into execute().

        Schema per issue #69's design block. Indexes target the dashboard's
        polling read pattern (time-series + group-by-mode).
        """
        if self._metrics_table_ensured:
            return
        if not self.db_client.pool:
            await self.db_client.connect()
        async with self.db_client.pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sqlonfhir.hybrid_runner_metrics (
                    id                       SERIAL PRIMARY KEY,
                    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    trace_id                 VARCHAR(64),
                    caller                   VARCHAR(64) NOT NULL DEFAULT 'direct',
                    mode                     VARCHAR(32) NOT NULL,
                    view_names               JSONB NOT NULL,
                    batch_anchor_ts          TIMESTAMPTZ NOT NULL,
                    speed_layer_hit          BOOLEAN NOT NULL,
                    speed_layer_rows_merged  INTEGER NOT NULL DEFAULT 0,
                    freshness_delta_seconds  INTEGER NOT NULL,
                    latency_ms               INTEGER NOT NULL,
                    row_count                INTEGER NOT NULL,
                    extra                    JSONB
                )
                """
            )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_hrm_created_at
                    ON sqlonfhir.hybrid_runner_metrics(created_at DESC)
                """
            )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_hrm_mode_created
                    ON sqlonfhir.hybrid_runner_metrics(mode, created_at DESC)
                """
            )
        self._metrics_table_ensured = True

    async def _record_metric(
        self,
        view_name: str,
        mode: "FreshnessAnnotation",
        speed_layer_hit: bool,
        speed_layer_rows_merged: int,
        row_count: int,
        latency_ms: int,
    ) -> None:
        """INSERT one row into sqlonfhir.hybrid_runner_metrics.

        Sprint 6.5 Phase 2A cycle 5 (#69). Private helper — execute()
        calls this. Best-effort: a failure here logs a warning but does
        not raise back into the caller (HybridRunner's contract is to
        return data; metric write failure must not break the read path).
        """
        import json
        from datetime import datetime, timezone

        await self.create_hybrid_runner_metrics_table()

        anchor = self._last_batch_anchor_ts
        if anchor is not None:
            now = datetime.now(anchor.tzinfo or timezone.utc)
            freshness_delta_seconds = int((now - anchor).total_seconds())
        else:
            freshness_delta_seconds = 0

        try:
            async with self.db_client.pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO sqlonfhir.hybrid_runner_metrics
                        (caller, mode, view_names, batch_anchor_ts,
                         speed_layer_hit, speed_layer_rows_merged,
                         freshness_delta_seconds, latency_ms, row_count)
                    VALUES ('direct', $1, $2::jsonb, $3, $4, $5, $6, $7, $8)
                    """,
                    mode.value,
                    json.dumps([view_name]),
                    anchor,
                    speed_layer_hit,
                    speed_layer_rows_merged,
                    freshness_delta_seconds,
                    latency_ms,
                    row_count,
                )
        except Exception as e:
            logger.warning(
                f"Failed to record hybrid_runner_metric for '{view_name}' "
                f"mode={mode.value}: {e}. Read path was unaffected."
            )

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
