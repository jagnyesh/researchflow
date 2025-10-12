"""
HAPI FHIR Database Schema Introspection

Discovers and maps HAPI FHIR's PostgreSQL schema to enable SQL-on-FHIR query generation.

Key HAPI tables:
- hfj_resource: Main resource metadata
- hfj_res_ver: Resource version content (JSONB)
- hfj_spidx_*: Search parameter indexes (string, date, token, quantity, uri, coords, number)
- hfj_res_link: Resource references
- hfj_res_tag: Resource tags
"""

import logging
from typing import Dict, List, Any, Optional, Set
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TableColumn:
    """Database column information"""
    name: str
    data_type: str
    is_nullable: bool
    max_length: Optional[int] = None
    numeric_precision: Optional[int] = None


@dataclass
class SearchParamIndex:
    """Search parameter index table information"""
    table_name: str
    param_type: str  # string, date, token, quantity, uri, coords, number
    columns: List[TableColumn]


@dataclass
class HAPISchema:
    """
    Complete HAPI FHIR database schema information

    Attributes:
        resource_table: Main hfj_resource table schema
        version_table: hfj_res_ver table schema
        search_indexes: Search parameter index tables
        resource_types: Set of available FHIR resource types
    """
    resource_table: Dict[str, TableColumn]
    version_table: Dict[str, TableColumn]
    search_indexes: Dict[str, SearchParamIndex]
    resource_types: Set[str]


