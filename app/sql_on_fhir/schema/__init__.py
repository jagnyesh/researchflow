"""
SQL-on-FHIR Schema Introspection

Provides database schema discovery and mapping for HAPI FHIR databases.
"""

from .hapi_schema import (
    HAPISchemaIntrospector,
    HAPISchema,
    TableColumn,
    SearchParamIndex,
    create_schema_introspector
)

__all__ = [
    'HAPISchemaIntrospector',
    'HAPISchema',
    'TableColumn',
    'SearchParamIndex',
    'create_schema_introspector'
]
