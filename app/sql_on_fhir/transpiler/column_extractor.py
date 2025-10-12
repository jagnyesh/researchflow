"""
ViewDefinition Column Extractor

Parses SQL-on-FHIR ViewDefinition SELECT clauses and generates
SQL SELECT statements with proper column extraction and forEach handling.

Handles:
- Simple columns with FHIRPath expressions
- forEach array iteration with lateral joins
- forEachOrNull for optional array elements
- Nested select structures
"""

import logging
from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass

from .fhirpath_transpiler import FHIRPathTranspiler

logger = logging.getLogger(__name__)


@dataclass
class ColumnDefinition:
    """Single column definition"""
    name: str
    sql_expression: str
    description: Optional[str] = None
    is_nullable: bool = False


@dataclass
class SelectClause:
    """Complete SELECT clause with columns and lateral joins"""
    columns: List[ColumnDefinition]
    lateral_joins: List[str]
    select_sql: str


class ColumnExtractor:
    """
    Extracts columns from ViewDefinition SELECT clause

    Generates SQL SELECT statements using FHIRPath transpiler
    """

    def __init__(self, transpiler: FHIRPathTranspiler):
        """
        Initialize column extractor

        Args:
            transpiler: FHIRPath to SQL transpiler instance
        """
        self.transpiler = transpiler
        self._lateral_counter = 0

    def extract_columns(
        self,
        select_elements: List[Dict[str, Any]],
        resource_type: str
    ) -> SelectClause:
        """
        Extract columns from ViewDefinition select elements

        Args:
            select_elements: List of select elements from ViewDefinition
            resource_type: FHIR resource type

        Returns:
            SelectClause with columns, lateral joins, and complete SQL
        """
        all_columns = []
        lateral_joins = []

        for select_elem in select_elements:
            # Handle forEach
            if 'forEach' in select_elem:
                cols, join = self._extract_forEach_columns(
                    select_elem,
                    select_elem['forEach'],
                    nullable=False
                )
                all_columns.extend(cols)
                lateral_joins.append(join)

            # Handle forEachOrNull
            elif 'forEachOrNull' in select_elem:
                cols, join = self._extract_forEach_columns(
                    select_elem,
                    select_elem['forEachOrNull'],
                    nullable=True
                )
                all_columns.extend(cols)
                lateral_joins.append(join)

            # Handle simple columns
            elif 'column' in select_elem:
                cols = self._extract_simple_columns(select_elem['column'])
                all_columns.extend(cols)

            # Handle unionAll (advanced feature)
            elif 'unionAll' in select_elem:
                logger.warning("unionAll not yet supported, skipping")

        # Build SELECT SQL
        select_sql = self._build_select_sql(all_columns)

        return SelectClause(
            columns=all_columns,
            lateral_joins=lateral_joins,
            select_sql=select_sql
        )

    def _extract_simple_columns(
        self,
        column_defs: List[Dict[str, Any]]
    ) -> List[ColumnDefinition]:
        """
        Extract simple columns (no forEach)

        Args:
            column_defs: List of column definitions

        Returns:
            List of ColumnDefinition objects
        """
        columns = []

        for col_def in column_defs:
            name = col_def.get('name', 'unnamed')
            path = col_def.get('path', '')
            description = col_def.get('description')

            # Handle special functions
            if path == 'getResourceKey()':
                # Resource key is the FHIR ID
                sql_expr = f"v.res_text_vc::jsonb->>'id'"
            else:
                # Transpile FHIRPath to SQL
                expr = self.transpiler.transpile(path, as_text=True)
                sql_expr = expr.sql

            columns.append(ColumnDefinition(
                name=name,
                sql_expression=sql_expr,
                description=description,
                is_nullable=False
            ))

        return columns

    def _extract_forEach_columns(
        self,
        select_elem: Dict[str, Any],
        for_each_path: str,
        nullable: bool
    ) -> Tuple[List[ColumnDefinition], str]:
        """
        Extract columns from forEach/forEachOrNull

        Args:
            select_elem: Select element with forEach
            for_each_path: FHIRPath expression for array iteration
            nullable: True for forEachOrNull, False for forEach

        Returns:
            Tuple of (column list, lateral join SQL)
        """
        column_defs = select_elem.get('column', [])

        # Generate unique alias for this forEach
        self._lateral_counter += 1
        foreach_alias = f"foreach_{self._lateral_counter}"

        # Transpile forEach path to get array
        # Handle complex paths like "name.where(use = 'official').first()"
        base_expr = self.transpiler.transpile(for_each_path, as_text=False)

        # Build lateral join
        if nullable:
            join_type = "LEFT JOIN LATERAL"
        else:
            join_type = "CROSS JOIN LATERAL"

        # Check if forEach path returns array or single element
        if '.first()' in for_each_path or base_expr.requires_subquery:
            # Single element - use it directly as context
            lateral_join = f"""
{join_type} (
    SELECT {base_expr.sql} AS {foreach_alias}
) AS {foreach_alias}_row ON true
            """.strip()
            context_path = f"{foreach_alias}_row.{foreach_alias}"
        else:
            # Array - use jsonb_array_elements
            lateral_join = f"""
{join_type} jsonb_array_elements(
    COALESCE({base_expr.sql}, '[]'::jsonb)
) AS {foreach_alias} ON true
            """.strip()
            context_path = foreach_alias

        # Extract columns in context of forEach element
        columns = []
        for col_def in column_defs:
            name = col_def.get('name', 'unnamed')
            path = col_def.get('path', '')
            description = col_def.get('description')

            # Transpile in forEach context
            expr = self.transpiler.transpile(path, as_text=True, context_path=context_path)

            columns.append(ColumnDefinition(
                name=name,
                sql_expression=expr.sql,
                description=description,
                is_nullable=nullable
            ))

        return columns, lateral_join

    def _build_select_sql(self, columns: List[ColumnDefinition]) -> str:
        """
        Build complete SELECT clause SQL

        Args:
            columns: List of column definitions

        Returns:
            SELECT clause SQL string
        """
        if not columns:
            return "SELECT 1"

        # Build column expressions
        col_exprs = []
        for col in columns:
            # Add column with alias
            col_exprs.append(f"    {col.sql_expression} AS {col.name}")

        select_sql = "SELECT\n" + ",\n".join(col_exprs)

        return select_sql

    def extract_where_clause(
        self,
        where_elements: List[Dict[str, Any]]
    ) -> str:
        """
        Extract WHERE clause from ViewDefinition

        Args:
            where_elements: List of where elements from ViewDefinition

        Returns:
            WHERE clause SQL string
        """
        if not where_elements:
            return ""

        conditions = []

        for where_elem in where_elements:
            path = where_elem.get('path', '')
            description = where_elem.get('description')

            # Transpile FHIRPath to SQL
            expr = self.transpiler.transpile(path, as_text=False)

            # Add comment if description exists
            if description:
                conditions.append(f"({expr.sql})  -- {description}")
            else:
                conditions.append(f"({expr.sql})")

        where_sql = "WHERE\n    " + "\n    AND ".join(conditions)

        return where_sql


def create_column_extractor(transpiler: FHIRPathTranspiler) -> ColumnExtractor:
    """
    Factory function to create column extractor

    Args:
        transpiler: FHIRPath transpiler instance

    Returns:
        Configured ColumnExtractor
    """
    return ColumnExtractor(transpiler)
