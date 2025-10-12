"""
HAPI FHIR Database Client

Direct PostgreSQL connection to HAPI FHIR's database for executing
SQL-on-FHIR ViewDefinitions at database level (10-100x faster than REST API).

HAPI FHIR stores resources in PostgreSQL with the following schema:
- hfj_resource: Main resource metadata table (res_id, res_type, res_ver, fhir_id)
- hfj_res_ver: Resource version content table (pid, res_text_vc with JSON content)
- JOIN: hfj_resource.res_ver = hfj_res_ver.pid
- Search param indexes: hfj_spidx_string, hfj_spidx_date, hfj_spidx_token, etc.
"""

import logging
import asyncpg
import os
import json
from typing import List, Dict, Any, Optional
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)


class HAPIDBClient:
    """
    Async PostgreSQL client for HAPI FHIR database

    Features:
    - Connection pooling for performance
    - Async query execution
    - Transaction support
    - Query timeout protection
    """

    def __init__(
        self,
        connection_url: Optional[str] = None,
        min_pool_size: int = 5,
        max_pool_size: int = 20,
        command_timeout: float = 30.0
    ):
        """
        Initialize HAPI DB client

        Args:
            connection_url: PostgreSQL connection URL (default from env HAPI_DB_URL)
            min_pool_size: Minimum connections in pool
            max_pool_size: Maximum connections in pool
            command_timeout: Query timeout in seconds
        """
        self.connection_url = connection_url or os.getenv(
            'HAPI_DB_URL',
            'postgresql://hapi:hapi@localhost:5433/hapi'
        )
        self.min_pool_size = min_pool_size
        self.max_pool_size = max_pool_size
        self.command_timeout = command_timeout
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        """Establish connection pool"""
        if self.pool is None:
            try:
                self.pool = await asyncpg.create_pool(
                    self.connection_url,
                    min_size=self.min_pool_size,
                    max_size=self.max_pool_size,
                    command_timeout=self.command_timeout
                )
                logger.info(
                    f"Connected to HAPI database "
                    f"(pool: {self.min_pool_size}-{self.max_pool_size} connections)"
                )
            except Exception as e:
                logger.error(f"Failed to connect to HAPI database: {e}")
                raise

    async def close(self):
        """Close connection pool"""
        if self.pool:
            await self.pool.close()
            self.pool = None
            logger.info("Closed HAPI database connection pool")

    async def test_connection(self) -> bool:
        """
        Test database connectivity

        Returns:
            True if connected and can query, False otherwise
        """
        try:
            if not self.pool:
                await self.connect()

            async with self.pool.acquire() as conn:
                result = await conn.fetchval('SELECT 1')
                return result == 1
        except Exception as e:
            logger.error(f"Connection test failed: {e}")
            return False

    async def execute_query(
        self,
        sql: str,
        params: Optional[List] = None,
        timeout: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """
        Execute SELECT query and return results as list of dicts

        Args:
            sql: SQL query string
            params: Query parameters for prepared statement
            timeout: Override default command timeout

        Returns:
            List of rows as dictionaries
        """
        if not self.pool:
            await self.connect()

        try:
            async with self.pool.acquire() as conn:
                # Set timeout for this query if specified
                if timeout:
                    await conn.execute(f'SET statement_timeout = {int(timeout * 1000)}')

                # Execute query
                if params:
                    rows = await conn.fetch(sql, *params)
                else:
                    rows = await conn.fetch(sql)

                # Convert to list of dicts
                return [dict(row) for row in rows]

        except asyncpg.QueryCanceledError:
            logger.error(f"Query timed out after {timeout or self.command_timeout}s: {sql[:100]}...")
            raise TimeoutError(f"Query execution exceeded {timeout or self.command_timeout} seconds")
        except Exception as e:
            logger.error(f"Query execution failed: {e}\nSQL: {sql[:200]}...")
            raise

    async def execute_scalar(
        self,
        sql: str,
        params: Optional[List] = None
    ) -> Any:
        """
        Execute query and return single scalar value

        Args:
            sql: SQL query string
            params: Query parameters

        Returns:
            Single value from first row, first column
        """
        if not self.pool:
            await self.connect()

        async with self.pool.acquire() as conn:
            if params:
                return await conn.fetchval(sql, *params)
            else:
                return await conn.fetchval(sql)

    async def explain_query(self, sql: str, analyze: bool = False) -> str:
        """
        Get query execution plan for optimization

        Args:
            sql: SQL query to explain
            analyze: If True, actually execute query and return timings

        Returns:
            EXPLAIN output as string
        """
        if not self.pool:
            await self.connect()

        explain_sql = f"EXPLAIN {'ANALYZE ' if analyze else ''}{sql}"

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(explain_sql)
            return '\n'.join([row['QUERY PLAN'] for row in rows])

    @asynccontextmanager
    async def transaction(self):
        """
        Transaction context manager

        Usage:
            async with client.transaction():
                await client.execute_query("INSERT ...")
                await client.execute_query("UPDATE ...")
                # Commits on exit, rolls back on exception
        """
        if not self.pool:
            await self.connect()

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                yield conn

    async def get_resource_count(self, resource_type: str) -> int:
        """
        Get count of resources by type

        Args:
            resource_type: FHIR resource type (e.g., "Patient", "Observation")

        Returns:
            Count of resources
        """
        sql = """
            SELECT COUNT(*)
            FROM hfj_resource
            WHERE res_type = $1
              AND res_deleted_at IS NULL
        """
        return await self.execute_scalar(sql, [resource_type])

    async def get_available_resource_types(self) -> List[str]:
        """
        Get list of all resource types in database

        Returns:
            List of resource type names
        """
        sql = """
            SELECT DISTINCT res_type
            FROM hfj_resource
            WHERE res_deleted_at IS NULL
            ORDER BY res_type
        """
        rows = await self.execute_query(sql)
        return [row['res_type'] for row in rows]

    async def get_resource_by_id(
        self,
        resource_type: str,
        resource_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch single resource by ID

        Args:
            resource_type: FHIR resource type
            resource_id: Resource ID (numeric res_id or FHIR logical ID)

        Returns:
            Resource as dict, or None if not found
        """
        sql = """
            SELECT v.res_text_vc AS resource
            FROM hfj_resource r
            JOIN hfj_res_ver v ON r.res_ver = v.pid
            WHERE r.res_type = $1
              AND r.res_id = $2
              AND r.res_deleted_at IS NULL
            LIMIT 1
        """
        rows = await self.execute_query(sql, [resource_type, resource_id])

        if rows:
            resource_text = rows[0]['resource']
            # Parse JSON string to dict if needed
            if isinstance(resource_text, str):
                return json.loads(resource_text)
            return resource_text
        return None

    async def get_database_stats(self) -> Dict[str, Any]:
        """
        Get database statistics for monitoring

        Returns:
            Dict with resource counts, table sizes, etc.
        """
        stats = {}

        # Resource counts by type
        sql = """
            SELECT res_type, COUNT(*) as count
            FROM hfj_resource
            WHERE res_deleted_at IS NULL
            GROUP BY res_type
            ORDER BY count DESC
            LIMIT 10
        """
        resource_counts = await self.execute_query(sql)
        stats['resource_counts'] = {
            row['res_type']: row['count']
            for row in resource_counts
        }

        # Total resources
        stats['total_resources'] = await self.execute_scalar(
            "SELECT COUNT(*) FROM hfj_resource WHERE res_deleted_at IS NULL"
        )

        # Database size
        stats['database_size_mb'] = await self.execute_scalar(
            "SELECT pg_database_size(current_database()) / 1024 / 1024"
        )

        # Connection pool stats
        if self.pool:
            stats['pool_size'] = self.pool.get_size()
            stats['pool_free_connections'] = self.pool.get_idle_size()

        return stats


# Singleton instance factory
_hapi_db_client: Optional[HAPIDBClient] = None


async def create_hapi_db_client() -> HAPIDBClient:
    """
    Create or return singleton HAPI DB client instance

    Returns:
        Configured HAPIDBClient with connection pool
    """
    global _hapi_db_client

    if _hapi_db_client is None:
        _hapi_db_client = HAPIDBClient()
        await _hapi_db_client.connect()

    return _hapi_db_client


async def close_hapi_db_client():
    """Close singleton client if exists"""
    global _hapi_db_client

    if _hapi_db_client:
        await _hapi_db_client.close()
        _hapi_db_client = None
