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
import re
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from langsmith import traceable

from app.clients.hapi_db_client import HAPIDBClient
from app.schemas._errors import log_internal_error
from app.sql_on_fhir.errors import UnsupportedSearchParamError

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
        # Patient-related params (column names match the patient_demographics
        # ViewDefinition: see app/sql_on_fhir/view_definitions/patient_demographics.json)
        "gender": "gender",
        "birthdate": "birth_date",
        "family": "family_name",
        "given": "given_name",
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

    # Coded values and ids: a substring match is wrong ('%male%' matches
    # 'female', '%active%' matches 'inactive', '%12%' matches '312').
    EXACT_MATCH_PARAMS = {
        "gender",
        "clinical-status",
        "status",
        "code",
        "patient",
        "subject",
        "_id",
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
        max_resources: Optional[int] = None,
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
        view_name = view_definition.get("name")
        resource_type = view_definition.get("resource")

        logger.info(f"Executing materialized view query: '{view_name}' (MaterializedViewRunner)")

        # Step 1: Check if materialized view exists
        view_exists = await self._check_view_exists(view_name)

        if not view_exists:
            raise ValueError(
                f"Materialized view '{self.SCHEMA_NAME}.{view_name}' does not exist. "
                f"Run 'python scripts/create_materialized_views.py' to create it."
            )

        # Step 2: Build SQL query
        sql, params = self._build_query(view_name, search_params, max_resources)

        logger.debug(f"Built SQL query: {len(sql)} characters")
        logger.debug(f"SQL:\n{sql}")

        # Step 3: Execute query
        start_time = datetime.now()
        self._last_executed_sql = sql

        try:
            rows = await self.db_client.execute_query(sql, params)

            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            self._total_queries += 1
            self._total_execution_time_ms += execution_time

            logger.info(
                f"✓ Materialized view '{view_name}' returned {len(rows)} rows "
                f"in {execution_time:.1f}ms (avg: {self._total_execution_time_ms / self._total_queries:.1f}ms)"
            )

            return rows

        except Exception as e:
            log_internal_error(logger, f"Query execution failed for '{view_name}'", e)
            logger.debug(f"Failed SQL:\n{sql}")
            raise RuntimeError("Materialized view query failed") from e

    @traceable(tags=["materialized-view-runner", "count"])
    async def execute_count(
        self, view_definition: Dict[str, Any], search_params: Optional[Dict[str, Any]] = None
    ) -> int:
        """
        Execute COUNT query against materialized view

        Args:
            view_definition: ViewDefinition resource
            search_params: Optional FHIR search parameters

        Returns:
            Count of matching rows
        """
        view_name = view_definition.get("name")

        logger.info(f"Executing COUNT query: '{view_name}' (MaterializedViewRunner)")

        # Check if view exists
        view_exists = await self._check_view_exists(view_name)

        if not view_exists:
            raise ValueError(f"Materialized view '{self.SCHEMA_NAME}.{view_name}' does not exist")

        # Build COUNT query
        sql, params = self._build_count_query(view_name, search_params)

        try:
            result = await self.db_client.execute_query(sql, params)
            count = result[0]["count"] if result else 0

            logger.info(f"✓ COUNT query returned: {count:,} rows")
            return count

        except Exception as e:
            log_internal_error(logger, f"COUNT query failed for '{view_name}'", e)
            raise RuntimeError("COUNT query failed") from e

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

        # Bug 9 fix (issue #13): SQL-on-FHIR v2 spec defines `column` as an ARRAY
        # of {name, path, ...} objects, not a string. The previous code's
        # `isinstance(column_name, str)` check was always False, so this method
        # returned {} for every view def. Production callsites at
        # app/api/analytics.py:294 + :511 silently consumed the empty schema.
        # Iterate the column array correctly and walk every select block
        # (top-level + forEach), mirroring how column_extractor.py parses view defs.
        for select_item in view_definition.get("select", []):
            for col_def in select_item.get("column", []):
                column_name = col_def.get("name")
                if not column_name:
                    continue

                # Best-effort type inference from the column name. Unchanged from
                # the prior implementation — the only observable bug was the
                # always-empty result.
                column_type = "string"
                if any(kw in column_name.lower() for kw in ["date", "time"]):
                    column_type = "datetime"
                elif any(kw in column_name.lower() for kw in ["count", "age"]):
                    column_type = "integer"
                elif any(kw in column_name.lower() for kw in ["value", "score"]):
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
            self._total_execution_time_ms / self._total_queries if self._total_queries > 0 else 0.0
        )

        return {
            "total_queries": self._total_queries,
            "total_execution_time_ms": self._total_execution_time_ms,
            "average_execution_time_ms": avg_time,
            "runner_type": "materialized",
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
            return result[0]["exists"] if result else False
        except Exception as e:
            log_internal_error(logger, "Failed to check view existence", e, level=logging.WARNING)
            return False

    def _build_query(
        self,
        view_name: str,
        search_params: Optional[Dict[str, Any]] = None,
        max_resources: Optional[int] = None,
    ) -> Tuple[str, List[Any]]:
        """
        Build SQL SELECT query for materialized view

        Args:
            view_name: Name of the materialized view
            search_params: Filter parameters
            max_resources: Row limit

        Returns:
            SQL query string and its bound parameters
        """
        # Base SELECT
        sql = f"SELECT * FROM {self.SCHEMA_NAME}.{view_name}"

        # Add WHERE clause from search_params
        where_clauses, params = self._build_where_clauses(search_params)

        if where_clauses:
            sql += "\nWHERE " + " AND ".join(where_clauses)

        # Add LIMIT clause
        if max_resources:
            params.append(int(max_resources))
            sql += f"\nLIMIT ${len(params)}"

        return sql, params

    def _build_count_query(
        self, view_name: str, search_params: Optional[Dict[str, Any]] = None
    ) -> Tuple[str, List[Any]]:
        """
        Build SQL COUNT query

        Args:
            view_name: Name of the materialized view
            search_params: Filter parameters

        Returns:
            SQL COUNT query string and its bound parameters
        """
        # Base COUNT
        sql = f"SELECT COUNT(*) as count FROM {self.SCHEMA_NAME}.{view_name}"

        # Add WHERE clause
        where_clauses, params = self._build_where_clauses(search_params)

        if where_clauses:
            sql += "\nWHERE " + " AND ".join(where_clauses)

        return sql, params

    def _build_where_clauses(
        self, search_params: Optional[Dict[str, Any]] = None
    ) -> Tuple[List[str], List[Any]]:
        """
        Build WHERE clause conditions from search parameters

        Values are bound as $n parameters, never pasted into the SQL text.
        Every mapped column is text, so values bind as strings.

        Args:
            search_params: Dictionary of search parameters

        Returns:
            List of WHERE clause strings and their bound parameters

        Raises:
            UnsupportedSearchParamError: for a key outside SEARCH_PARAM_MAPPINGS
        """
        clauses: List[str] = []
        params: List[Any] = []
        if not search_params:
            return clauses, params

        def bind(value: Any) -> str:
            params.append(value)
            return f"${len(params)}"

        for param_name, param_value in search_params.items():
            if param_name not in self.SEARCH_PARAM_MAPPINGS:
                raise UnsupportedSearchParamError(param_name)
            column = f"{self.SEARCH_PARAM_MAPPINGS[param_name]}::text"
            exact = param_name in self.EXACT_MATCH_PARAMS

            if isinstance(param_value, str) and exact:
                clauses.append(f"LOWER({column}) = LOWER({bind(param_value)})")

            elif isinstance(param_value, str):
                pattern = "%" + re.sub(r"([\\%_])", r"\\\1", param_value) + "%"
                clauses.append(f"{column} ILIKE {bind(pattern)}")

            elif isinstance(param_value, (int, float)) and not isinstance(param_value, bool):
                clauses.append(f"{column} = {bind(str(param_value))}")

            elif isinstance(param_value, list):
                values = [str(v) for v in param_value]
                if exact:
                    values = [v.lower() for v in values]
                    clauses.append(f"LOWER({column}) = ANY({bind(values)}::text[])")
                else:
                    clauses.append(f"{column} = ANY({bind(values)}::text[])")

            elif isinstance(param_value, dict):
                # Date ranges; the mapped date columns hold ISO-8601 text.
                bounds = {"start", "end"}
                if (
                    not param_value
                    or param_value.keys() - bounds
                    or any(v is None for v in param_value.values())
                ):
                    # Anything else would silently drop or garble part of the filter.
                    raise UnsupportedSearchParamError(param_name)
                if "start" in param_value:
                    clauses.append(f"{column} >= {bind(str(param_value['start']))}")
                if "end" in param_value:
                    clauses.append(f"{column} <= {bind(str(param_value['end']))}")

            else:
                raise UnsupportedSearchParamError(param_name)

        return clauses, params
