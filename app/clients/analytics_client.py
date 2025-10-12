"""
Analytics API Client

Wrapper for the SQL-on-FHIR v2 Analytics API
"""

import httpx
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class QueryResult:
    """Result from ViewDefinition execution"""
    view_name: str
    resource_type: str
    row_count: int
    rows: List[Dict[str, Any]]
    schema: Dict[str, str]
    execution_time_ms: float = 0.0


class AnalyticsClient:
    """
    Client for interacting with ResearchFlow Analytics API

    Provides methods for executing ViewDefinitions and retrieving results.
    """

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.analytics_url = f"{base_url}/analytics"
        self.client = httpx.AsyncClient(timeout=30.0)

    async def close(self):
        """Close HTTP client"""
        await self.client.aclose()

    async def health_check(self) -> bool:
        """Check if Analytics API is healthy"""
        try:
            response = await self.client.get(f"{self.analytics_url}/health")
            response.raise_for_status()
            data = response.json()
            return data.get("status") == "healthy"
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False

    async def list_view_definitions(self) -> List[Dict[str, str]]:
        """List all available ViewDefinitions"""
        try:
            response = await self.client.get(f"{self.analytics_url}/view-definitions")
            response.raise_for_status()
            data = response.json()
            return data.get("view_definitions", [])
        except Exception as e:
            logger.error(f"Failed to list ViewDefinitions: {e}")
            return []

    async def execute_view_definition(
        self,
        view_name: str,
        search_params: Optional[Dict[str, Any]] = None,
        max_resources: Optional[int] = None
    ) -> QueryResult:
        """
        Execute a ViewDefinition

        Args:
            view_name: Name of ViewDefinition to execute
            search_params: FHIR search parameters for filtering
            max_resources: Maximum resources to process

        Returns:
            QueryResult with rows and metadata
        """
        import time
        start_time = time.time()

        try:
            payload = {
                "view_name": view_name,
                "search_params": search_params or {},
                "max_resources": max_resources
            }

            response = await self.client.post(
                f"{self.analytics_url}/execute",
                json=payload
            )
            response.raise_for_status()
            data = response.json()

            execution_time = (time.time() - start_time) * 1000  # Convert to ms

            return QueryResult(
                view_name=data.get("view_name"),
                resource_type=data.get("resource_type"),
                row_count=data.get("row_count", 0),
                rows=data.get("rows", []),
                schema=data.get("column_schema", {}),
                execution_time_ms=execution_time
            )

        except Exception as e:
            logger.error(f"Failed to execute ViewDefinition '{view_name}': {e}")
            raise

    async def execute_multiple_view_definitions(
        self,
        view_names: List[str],
        search_params: Optional[Dict[str, Any]] = None,
        max_resources: Optional[int] = None
    ) -> Dict[str, QueryResult]:
        """
        Execute multiple ViewDefinitions

        Args:
            view_names: List of ViewDefinition names
            search_params: Common search parameters
            max_resources: Maximum resources per ViewDefinition

        Returns:
            Dict mapping view_name to QueryResult
        """
        results = {}

        for view_name in view_names:
            try:
                result = await self.execute_view_definition(
                    view_name=view_name,
                    search_params=search_params,
                    max_resources=max_resources
                )
                results[view_name] = result
            except Exception as e:
                logger.error(f"Failed to execute {view_name}: {e}")
                # Continue with other ViewDefinitions
                continue

        return results

    async def join_results(
        self,
        primary_result: QueryResult,
        secondary_result: QueryResult,
        join_key: str = "patient_id"
    ) -> List[Dict[str, Any]]:
        """
        Join two query results on a common key

        Args:
            primary_result: Primary result set
            secondary_result: Secondary result set to join
            join_key: Key to join on (default: patient_id)

        Returns:
            List of joined rows
        """
        # Create index on secondary result
        secondary_index = {}
        for row in secondary_result.rows:
            key_value = row.get(join_key)
            if key_value:
                if key_value not in secondary_index:
                    secondary_index[key_value] = []
                secondary_index[key_value].append(row)

        # Join
        joined_rows = []
        for primary_row in primary_result.rows:
            key_value = primary_row.get(join_key) or primary_row.get("id")
            if key_value in secondary_index:
                # Multiple matches - create multiple joined rows
                for secondary_row in secondary_index[key_value]:
                    joined_row = {**primary_row, **secondary_row}
                    joined_rows.append(joined_row)
            else:
                # No match - include primary row only
                joined_rows.append(primary_row)

        return joined_rows

    async def filter_rows(
        self,
        rows: List[Dict[str, Any]],
        filters: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Apply post-filters to result rows

        Args:
            rows: Result rows
            filters: List of filter conditions
                     Each filter: {"field": str, "value": Any, "operator": "eq|ne|gt|lt|contains"}

        Returns:
            Filtered rows
        """
        filtered = rows

        for filter_spec in filters:
            field = filter_spec.get("field")
            value = filter_spec.get("value")
            operator = filter_spec.get("operator", "eq")

            filtered = [
                row for row in filtered
                if self._matches_filter(row, field, value, operator)
            ]

        return filtered

    def _matches_filter(
        self,
        row: Dict[str, Any],
        field: str,
        value: Any,
        operator: str
    ) -> bool:
        """Check if row matches filter condition"""
        row_value = row.get(field)

        if row_value is None:
            return False

        if operator == "eq":
            return row_value == value
        elif operator == "ne":
            return row_value != value
        elif operator == "gt":
            return row_value > value
        elif operator == "lt":
            return row_value < value
        elif operator == "contains":
            return value.lower() in str(row_value).lower()
        else:
            return False
