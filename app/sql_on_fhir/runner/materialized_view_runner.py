"""
Materialized View Runner

Executes queries against pre-computed materialized views in the 'sqlonfhir' schema.

This is 10-100x faster than PostgresRunner because:
- No FHIRPath transpilation overhead
- No SQL generation overhead
- Views are pre-indexed and optimized
- Direct PostgreSQL query execution

Architecture:
1. Map ViewDefinition name to materialized view
2. Build WHERE clause from search_params
3. Execute SELECT against sqlonfhir.{view_name}
4. Return results (same interface as other runners)

Dual Column Architecture:
- Views with foreign keys store BOTH formats:
  * patient_ref: Full FHIR reference (e.g., "Patient/12345")
  * patient_id: Extracted ID (e.g., "12345")
- Use patient_id for JOINs (cleaner, faster)
- Use patient_ref when FHIR semantics are needed

Performance:
- PostgresRunner: 50-500ms (transpilation + generation + execution)
- MaterializedViewRunner: 5-10ms (direct query only)
"""

import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

from app.clients.hapi_db_client import HAPIDBClient

logger = logging.getLogger(__name__)


class MaterializedViewRunner:
    """
    Runner for querying pre-computed materialized views

    Executes fast queries against views in the 'sqlonfhir' schema,
    bypassing FHIRPath transpilation and SQL generation entirely.

    Implements same interface as PostgresRunner and InMemoryRunner
    for drop-in replacement.
    """

    SCHEMA_NAME = "sqlonfhir"

    # Mapping of common search params to column names
    # ViewDefinitions use different column naming conventions
    #
    # IMPORTANT: Dual Column Architecture
    # - Views store both FHIR reference (patient_ref="Patient/123")
    #   AND extracted ID (patient_id="123")
    # - Use patient_id for JOINs (faster, simpler)
    # - Use patient_ref when FHIR format is needed
    SEARCH_PARAM_MAPPINGS = {
        # Patient-related params
        "gender": "gender",
        "birthdate": "dob",
        "family": "name_family",
        "given": "name_given",

        # Common params across resources
        # Note: patient_id is the extracted ID from patient_ref
        "patient": "patient_id",
        "subject": "patient_id",  # Alias for patient
        "_id": "id",
        "code": "code",
        "status": "status",

        # Condition-specific
        "clinical-status": "clinical_status",

        # Observation-specific
        "date": "effective_date",
        "value-quantity": "value",
    }

    def __init__(self, db_client: HAPIDBClient):
        """
        Initialize materialized view runner

        Args:
            db_client: HAPI database client
        """
        self.db_client = db_client

        # Query execution statistics
        self._total_queries = 0
        self._total_execution_time_ms = 0.0

        # Store last executed SQL for debugging
        self._last_executed_sql: Optional[str] = None

        logger.info(f"Initialized MaterializedViewRunner (schema='{self.SCHEMA_NAME}')")

    async def execute(
        self,
        view_definition: Dict[str, Any],
        search_params: Optional[Dict[str, Any]] = None,
        max_resources: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Execute query against materialized view

        Args:
            view_definition: ViewDefinition resource
            search_params: Optional FHIR search parameters to filter results
            max_resources: Maximum number of rows to return (LIMIT clause)

        Returns:
            List of rows (each row is a dict with column values)

        Example:
            results = await runner.execute(
                view_def,
                search_params={"gender": "female"},
                max_resources=1000
            )
        """
        view_name = view_definition.get('name')
        resource_type = view_definition.get('resource')

        logger.info(f"Executing materialized view query: '{view_name}' (MaterializedViewRunner)")

        # Step 1: Check if materialized view exists
        view_exists = await self._check_view_exists(view_name)

        if not view_exists:
            raise ValueError(
                f"Materialized view '{self.SCHEMA_NAME}.{view_name}' does not exist. "
                f"Run 'python scripts/create_materialized_views.py' to create it."
            )

        # Step 2: Build SQL query
        sql = self._build_query(view_name, search_params, max_resources)

        logger.debug(f"Built SQL query: {len(sql)} characters")
        logger.debug(f"SQL:\n{sql}")

        # Step 3: Execute query
        start_time = datetime.now()
        self._last_executed_sql = sql

        try:
            rows = await self.db_client.execute_query(sql)

            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            self._total_queries += 1
            self._total_execution_time_ms += execution_time

            logger.info(
                f"✓ Materialized view '{view_name}' returned {len(rows)} rows "
                f"in {execution_time:.1f}ms (avg: {self._total_execution_time_ms / self._total_queries:.1f}ms)"
            )

            return rows

        except Exception as e:
            logger.error(f"Query execution failed for '{view_name}': {e}")
            logger.debug(f"Failed SQL:\n{sql}")
            raise RuntimeError(f"Materialized view query failed: {e}")

    async def execute_count(
        self,
        view_definition: Dict[str, Any],
        search_params: Optional[Dict[str, Any]] = None
    ) -> int:
        """
        Execute COUNT query against materialized view

        Args:
            view_definition: ViewDefinition resource
            search_params: Optional FHIR search parameters

        Returns:
            Count of matching rows
        """
        view_name = view_definition.get('name')

        logger.info(f"Executing COUNT query: '{view_name}' (MaterializedViewRunner)")

        # Check if view exists
        view_exists = await self._check_view_exists(view_name)

        if not view_exists:
            raise ValueError(
                f"Materialized view '{self.SCHEMA_NAME}.{view_name}' does not exist"
            )

        # Build COUNT query
        sql = self._build_count_query(view_name, search_params)

        try:
            result = await self.db_client.execute_query(sql)
            count = result[0]['count'] if result else 0

            logger.info(f"✓ COUNT query returned: {count:,} rows")
            return count

        except Exception as e:
            logger.error(f"COUNT query failed for '{view_name}': {e}")
            raise RuntimeError(f"COUNT query failed: {e}")

    def get_schema(self, view_definition: Dict[str, Any]) -> Dict[str, str]:
        """
        Extract column schema from ViewDefinition

        Args:
            view_definition: ViewDefinition resource

        Returns:
            Dictionary mapping column names to types

        Note: This is best-effort schema extraction from ViewDefinition.
              For accurate schema, query the materialized view metadata.
        """
        schema = {}

        # Extract select columns from ViewDefinition
        for select_item in view_definition.get('select', []):
            column_name = select_item.get('column')

            # Skip if column_name is None or not a string
            if not column_name or not isinstance(column_name, str):
                continue

            # Infer type from FHIRPath or use string as default
            column_type = "string"

            # Common type mappings
            if any(keyword in column_name.lower() for keyword in ['date', 'time']):
                column_type = "datetime"
            elif any(keyword in column_name.lower() for keyword in ['count', 'age']):
                column_type = "integer"
            elif any(keyword in column_name.lower() for keyword in ['value', 'score']):
                column_type = "float"

            schema[column_name] = column_type

        return schema

    def get_last_executed_sql(self) -> Optional[str]:
        """
        Get the last executed SQL query (for debugging)

        Returns:
            SQL query string or None
        """
        return self._last_executed_sql

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get runner statistics

        Returns:
            Dictionary with execution stats
        """
        avg_time = (
            self._total_execution_time_ms / self._total_queries
            if self._total_queries > 0
            else 0.0
        )

        return {
            "total_queries": self._total_queries,
            "total_execution_time_ms": self._total_execution_time_ms,
            "average_execution_time_ms": avg_time,
            "runner_type": "materialized"
        }

    # Private helper methods

    async def _check_view_exists(self, view_name: str) -> bool:
        """
        Check if materialized view exists

        Args:
            view_name: Name of the view

        Returns:
            True if view exists, False otherwise
        """
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
            return result[0]['exists'] if result else False
        except Exception as e:
            logger.warning(f"Failed to check view existence: {e}")
            return False

    def _build_query(
        self,
        view_name: str,
        search_params: Optional[Dict[str, Any]] = None,
        max_resources: Optional[int] = None
    ) -> str:
        """
        Build SQL SELECT query for materialized view

        Args:
            view_name: Name of the materialized view
            search_params: Filter parameters
            max_resources: Row limit

        Returns:
            SQL query string
        """
        # Base SELECT
        sql = f"SELECT * FROM {self.SCHEMA_NAME}.{view_name}"

        # Add WHERE clause from search_params
        where_clauses = self._build_where_clauses(search_params)

        if where_clauses:
            sql += "\nWHERE " + " AND ".join(where_clauses)

        # Add LIMIT clause
        if max_resources:
            sql += f"\nLIMIT {max_resources}"

        return sql

    def _build_count_query(
        self,
        view_name: str,
        search_params: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Build SQL COUNT query

        Args:
            view_name: Name of the materialized view
            search_params: Filter parameters

        Returns:
            SQL COUNT query string
        """
        # Base COUNT
        sql = f"SELECT COUNT(*) as count FROM {self.SCHEMA_NAME}.{view_name}"

        # Add WHERE clause
        where_clauses = self._build_where_clauses(search_params)

        if where_clauses:
            sql += "\nWHERE " + " AND ".join(where_clauses)

        return sql

    def _build_where_clauses(
        self,
        search_params: Optional[Dict[str, Any]] = None
    ) -> List[str]:
        """
        Build WHERE clause conditions from search parameters

        Args:
            search_params: Dictionary of search parameters

        Returns:
            List of WHERE clause strings
        """
        if not search_params:
            return []

        clauses = []

        for param_name, param_value in search_params.items():
            # Map FHIR search param to column name
            column_name = self.SEARCH_PARAM_MAPPINGS.get(param_name, param_name)

            # Build condition based on value type
            if isinstance(param_value, str):
                # String comparison (case-insensitive LIKE)
                clauses.append(f"{column_name} ILIKE '%{param_value}%'")

            elif isinstance(param_value, (int, float)):
                # Numeric comparison
                clauses.append(f"{column_name} = {param_value}")

            elif isinstance(param_value, list):
                # IN clause for multiple values
                if all(isinstance(v, str) for v in param_value):
                    values_str = "', '".join(param_value)
                    clauses.append(f"{column_name} IN ('{values_str}')")
                else:
                    values_str = ", ".join(str(v) for v in param_value)
                    clauses.append(f"{column_name} IN ({values_str})")

            elif isinstance(param_value, dict):
                # Handle complex parameters (e.g., date ranges)
                if 'start' in param_value or 'end' in param_value:
                    if 'start' in param_value:
                        clauses.append(f"{column_name} >= '{param_value['start']}'")
                    if 'end' in param_value:
                        clauses.append(f"{column_name} <= '{param_value['end']}'")

        return clauses
