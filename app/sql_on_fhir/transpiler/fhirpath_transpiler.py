"""
FHIRPath to SQL Transpiler

Converts FHIRPath expressions (from SQL-on-FHIR ViewDefinitions)
to PostgreSQL JSONB queries for execution against HAPI FHIR database.

Supported FHIRPath features:
- Simple field access: "gender", "birthDate"
- Nested fields: "name.family", "address.city"
- Array navigation: "name.given" (first element), "name.given.all()" (all elements)
- where() clause: "coding.where(system='http://loinc.org')"
- first(), exists(), count(), empty()
- Type casting: toInteger(), toString(), toDateTime()

Example conversions:
  FHIRPath: "name.family"
  SQL: v.res_text_vc::jsonb->'name'->0->>'family'

  FHIRPath: "code.coding.where(system='http://loinc.org').code"
  SQL: (SELECT coding->>'code' FROM jsonb_array_elements(...) WHERE ...)
"""

import logging
import re
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class FHIRPathExpression:
    """Parsed FHIRPath expression"""
    path: str  # Original FHIRPath
    sql: str  # Transpiled SQL
    requires_subquery: bool = False  # True if needs lateral join
    array_alias: Optional[str] = None  # Alias for jsonb_array_elements


class FHIRPathTranspiler:
    """
    Transpiles FHIRPath expressions to PostgreSQL JSONB queries

    Handles the subset of FHIRPath used in SQL-on-FHIR ViewDefinitions
    """

    def __init__(self, resource_alias: str = "v", resource_column: str = "res_text_vc"):
        """
        Initialize transpiler

        Args:
            resource_alias: Table alias for resource version table (default: 'v')
            resource_column: Column name containing JSONB resource (default: 'res_text_vc')
        """
        self.resource_alias = resource_alias
        self.resource_column = resource_column
        self._array_counter = 0  # For generating unique array aliases

    def transpile(
        self,
        fhir_path: str,
        as_text: bool = True,
        context_path: Optional[str] = None
    ) -> FHIRPathExpression:
        """
        Transpile FHIRPath expression to SQL

        Args:
            fhir_path: FHIRPath expression
            as_text: If True, use ->> for text output; if False, use -> for jsonb
            context_path: Optional context path (for forEach expressions)

        Returns:
            FHIRPathExpression with transpiled SQL
        """
        # Strip whitespace
        fhir_path = fhir_path.strip()

        # Handle empty path
        if not fhir_path or fhir_path == '.':
            base_path = f"{self.resource_alias}.{self.resource_column}::jsonb"
            if context_path:
                base_path = context_path
            return FHIRPathExpression(
                path=fhir_path,
                sql=base_path
            )

        # Check for string concatenation with + operator
        if ' + ' in fhir_path:
            return self._transpile_concatenation(fhir_path, as_text, context_path)

        # Check for where() clause
        if '.where(' in fhir_path:
            return self._transpile_where_clause(fhir_path, as_text, context_path)

        # Check for function calls
        if '.first()' in fhir_path:
            return self._transpile_first(fhir_path, as_text, context_path)

        if '.exists()' in fhir_path:
            return self._transpile_exists(fhir_path, context_path)

        if '.count()' in fhir_path:
            return self._transpile_count(fhir_path, context_path)

        if '.empty()' in fhir_path:
            return self._transpile_empty(fhir_path, context_path)

        # Simple field path (most common case)
        return self._transpile_simple_path(fhir_path, as_text, context_path)

    def _transpile_simple_path(
        self,
        fhir_path: str,
        as_text: bool,
        context_path: Optional[str]
    ) -> FHIRPathExpression:
        """
        Transpile simple field path like "name.family" or "birthDate"

        Args:
            fhir_path: Simple field path
            as_text: Use ->> for final element
            context_path: Optional context for nested paths

        Returns:
            FHIRPathExpression with JSONB path
        """
        # Start with resource or context
        if context_path:
            base = context_path
        else:
            base = f"{self.resource_alias}.{self.resource_column}::jsonb"

        # Split path into segments
        segments = fhir_path.split('.')

        # Build JSONB navigation
        sql_parts = [base]

        for i, segment in enumerate(segments):
            is_last = (i == len(segments) - 1)

            # Handle array access (assume first element for simple paths)
            # In FHIR, many fields like "name" and "address" are arrays
            if segment in ['name', 'address', 'telecom', 'identifier', 'coding']:
                # Access first element of array
                sql_parts.append(f"->0")
                # Then access the field
                if is_last and as_text:
                    sql_parts.append(f"->>'{segment}'")
                else:
                    sql_parts.append(f"->'{segment}'")
            else:
                # Simple field access
                if is_last and as_text:
                    sql_parts.append(f"->>'{segment}'")
                else:
                    sql_parts.append(f"->'{segment}'")

        sql = "".join(sql_parts)

        return FHIRPathExpression(
            path=fhir_path,
            sql=sql
        )

    def _transpile_where_clause(
        self,
        fhir_path: str,
        as_text: bool,
        context_path: Optional[str]
    ) -> FHIRPathExpression:
        """
        Transpile where() clause like "coding.where(system='http://loinc.org').code"

        Generates a lateral join with jsonb_array_elements

        Args:
            fhir_path: Path with where clause
            as_text: Use ->> for final output
            context_path: Optional context

        Returns:
            FHIRPathExpression with subquery SQL
        """
        # Parse: <array_path>.where(<condition>).<result_path>
        # Match one or more path segments (including nested like "code.coding")
        match = re.match(r"(.+?)\.where\((.+?)\)(?:\.(.+))?", fhir_path)

        if not match:
            logger.warning(f"Could not parse where clause: {fhir_path}")
            return self._transpile_simple_path(fhir_path, as_text, context_path)

        array_path = match.group(1)  # e.g., "coding" or "code.coding"
        condition = match.group(2)   # e.g., "system='http://loinc.org'"
        result_path = match.group(3)  # e.g., "code"

        # Generate unique alias for array element
        self._array_counter += 1
        array_alias = f"elem_{self._array_counter}"

        # Build base path to array
        if context_path:
            base = context_path
        else:
            base = f"{self.resource_alias}.{self.resource_column}::jsonb"

        # Path to array - handle nested paths like "code.coding"
        if '.' in array_path:
            # Nested path: navigate to parent, then to array
            path_parts = array_path.split('.')
            for part in path_parts:
                base = f"{base}->'{part}'"
            array_sql = base
        else:
            # Simple path
            array_sql = f"{base}->'{array_path}'"

        # Parse condition (simple equality only for now)
        condition_sql = self._parse_where_condition(condition, array_alias)

        # Build subquery
        if result_path:
            # Extract specific field from matching element
            if as_text:
                select_expr = f"{array_alias}->>'{result_path}'"
            else:
                select_expr = f"{array_alias}->'{result_path}'"

            sql = f"""(
                SELECT {select_expr}
                FROM jsonb_array_elements({array_sql}) AS {array_alias}
                WHERE {condition_sql}
                LIMIT 1
            )""".strip()
        else:
            # Return entire matching element
            sql = f"""(
                SELECT {array_alias}
                FROM jsonb_array_elements({array_sql}) AS {array_alias}
                WHERE {condition_sql}
                LIMIT 1
            )""".strip()

        return FHIRPathExpression(
            path=fhir_path,
            sql=sql,
            requires_subquery=True,
            array_alias=array_alias
        )

    def _parse_where_condition(self, condition: str, elem_alias: str) -> str:
        """
        Parse where() condition to SQL WHERE clause

        Args:
            condition: FHIRPath condition (e.g., "system='http://loinc.org'")
            elem_alias: Alias for array element

        Returns:
            SQL WHERE condition
        """
        # Simple equality: field='value'
        match = re.match(r"(\w+)\s*=\s*'([^']+)'", condition)
        if match:
            field = match.group(1)
            value = match.group(2)
            return "{}->>'{}'  = '{}'".format(elem_alias, field, value)

        # TODO: Support more complex conditions
        logger.warning(f"Unsupported where condition: {condition}")
        return "true"

    def _transpile_first(
        self,
        fhir_path: str,
        as_text: bool,
        context_path: Optional[str]
    ) -> FHIRPathExpression:
        """
        Transpile first() function

        Args:
            fhir_path: Path with .first()
            as_text: Use ->> for output
            context_path: Optional context

        Returns:
            FHIRPathExpression accessing first array element
        """
        # Remove .first() and access [0]
        base_path = fhir_path.replace('.first()', '')

        # Transpile base path
        base_expr = self._transpile_simple_path(base_path, False, context_path)

        # Add [0] access
        if as_text:
            sql = f"({base_expr.sql})->0"
        else:
            sql = f"({base_expr.sql})->0"

        return FHIRPathExpression(
            path=fhir_path,
            sql=sql
        )

    def _transpile_exists(
        self,
        fhir_path: str,
        context_path: Optional[str]
    ) -> FHIRPathExpression:
        """
        Transpile exists() function to check if field exists and is not null

        Args:
            fhir_path: Path with .exists()
            context_path: Optional context

        Returns:
            FHIRPathExpression with boolean check
        """
        base_path = fhir_path.replace('.exists()', '')
        base_expr = self._transpile_simple_path(base_path, False, context_path)

        sql = f"({base_expr.sql} IS NOT NULL)"

        return FHIRPathExpression(
            path=fhir_path,
            sql=sql
        )

    def _transpile_count(
        self,
        fhir_path: str,
        context_path: Optional[str]
    ) -> FHIRPathExpression:
        """
        Transpile count() function for arrays

        Args:
            fhir_path: Path with .count()
            context_path: Optional context

        Returns:
            FHIRPathExpression with jsonb_array_length
        """
        base_path = fhir_path.replace('.count()', '')
        base_expr = self._transpile_simple_path(base_path, False, context_path)

        sql = f"jsonb_array_length({base_expr.sql})"

        return FHIRPathExpression(
            path=fhir_path,
            sql=sql
        )

    def _transpile_empty(
        self,
        fhir_path: str,
        context_path: Optional[str]
    ) -> FHIRPathExpression:
        """
        Transpile empty() function to check if value is null or empty

        Args:
            fhir_path: Path with .empty()
            context_path: Optional context

        Returns:
            FHIRPathExpression with null/empty check
        """
        base_path = fhir_path.replace('.empty()', '')
        base_expr = self._transpile_simple_path(base_path, False, context_path)

        sql = f"({base_expr.sql} IS NULL OR {base_expr.sql} = '[]'::jsonb)"

        return FHIRPathExpression(
            path=fhir_path,
            sql=sql
        )

    def _transpile_concatenation(
        self,
        fhir_path: str,
        as_text: bool,
        context_path: Optional[str]
    ) -> FHIRPathExpression:
        """
        Transpile string concatenation using + operator

        Args:
            fhir_path: Path with + operator (e.g., "given.first() + ' ' + family")
            as_text: Use ->> for text output
            context_path: Optional context

        Returns:
            FHIRPathExpression with SQL concatenation using ||
        """
        # Split by + operator
        parts = fhir_path.split(' + ')

        sql_parts = []
        for part in parts:
            part = part.strip()

            # Check if it's a string literal (quoted)
            if part.startswith("'") and part.endswith("'"):
                # Keep string literal as-is
                sql_parts.append(part)
            else:
                # Transpile as FHIRPath expression
                expr = self.transpile(part, as_text=True, context_path=context_path)
                sql_parts.append(f"COALESCE({expr.sql}, '')")

        # Join with SQL concatenation operator ||
        sql = " || ".join(sql_parts)

        return FHIRPathExpression(
            path=fhir_path,
            sql=sql
        )

    def transpile_forEach(
        self,
        fhir_path: str,
        column_paths: List[Tuple[str, str]]
    ) -> Tuple[str, str, str]:
        """
        Transpile forEach expression for lateral join

        Args:
            fhir_path: forEach path (e.g., "name" for array iteration)
            column_paths: List of (column_name, fhir_path) to extract from each element

        Returns:
            Tuple of (lateral_join_clause, array_alias, select_columns)
        """
        # Generate unique alias
        self._array_counter += 1
        array_alias = f"foreach_{self._array_counter}"

        # Build path to array
        base = f"{self.resource_alias}.{self.resource_column}::jsonb"
        array_path = f"{base}->'{fhir_path}'"

        # Build lateral join
        lateral_join = f"""
            LEFT JOIN LATERAL jsonb_array_elements({array_path}) AS {array_alias}
            ON true
        """.strip()

        # Build SELECT columns for each path in the forEach context
        select_columns = []
        for col_name, col_path in column_paths:
            # Transpile in context of array element
            expr = self.transpile(col_path, as_text=True, context_path=array_alias)
            select_columns.append(f"{expr.sql} AS {col_name}")

        return lateral_join, array_alias, ", ".join(select_columns)


def create_fhirpath_transpiler(
    resource_alias: str = "v",
    resource_column: str = "res_text_vc"
) -> FHIRPathTranspiler:
    """
    Factory function to create FHIRPath transpiler

    Args:
        resource_alias: Alias for resource version table
        resource_column: Column with JSONB resource

    Returns:
        Configured FHIRPathTranspiler
    """
    return FHIRPathTranspiler(resource_alias, resource_column)
