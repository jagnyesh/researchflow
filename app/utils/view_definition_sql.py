"""
ViewDefinition to SQL Converter

Generates SQL-like representations from SQL-on-FHIR v2 ViewDefinitions
for display purposes. These are not executable SQL but readable pseudo-SQL
showing the data transformation logic.
"""

from typing import Dict, Any, List


def view_definition_to_sql(view_def: Dict[str, Any], search_params: Dict[str, Any] = None) -> str:
    """
    Convert a ViewDefinition to SQL-like syntax for display

    Args:
        view_def: ViewDefinition resource
        search_params: FHIR search parameters applied

    Returns:
        SQL-like string representation
    """
    resource_type = view_def.get('resource', 'Unknown')
    view_name = view_def.get('name', 'unnamed_view')
    select_elements = view_def.get('select', [])
    where_clauses = view_def.get('where', [])

    # Build SELECT clause
    columns = _extract_columns(select_elements)
    select_clause = "SELECT\n  " + ",\n  ".join(columns)

    # Build FROM clause
    from_clause = f"FROM {resource_type}"

    # Build WHERE clause
    where_conditions = []

    # Add ViewDefinition where clauses
    for where in where_clauses:
        path = where.get('path', '')
        desc = where.get('description', '')
        if desc:
            where_conditions.append(f"{path}  -- {desc}")
        else:
            where_conditions.append(path)

    # Add search parameters
    if search_params:
        for key, value in search_params.items():
            where_conditions.append(f"{key} = '{value}'")

    where_clause = ""
    if where_conditions:
        where_clause = "WHERE\n  " + " AND\n  ".join(where_conditions)

    # Build comment header
    header = f"-- ViewDefinition: {view_name}\n"
    if view_def.get('title'):
        header += f"-- {view_def['title']}\n"
    if view_def.get('description'):
        header += f"-- {view_def['description']}\n"
    header += "\n"

    # Combine
    sql = header + select_clause + "\n" + from_clause
    if where_clause:
        sql += "\n" + where_clause
    sql += ";"

    return sql


def _extract_columns(select_elements: List[Dict[str, Any]], prefix: str = "") -> List[str]:
    """
    Extract column definitions from select elements

    Args:
        select_elements: List of select elements from ViewDefinition
        prefix: Prefix for nested columns

    Returns:
        List of column strings
    """
    columns = []

    for select_elem in select_elements:
        # Handle forEach
        if 'forEach' in select_elem or 'forEachOrNull' in select_elem:
            for_each_path = select_elem.get('forEach') or select_elem.get('forEachOrNull')
            for_each_type = 'forEach' if 'forEach' in select_elem else 'forEachOrNull'

            # Add columns with forEach context
            elem_columns = select_elem.get('column', [])
            for col in elem_columns:
                name = col.get('name', 'unnamed')
                path = col.get('path', '')
                desc = col.get('description', '')

                comment = f" -- {for_each_type}({for_each_path}) -> {path}"
                if desc:
                    comment += f" | {desc}"

                columns.append(f"{prefix}{name}{comment}")

        # Handle regular columns
        elif 'column' in select_elem:
            elem_columns = select_elem['column']
            for col in elem_columns:
                name = col.get('name', 'unnamed')
                path = col.get('path', '')
                desc = col.get('description', '')

                comment = f" -- {path}"
                if desc:
                    comment += f" | {desc}"

                columns.append(f"{prefix}{name}{comment}")

        # Handle nested select
        if 'select' in select_elem:
            nested_columns = _extract_columns(select_elem['select'], prefix + "  ")
            columns.extend(nested_columns)

        # Handle unionAll
        if 'unionAll' in select_elem:
            for union_select in select_elem['unionAll']:
                union_columns = _extract_columns([union_select], prefix)
                columns.extend(union_columns)

    return columns


def generate_sql_for_view_names(
    view_names: List[str],
    view_definitions: Dict[str, Dict[str, Any]],
    search_params: Dict[str, Any] = None
) -> Dict[str, str]:
    """
    Generate SQL-like representations for multiple ViewDefinitions

    Args:
        view_names: List of ViewDefinition names
        view_definitions: Dict mapping view names to ViewDefinitions
        search_params: FHIR search parameters

    Returns:
        Dict mapping view names to SQL strings
    """
    sql_queries = {}

    for view_name in view_names:
        if view_name in view_definitions:
            sql = view_definition_to_sql(view_definitions[view_name], search_params)
            sql_queries[view_name] = sql

    return sql_queries