class HAPISchemaIntrospector:
    """
    Introspects HAPI FHIR database schema

    Provides mapping between FHIR concepts and database tables/columns
    for SQL-on-FHIR query generation.
    """

    def __init__(self, db_client):
        """
        Initialize schema introspector

        Args:
            db_client: HAPIDBClient instance
        """
        self.db_client = db_client
        self._schema_cache: Optional[HAPISchema] = None

    async def get_schema(self, use_cache: bool = True) -> HAPISchema:
        """
        Get complete HAPI schema information

        Args:
            use_cache: Use cached schema if available

        Returns:
            HAPISchema with complete database structure
        """
        if use_cache and self._schema_cache:
            return self._schema_cache

        logger.info("Introspecting HAPI database schema...")

        # Get table schemas
        resource_table = await self._introspect_table('hfj_resource')
        version_table = await self._introspect_table('hfj_res_ver')

        # Get search parameter index tables
        search_indexes = await self._introspect_search_indexes()

        # Get available resource types
        resource_types = await self._get_resource_types()

        schema = HAPISchema(
            resource_table=resource_table,
            version_table=version_table,
            search_indexes=search_indexes,
            resource_types=resource_types
        )

        self._schema_cache = schema
        logger.info(f"Schema introspection complete: {len(resource_types)} resource types, "
                   f"{len(search_indexes)} search index tables")

        return schema

    async def _introspect_table(self, table_name: str) -> Dict[str, TableColumn]:
        """
        Get column information for a table

        Args:
            table_name: Name of table to introspect

        Returns:
            Dict mapping column names to TableColumn objects
        """
        sql = """
            SELECT
                column_name,
                data_type,
                is_nullable,
                character_maximum_length,
                numeric_precision
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = $1
            ORDER BY ordinal_position
        """

        rows = await self.db_client.execute_query(sql, [table_name])

        columns = {}
        for row in rows:
            col = TableColumn(
                name=row['column_name'],
                data_type=row['data_type'],
                is_nullable=(row['is_nullable'] == 'YES'),
                max_length=row.get('character_maximum_length'),
                numeric_precision=row.get('numeric_precision')
            )
            columns[col.name] = col

        return columns

    async def _introspect_search_indexes(self) -> Dict[str, SearchParamIndex]:
        """
        Discover search parameter index tables

        Returns:
            Dict mapping table names to SearchParamIndex objects
        """
        # Known HAPI search parameter index tables
        search_param_tables = {
            'hfj_spidx_string': 'string',
            'hfj_spidx_date': 'date',
            'hfj_spidx_token': 'token',
            'hfj_spidx_quantity': 'quantity',
            'hfj_spidx_uri': 'uri',
            'hfj_spidx_coords': 'coords',
            'hfj_spidx_number': 'number'
        }

        indexes = {}

        for table_name, param_type in search_param_tables.items():
            # Check if table exists
            exists_sql = """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                      AND table_name = $1
                )
            """
            exists = await self.db_client.execute_scalar(exists_sql, [table_name])

            if exists:
                columns_dict = await self._introspect_table(table_name)
                columns_list = list(columns_dict.values())

                index = SearchParamIndex(
                    table_name=table_name,
                    param_type=param_type,
                    columns=columns_list
                )
                indexes[table_name] = index

        return indexes

    async def _get_resource_types(self) -> Set[str]:
        """
        Get set of available FHIR resource types in database

        Returns:
            Set of resource type names
        """
        sql = """
            SELECT DISTINCT res_type
            FROM hfj_resource
            WHERE res_deleted_at IS NULL
            ORDER BY res_type
        """
        rows = await self.db_client.execute_query(sql)
        return {row['res_type'] for row in rows}

    async def get_search_param_column(
        self,
        param_name: str,
        param_type: str,
        resource_type: str
    ) -> Optional[str]:
        """
        Map FHIR search parameter to database column

        Args:
            param_name: FHIR search parameter name (e.g., 'gender', 'birthdate')
            param_type: Parameter type (string, date, token, etc.)
            resource_type: FHIR resource type

        Returns:
            Column name in search index table, or None if not found
        """
        # Common column mappings by param type
        column_mappings = {
            'string': 'sp_value_normalized',  # Normalized string value
            'date': 'sp_value_low',  # Date range low value
            'token': 'sp_value',  # Token value (code, identifier)
            'quantity': 'sp_value',  # Numeric quantity value
            'uri': 'sp_uri',  # URI value
            'number': 'sp_value',  # Numeric value
        }

        return column_mappings.get(param_type)

    async def get_resource_json_path(self, fhir_path: str) -> str:
        """
        Convert FHIRPath expression to PostgreSQL JSONB path

        Args:
            fhir_path: FHIRPath expression (e.g., "Patient.gender")

        Returns:
            PostgreSQL JSONB path expression (e.g., "res_text_vc::jsonb->'gender'")
        """
        # Remove resource type prefix if present
        if '.' in fhir_path:
            parts = fhir_path.split('.', 1)
            path = parts[1]
        else:
            path = fhir_path

        # Convert to JSONB path operators
        # Simple case: direct field access
        if '.' not in path:
            return f"v.res_text_vc::jsonb->'{path}'"

        # Nested path: field1.field2.field3
        path_parts = path.split('.')
        jsonb_path = "v.res_text_vc::jsonb"

        for i, part in enumerate(path_parts):
            if i == len(path_parts) - 1:
                # Last element - use ->> for text output
                jsonb_path += f"->'{part}'"
            else:
                # Intermediate elements - use -> for jsonb
                jsonb_path += f"->'{part}'"

        return jsonb_path

    def get_search_index_join(
        self,
        resource_alias: str,
        param_type: str,
        index_alias: str
    ) -> str:
        """
        Generate JOIN clause for search parameter index table

        Args:
            resource_alias: Alias for hfj_resource table (e.g., 'r')
            param_type: Search parameter type
            index_alias: Alias for search index table (e.g., 'sp_gender')

        Returns:
            SQL JOIN clause
        """
        table_name = f"hfj_spidx_{param_type}"

        return f"""
            LEFT JOIN {table_name} {index_alias}
              ON {resource_alias}.res_id = {index_alias}.res_id
              AND {index_alias}.sp_name = '{{param_name}}'
        """.strip()

    async def print_schema_summary(self):
        """Print human-readable schema summary for debugging"""
        schema = await self.get_schema()

        print("\n" + "=" * 80)
        print("HAPI FHIR DATABASE SCHEMA SUMMARY")
        print("=" * 80)

        print(f"\nResource Types ({len(schema.resource_types)}):")
        for rt in sorted(schema.resource_types):
            print(f"  - {rt}")

        print(f"\nhfj_resource table ({len(schema.resource_table)} columns):")
        for col_name, col in list(schema.resource_table.items())[:10]:
            nullable = "NULL" if col.is_nullable else "NOT NULL"
            print(f"  {col_name}: {col.data_type} {nullable}")
        if len(schema.resource_table) > 10:
            print(f"  ... and {len(schema.resource_table) - 10} more columns")

        print(f"\nhfj_res_ver table ({len(schema.version_table)} columns):")
        for col_name, col in list(schema.version_table.items())[:10]:
            nullable = "NULL" if col.is_nullable else "NOT NULL"
            print(f"  {col_name}: {col.data_type} {nullable}")
        if len(schema.version_table) > 10:
            print(f"  ... and {len(schema.version_table) - 10} more columns")

        print(f"\nSearch Parameter Indexes ({len(schema.search_indexes)} tables):")
        for table_name, index in schema.search_indexes.items():
            print(f"  {table_name} ({index.param_type}):")
            key_columns = ['res_id', 'sp_name', 'sp_value', 'sp_value_normalized',
                          'sp_value_low', 'sp_value_high']
            for col in index.columns:
                if col.name in key_columns:
                    print(f"    - {col.name}: {col.data_type}")

        print("\n" + "=" * 80 + "\n")


async def create_schema_introspector(db_client) -> HAPISchemaIntrospector:
    """
    Factory function to create and initialize schema introspector

    Args:
        db_client: HAPIDBClient instance

    Returns:
        Initialized HAPISchemaIntrospector
    """
    introspector = HAPISchemaIntrospector(db_client)

    # Pre-load schema on creation
    await introspector.get_schema(use_cache=False)

    return introspector
