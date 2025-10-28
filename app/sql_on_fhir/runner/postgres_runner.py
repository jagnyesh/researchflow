"""
PostgreSQL ViewDefinition Runner

Executes SQL-on-FHIR v2 ViewDefinitions directly in PostgreSQL database.

This is 10-100x faster than the in-memory runner because:
- No network overhead (queries run in-database)
- PostgreSQL optimizer handles joins and aggregations
- JSONB indexing for fast field access
- Parallel query execution by database

Architecture:
1. Transpile FHIRPath expressions to PostgreSQL JSONB queries
2. Build complete SQL SELECT statement
3. Execute against HAPI FHIR database
4. Return results as list of dicts (same interface as InMemoryRunner)
"""

import logging
import hashlib
import json
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

from app.clients.hapi_db_client import HAPIDBClient
from app.sql_on_fhir.transpiler import (
    create_fhirpath_transpiler,
    create_column_extractor
)
from app.sql_on_fhir.query_builder import create_sql_query_builder

logger = logging.getLogger(__name__)


class PostgresRunner:
    """
    PostgreSQL-based runner for SQL-on-FHIR v2 ViewDefinitions

    Executes ViewDefinitions as native PostgreSQL queries against
    HAPI FHIR database for 10-100x performance improvement.

    Implements same interface as InMemoryRunner for drop-in replacement.
    """

    def __init__(
        self,
        db_client: HAPIDBClient,
        enable_cache: bool = True,
        cache_ttl_seconds: int = 300
    ):
        """
        Initialize PostgreSQL runner

        Args:
            db_client: HAPI database client
            enable_cache: Enable query result caching (default: True)
            cache_ttl_seconds: Cache TTL in seconds (default: 300 = 5 minutes)
        """
        self.db_client = db_client
        self.enable_cache = enable_cache
        self.cache_ttl_seconds = cache_ttl_seconds

        # Initialize SQL generation components
        self.transpiler = create_fhirpath_transpiler()
        self.extractor = create_column_extractor(self.transpiler)
        self.builder = create_sql_query_builder(self.transpiler, self.extractor)

        # Simple in-memory cache
        self._cache: Dict[str, Tuple[datetime, List[Dict[str, Any]]]] = {}

        # Cache statistics
        self._cache_hits = 0
        self._cache_misses = 0

        # Query execution statistics
        self._total_queries = 0
        self._total_execution_time_ms = 0.0

        # Store last executed SQL for retrieval
        self._last_executed_sql: Optional[str] = None

        logger.info(
            f"Initialized PostgresRunner "
            f"(cache={'enabled' if enable_cache else 'disabled'}, TTL={cache_ttl_seconds}s)"
        )

    async def execute(
        self,
        view_definition: Dict[str, Any],
        search_params: Optional[Dict[str, Any]] = None,
        max_resources: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Execute a ViewDefinition and return tabular results

        Args:
            view_definition: ViewDefinition resource
            search_params: Optional FHIR search parameters to filter resources
            max_resources: Maximum number of resources to process

        Returns:
            List of rows (each row is a dict with column values)

        Example:
            results = await runner.execute(
                view_def,
                search_params={"gender": "female"},
                max_resources=1000
            )
        """
        resource_type = view_definition.get('resource')
        view_name = view_definition.get('name')

        # Step 0: Check cache
        if self.enable_cache:
            cache_key = self._generate_cache_key(view_definition, search_params, max_resources)
            cached_result = self._get_from_cache(cache_key)

            if cached_result is not None:
                self._cache_hits += 1
                logger.info(
                    f"✓ Cache HIT for '{view_name}' ({len(cached_result)} rows) "
                    f"[hits: {self._cache_hits}, misses: {self._cache_misses}]"
                )
                return cached_result

            self._cache_misses += 1
            logger.debug(
                f"Cache MISS for '{view_name}' "
                f"[hits: {self._cache_hits}, misses: {self._cache_misses}]"
            )

        logger.info(f"Executing ViewDefinition '{view_name}' for {resource_type} (PostgreSQL)")

        # Step 1: Build SQL query
        try:
            query = self.builder.build_query(
                view_definition,
                search_params=search_params,
                limit=max_resources
            )

            logger.debug(f"Built SQL query: {len(query.sql)} characters, {query.column_count} columns")
            logger.debug(f"Generated SQL:\n{query.sql}")

        except Exception as e:
            logger.error(f"Failed to build SQL query for '{view_name}': {e}")
            raise ValueError(f"SQL generation failed: {e}")

        # Step 2: Execute SQL query
        start_time = datetime.now()

        # Store SQL for retrieval
        self._last_executed_sql = query.sql

        try:
            rows = await self.db_client.execute_query(query.sql)

            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            self._total_queries += 1
            self._total_execution_time_ms += execution_time

            logger.info(
                f"✓ ViewDefinition '{view_name}' produced {len(rows)} rows "
                f"in {execution_time:.1f}ms (PostgreSQL)"
            )

        except Exception as e:
            logger.error(f"SQL execution failed for '{view_name}': {e}")
            logger.debug(f"Failed SQL:\n{query.sql}")
            raise RuntimeError(f"Query execution failed: {e}")

        # Step 3: Store in cache
        if self.enable_cache:
            self._put_in_cache(cache_key, rows)

        return rows

    async def execute_count(
        self,
        view_definition: Dict[str, Any],
        search_params: Optional[Dict[str, Any]] = None
    ) -> int:
        """
        Execute COUNT query for feasibility checks

        Args:
            view_definition: ViewDefinition resource
            search_params: Optional FHIR search parameters

        Returns:
            Count of matching resources
        """
        view_name = view_definition.get('name')

        logger.info(f"Executing COUNT query for '{view_name}'")

        # Build COUNT query
        try:
            count_sql = self.builder.build_count_query(view_definition, search_params)
        except Exception as e:
            logger.error(f"Failed to build COUNT query for '{view_name}': {e}")
            raise ValueError(f"COUNT query generation failed: {e}")

        # Execute
        start_time = datetime.now()

        try:
            rows = await self.db_client.execute_query(count_sql)
            count = rows[0]['count']

            execution_time = (datetime.now() - start_time).total_seconds() * 1000

            logger.info(f"✓ COUNT query for '{view_name}': {count} resources in {execution_time:.1f}ms")

            return count

        except Exception as e:
            logger.error(f"COUNT query execution failed for '{view_name}': {e}")
            raise RuntimeError(f"COUNT query failed: {e}")

    def get_schema(self, view_definition: Dict[str, Any]) -> Dict[str, str]:
        """
        Extract column schema from ViewDefinition

        Args:
            view_definition: ViewDefinition resource

        Returns:
            Dict mapping column names to types
        """
        schema = {}

        select_elements = view_definition.get('select', [])

        for select_elem in select_elements:
            self._extract_schema_from_select(select_elem, schema)

        return schema

    def _extract_schema_from_select(
        self,
        select_elem: Dict[str, Any],
        schema: Dict[str, str]
    ):
        """
        Recursively extract schema from select element

        Args:
            select_elem: Select element
            schema: Schema dict to populate
        """
        if 'column' in select_elem:
            for column in select_elem['column']:
                name = column.get('name')
                col_type = column.get('type', 'string')  # Default to string

                if name:
                    schema[name] = col_type

        # Handle nested selects
        if 'select' in select_elem:
            for nested in select_elem['select']:
                self._extract_schema_from_select(nested, schema)

        # Handle forEach/forEachOrNull
        if 'forEach' in select_elem or 'forEachOrNull' in select_elem:
            # Schema is same, just extracted from forEach context
            pass

        # Handle unionAll
        if 'unionAll' in select_elem:
            for union_select in select_elem['unionAll']:
                self._extract_schema_from_select(union_select, schema)

    # ========================================================================
    # Cache Management Methods
    # ========================================================================

    def _generate_cache_key(
        self,
        view_definition: Dict[str, Any],
        search_params: Optional[Dict[str, Any]],
        max_resources: Optional[int]
    ) -> str:
        """
        Generate cache key from query parameters

        Args:
            view_definition: ViewDefinition resource
            search_params: Search parameters
            max_resources: Max resources limit

        Returns:
            Cache key (MD5 hash)
        """
        key_components = {
            'runner': 'postgres',  # Distinguish from in-memory cache
            'view_name': view_definition.get('name'),
            'resource_type': view_definition.get('resource'),
            'search_params': search_params or {},
            'max_resources': max_resources,
            'where_clauses': view_definition.get('where', []),
            'select_hash': hashlib.md5(
                json.dumps(view_definition.get('select', []), sort_keys=True).encode()
            ).hexdigest()
        }

        key_string = json.dumps(key_components, sort_keys=True)
        cache_key = hashlib.md5(key_string.encode()).hexdigest()

        return cache_key

    def _get_from_cache(self, cache_key: str) -> Optional[List[Dict[str, Any]]]:
        """
        Retrieve results from cache

        Args:
            cache_key: Cache key

        Returns:
            Cached results or None if not found/expired
        """
        if cache_key not in self._cache:
            return None

        timestamp, results = self._cache[cache_key]

        # Check if expired
        age = (datetime.now() - timestamp).total_seconds()
        if age > self.cache_ttl_seconds:
            # Expired - remove from cache
            del self._cache[cache_key]
            logger.debug(f"Cache entry expired (age: {age:.1f}s > TTL: {self.cache_ttl_seconds}s)")
            return None

        return results

    def _put_in_cache(self, cache_key: str, results: List[Dict[str, Any]]):
        """
        Store results in cache

        Args:
            cache_key: Cache key
            results: Query results to cache
        """
        self._cache[cache_key] = (datetime.now(), results)
        logger.debug(f"Cached {len(results)} rows (cache size: {len(self._cache)} entries)")

    def clear_cache(self):
        """Clear all cached results"""
        cache_size = len(self._cache)
        self._cache.clear()
        self._cache_hits = 0
        self._cache_misses = 0
        logger.info(f"Cache cleared ({cache_size} entries removed)")

    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics

        Returns:
            Dict with cache metrics
        """
        total_requests = self._cache_hits + self._cache_misses
        hit_rate = (self._cache_hits / total_requests * 100) if total_requests > 0 else 0

        return {
            'runner_type': 'postgres',
            'enabled': self.enable_cache,
            'ttl_seconds': self.cache_ttl_seconds,
            'cache_size': len(self._cache),
            'cache_hits': self._cache_hits,
            'cache_misses': self._cache_misses,
            'total_requests': total_requests,
            'hit_rate_percent': round(hit_rate, 2)
        }

    def get_execution_stats(self) -> Dict[str, Any]:
        """
        Get query execution statistics

        Returns:
            Dict with execution metrics
        """
        avg_time = (
            self._total_execution_time_ms / self._total_queries
            if self._total_queries > 0 else 0
        )

        return {
            'runner_type': 'postgres',
            'total_queries': self._total_queries,
            'total_execution_time_ms': round(self._total_execution_time_ms, 2),
            'average_execution_time_ms': round(avg_time, 2)
        }

    def get_last_executed_sql(self) -> Optional[str]:
        """
        Get the last executed SQL query

        Returns:
            Last executed SQL string, or None if no queries executed yet
        """
        return self._last_executed_sql


async def create_postgres_runner(
    db_client: HAPIDBClient,
    enable_cache: bool = True,
    cache_ttl_seconds: int = 300
) -> PostgresRunner:
    """
    Factory function to create PostgreSQL runner

    Args:
        db_client: HAPI database client
        enable_cache: Enable query caching
        cache_ttl_seconds: Cache TTL

    Returns:
        Configured PostgresRunner
    """
    return PostgresRunner(db_client, enable_cache, cache_ttl_seconds)
