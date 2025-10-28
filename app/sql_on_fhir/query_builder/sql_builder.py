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
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

from app.sql_on_fhir.transpiler import (
    FHIRPathTranspiler,
    ColumnExtractor
)

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


class SQLQueryBuilder:
    """
    Builds complete SQL queries from ViewDefinitions

    Generates executable PostgreSQL queries against HAPI FHIR database
    """

    def __init__(
        self,
        transpiler: FHIRPathTranspiler,
        extractor: ColumnExtractor
    ):
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
        limit: Optional[int] = None
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
        view_name = view_definition.get('name', 'unnamed')
        resource_type = view_definition.get('resource', 'Unknown')
        select_elements = view_definition.get('select', [])
        where_elements = view_definition.get('where', [])

        # Extract columns and lateral joins
        select_clause = self.extractor.extract_columns(
            select_elements,
            resource_type
        )

        # Build FROM clause
        from_clause = self._build_from_clause(resource_type)

        # Add lateral joins if present
        if select_clause.lateral_joins:
            from_clause += "\n" + "\n".join(select_clause.lateral_joins)

        # Build WHERE clause
        where_conditions = []

        # Add ViewDefinition where clauses
        if where_elements:
            vd_where = self.extractor.extract_where_clause(where_elements)
            if vd_where:
                # Extract just the conditions (remove "WHERE" prefix)
                where_conditions.append(vd_where.replace('WHERE\n    ', ''))

        # Add search parameter filters
        if search_params:
            search_where = self._build_search_param_where(search_params, resource_type)
            if search_where:
                where_conditions.append(search_where)

        # Always filter deleted resources
        where_conditions.append("r.res_deleted_at IS NULL")

        # Filter by resource type
        where_conditions.append(f"r.res_type = '{resource_type}'")

        # Combine WHERE conditions
        where_clause = ""
        if where_conditions:
            where_clause = "WHERE\n    " + "\n    AND ".join(where_conditions)

        # Build complete query
        query_parts = [
            select_clause.select_sql,
            from_clause,
            where_clause
        ]

        # Add LIMIT if specified
        if limit:
            query_parts.append(f"LIMIT {limit}")

        sql = "\n".join(part for part in query_parts if part)

        return SQLQuery(
            sql=sql,
            resource_type=resource_type,
            view_name=view_name,
            column_count=len(select_clause.columns),
            has_lateral_joins=bool(select_clause.lateral_joins),
            has_where_clause=bool(where_elements or search_params)
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

    def _build_search_param_where(
        self,
        search_params: Dict[str, Any],
        resource_type: str
    ) -> str:
        """
        Build WHERE conditions from FHIR search parameters

        Args:
            search_params: FHIR search parameters
            resource_type: Resource type

        Returns:
            WHERE conditions SQL
        """
        conditions = []

        for param_name, param_value in search_params.items():
            # Handle common search parameters
            if param_name == '_id':
                conditions.append(f"r.res_id = '{param_value}'")

            elif param_name == 'gender':
                # Use JSONB path for simple fields
                conditions.append(
                    f"v.res_text_vc::jsonb->>'gender' = '{param_value}'"
                )

            elif param_name == 'birthdate' or param_name == 'birthdate_min' or param_name == 'birthdate_max':
                # Date search with FHIR prefix support (ge, le, gt, lt, eq)
                # Examples: "ge1995-01-01" means >= 1995-01-01
                #           "le2005-12-31" means <= 2005-12-31
                # birthdate_min and birthdate_max allow separate min/max constraints
                if isinstance(param_value, str):
                    if param_value.startswith('ge'):
                        # Greater than or equal
                        date_val = param_value[2:]
                        conditions.append(
                            f"v.res_text_vc::jsonb->>'birthDate' >= '{date_val}'"
                        )
                    elif param_value.startswith('le'):
                        # Less than or equal
                        date_val = param_value[2:]
                        conditions.append(
                            f"v.res_text_vc::jsonb->>'birthDate' <= '{date_val}'"
                        )
                    elif param_value.startswith('gt'):
                        # Greater than
                        date_val = param_value[2:]
                        conditions.append(
                            f"v.res_text_vc::jsonb->>'birthDate' > '{date_val}'"
                        )
                    elif param_value.startswith('lt'):
                        # Less than
                        date_val = param_value[2:]
                        conditions.append(
                            f"v.res_text_vc::jsonb->>'birthDate' < '{date_val}'"
                        )
                    elif param_value.startswith('eq'):
                        # Equal
                        date_val = param_value[2:]
                        conditions.append(
                            f"v.res_text_vc::jsonb->>'birthDate' = '{date_val}'"
                        )
                    else:
                        # No prefix - exact match
                        conditions.append(
                            f"v.res_text_vc::jsonb->>'birthDate' = '{param_value}'"
                        )

            elif param_name == 'family':
                # Name search - check in name array
                conditions.append(
                    f"EXISTS (SELECT 1 FROM jsonb_array_elements(v.res_text_vc::jsonb->'name') AS name_elem "
                    f"WHERE name_elem->>'family' = '{param_value}')"
                )

            else:
                # Generic parameter - try JSONB path
                logger.warning(f"Unknown search parameter: {param_name}, using generic JSONB match")
                conditions.append(
                    f"v.res_text_vc::jsonb->>'{param_name}' = '{param_value}'"
                )

        return " AND ".join(conditions) if conditions else ""

    def build_count_query(
        self,
        view_definition: Dict[str, Any],
        search_params: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Build COUNT query for feasibility checks

        Args:
            view_definition: ViewDefinition resource
            search_params: FHIR search parameters

        Returns:
            SQL COUNT query
        """
        resource_type = view_definition.get('resource', 'Unknown')
        where_elements = view_definition.get('where', [])

        # Build WHERE clause (same logic as full query)
        where_conditions = []

        if where_elements:
            vd_where = self.extractor.extract_where_clause(where_elements)
            if vd_where:
                where_conditions.append(vd_where.replace('WHERE\n    ', ''))

        if search_params:
            search_where = self._build_search_param_where(search_params, resource_type)
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

        return count_sql


def create_sql_query_builder(
    transpiler: FHIRPathTranspiler,
    extractor: ColumnExtractor
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
