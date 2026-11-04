"""
SQL Query Builder

Assembles complete PostgreSQL queries from SQL-on-FHIR ViewDefinitions.

Combines:
- Column extraction (SELECT clause)
- HAPI schema knowledge (FROM clause with JOIN)
- Search parameter filtering (WHERE clause)
- FHIR search params (additional filtering)
"""

import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field

from app.sql_on_fhir.errors import UnsupportedSearchParamError
from app.sql_on_fhir.transpiler import FHIRPathTranspiler, ColumnExtractor

logger = logging.getLogger(__name__)


@dataclass
class SQLQuery:
    """Complete SQL query with metadata"""

    sql: str
    resource_type: str
    view_name: str
    column_count: int
    has_lateral_joins: bool
    has_where_clause: bool
    params: List[Any] = field(default_factory=list)


class SQLQueryBuilder:
    """
    Builds complete SQL queries from ViewDefinitions

    Generates executable PostgreSQL queries against HAPI FHIR database
    """

    def __init__(self, transpiler: FHIRPathTranspiler, extractor: ColumnExtractor):
        """
        Initialize SQL query builder

        Args:
            transpiler: FHIRPath transpiler
            extractor: Column extractor
        """
        self.transpiler = transpiler
        self.extractor = extractor

    def build_query(
        self,
        view_definition: Dict[str, Any],
        search_params: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
    ) -> SQLQuery:
        """
        Build complete SQL query from ViewDefinition

        Args:
            view_definition: SQL-on-FHIR ViewDefinition resource
            search_params: FHIR search parameters for additional filtering
            limit: Maximum number of rows to return

        Returns:
            SQLQuery with complete executable SQL
        """
        view_name = view_definition.get("name", "unnamed")
        resource_type = view_definition.get("resource", "Unknown")
        select_elements = view_definition.get("select", [])
        where_elements = view_definition.get("where", [])

        # Extract columns and lateral joins
        select_clause = self.extractor.extract_columns(select_elements, resource_type)

        # Build FROM clause
        from_clause = self._build_from_clause(resource_type)

        # Add lateral joins if present
        if select_clause.lateral_joins:
            from_clause += "\n" + "\n".join(select_clause.lateral_joins)

        # Build WHERE clause
        where_conditions = []
        params: List[Any] = []

        # Add ViewDefinition where clauses
        if where_elements:
            vd_where = self.extractor.extract_where_clause(where_elements)
            if vd_where:
                # Extract just the conditions (remove "WHERE" prefix)
                where_conditions.append(vd_where.replace("WHERE\n    ", ""))

        # Add search parameter filters
        if search_params:
            search_where = self._build_search_param_where(search_params, params)
            if search_where:
                where_conditions.append(search_where)

        # Always filter deleted resources
        where_conditions.append("r.res_deleted_at IS NULL")

        # Filter by resource type. A literal, not a bound param: resource_type comes
        # from an admin-only ViewDefinition (ADR 0030), and materialize_views.py
        # reuses this SQL in CREATE MATERIALIZED VIEW, which can't take parameters.
        where_conditions.append(f"r.res_type = '{resource_type}'")

        # Combine WHERE conditions
        where_clause = ""
        if where_conditions:
            where_clause = "WHERE\n    " + "\n    AND ".join(where_conditions)

        # Build complete query
        query_parts = [select_clause.select_sql, from_clause, where_clause]

        # Add LIMIT if specified
        if limit:
            params.append(int(limit))
            query_parts.append(f"LIMIT ${len(params)}")

        sql = "\n".join(part for part in query_parts if part)

        return SQLQuery(
            sql=sql,
            resource_type=resource_type,
            view_name=view_name,
            column_count=len(select_clause.columns),
            has_lateral_joins=bool(select_clause.lateral_joins),
            has_where_clause=bool(where_elements or search_params),
            params=params,
        )

    def _build_from_clause(self, resource_type: str) -> str:
        """
        Build FROM clause with HAPI table join

        Args:
            resource_type: FHIR resource type

        Returns:
            FROM clause SQL
        """
        # Join hfj_resource (metadata) with hfj_res_ver (content)
        # Must match on BOTH res_id (resource ID) and res_ver (version number)
        from_clause = """FROM hfj_resource r
JOIN hfj_res_ver v ON r.res_id = v.res_id AND r.res_ver = v.res_ver"""

        return from_clause

    def _build_search_param_where(self, search_params: Dict[str, Any], params: List[Any]) -> str:
        """
        Build WHERE conditions from FHIR search parameters

        Values are appended to `params` and referenced as $n, never pasted into
        the SQL text. Unknown keys are rejected: they used to become JSONB keys.

        Args:
            search_params: FHIR search parameters
            params: Bound parameters of the query being built (appended to)

        Returns:
            WHERE conditions SQL

        Raises:
            UnsupportedSearchParamError: unknown key or non-string value
        """
        conditions = []

        def bind(value: str) -> str:
            params.append(value)
            return f"${len(params)}"

        birth_date = "v.res_text_vc::jsonb->>'birthDate'"
        prefix_ops = {"ge": ">=", "le": "<=", "gt": ">", "lt": "<", "eq": "="}

        for param_name, param_value in search_params.items():
            if not isinstance(param_value, str):
                raise UnsupportedSearchParamError(param_name)

            if param_name == "_id":
                conditions.append(f"r.res_id::text = {bind(param_value)}")

            elif param_name == "gender":
                # Case-insensitive exact, same rule as the batch and speed layers
                conditions.append(
                    f"LOWER(v.res_text_vc::jsonb->>'gender') = LOWER({bind(param_value)})"
                )

            elif param_name in ("birthdate", "birthdate_min", "birthdate_max"):
                # FHIR prefix support: "ge1995-01-01" means >= 1995-01-01; no prefix is exact
                op, date_val = "=", param_value
                if param_value[:2] in prefix_ops:
                    op, date_val = prefix_ops[param_value[:2]], param_value[2:]
                conditions.append(f"{birth_date} {op} {bind(date_val)}")

            elif param_name == "status":
                # Top-level code on Procedure/Observation/MedicationRequest. The
                # sqlonfhir tables route here (HybridRunner only detects matviews).
                conditions.append(f"v.res_text_vc::jsonb->>'status' = {bind(param_value)}")

            elif param_name == "family":
                # Name search - check in name array
                conditions.append(
                    f"EXISTS (SELECT 1 FROM jsonb_array_elements(v.res_text_vc::jsonb->'name') AS name_elem "
                    f"WHERE name_elem->>'family' = {bind(param_value)})"
                )

            else:
                raise UnsupportedSearchParamError(param_name)

        return " AND ".join(conditions) if conditions else ""

    def build_count_query(
        self, view_definition: Dict[str, Any], search_params: Optional[Dict[str, Any]] = None
    ) -> Tuple[str, List[Any]]:
        """
        Build COUNT query for feasibility checks

        Args:
            view_definition: ViewDefinition resource
            search_params: FHIR search parameters

        Returns:
            SQL COUNT query and its bound parameters
        """
        resource_type = view_definition.get("resource", "Unknown")
        where_elements = view_definition.get("where", [])

        # Build WHERE clause (same logic as full query)
        where_conditions = []
        params: List[Any] = []

        if where_elements:
            vd_where = self.extractor.extract_where_clause(where_elements)
            if vd_where:
                where_conditions.append(vd_where.replace("WHERE\n    ", ""))

        if search_params:
            search_where = self._build_search_param_where(search_params, params)
            if search_where:
                where_conditions.append(search_where)

        where_conditions.append("r.res_deleted_at IS NULL")
        where_conditions.append(f"r.res_type = '{resource_type}'")

        where_clause = "WHERE\n    " + "\n    AND ".join(where_conditions)

        # Build count query
        count_sql = f"""SELECT COUNT(DISTINCT r.res_id) AS count
FROM hfj_resource r
JOIN hfj_res_ver v ON r.res_id = v.res_id AND r.res_ver = v.res_ver
{where_clause}"""

        return count_sql, params


def create_sql_query_builder(
    transpiler: FHIRPathTranspiler, extractor: ColumnExtractor
) -> SQLQueryBuilder:
    """
    Factory function to create SQL query builder

    Args:
        transpiler: FHIRPath transpiler
        extractor: Column extractor

    Returns:
        Configured SQLQueryBuilder
    """
    return SQLQueryBuilder(transpiler, extractor)
