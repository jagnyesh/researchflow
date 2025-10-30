#!/usr/bin/env python3
"""
Materialize SQL-on-FHIR ViewDefinitions in PostgreSQL

Creates materialized views in the 'sqlonfhir' schema for all ViewDefinitions.
This enables fast analytics queries without regenerating SQL each time.

Usage:
    python scripts/materialize_views.py --create     # Create all materialized views
    python scripts/materialize_views.py --refresh    # Refresh all materialized views
    python scripts/materialize_views.py --drop       # Drop all materialized views

Environment:
    HAPI_DB_URL: PostgreSQL connection string for HAPI FHIR database
                 Default: postgresql://hapi:hapi@localhost:5433/hapi
"""

import asyncio
import asyncpg
import json
import logging
import os
import sys
from pathlib import Path
from typing import List, Dict, Any

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.sql_on_fhir.view_definition_manager import ViewDefinitionManager
from app.sql_on_fhir.runner.postgres_runner import PostgresRunner

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
SCHEMA_NAME = "sqlonfhir"
VIEW_DEFINITIONS_DIR = Path(__file__).parent.parent / "app" / "sql_on_fhir" / "view_definitions"
HAPI_DB_URL = os.getenv("HAPI_DB_URL", "postgresql://hapi:hapi@localhost:5433/hapi")


class ViewMaterializer:
    """Materializes ViewDefinitions as PostgreSQL materialized views."""

    def __init__(self, database_url: str):
        self.database_url = database_url
        self.manager = ViewDefinitionManager(str(VIEW_DEFINITIONS_DIR))
        self.runner = PostgresRunner(database_url)

    async def create_schema(self, conn: asyncpg.Connection):
        """Create the sqlonfhir schema if it doesn't exist."""
        logger.info(f"Creating schema '{SCHEMA_NAME}' if not exists...")
        await conn.execute(f"""
            CREATE SCHEMA IF NOT EXISTS {SCHEMA_NAME}
        """)
        logger.info(f"✅ Schema '{SCHEMA_NAME}' ready")

    async def get_view_definitions(self) -> List[Dict[str, Any]]:
        """Load all ViewDefinitions from the directory."""
        view_defs = []

        for json_file in VIEW_DEFINITIONS_DIR.glob("*.json"):
            try:
                with open(json_file, 'r') as f:
                    view_def = json.load(f)
                    view_defs.append({
                        'name': view_def.get('name'),
                        'resource': view_def.get('resource'),
                        'definition': view_def,
                        'file': json_file.name
                    })
                    logger.info(f"  Loaded ViewDefinition: {view_def.get('name')} ({json_file.name})")
            except Exception as e:
                logger.error(f"  Failed to load {json_file.name}: {e}")

        return view_defs

    async def materialize_view(
        self,
        conn: asyncpg.Connection,
        view_name: str,
        view_def: Dict[str, Any],
        resource_type: str
    ):
        """Create a materialized view for a ViewDefinition."""
        try:
            logger.info(f"\n{'='*60}")
            logger.info(f"Materializing view: {view_name}")
            logger.info(f"{'='*60}")

            # Generate SQL using the runner
            logger.info(f"  Generating SQL for {resource_type}...")
            query_result = await self.runner.execute_view_definition(
                view_definition=view_def,
                resource_type=resource_type
            )

            generated_sql = query_result.get('sql', '')

            if not generated_sql:
                logger.error(f"  ❌ No SQL generated for {view_name}")
                return False

            logger.info(f"  ✅ SQL generated ({len(generated_sql)} chars)")

            # Drop existing materialized view if it exists
            drop_sql = f"DROP MATERIALIZED VIEW IF EXISTS {SCHEMA_NAME}.{view_name} CASCADE"
            logger.info(f"  Dropping existing view if present...")
            await conn.execute(drop_sql)

            # Create materialized view
            create_sql = f"""
                CREATE MATERIALIZED VIEW {SCHEMA_NAME}.{view_name} AS
                {generated_sql}
            """

            logger.info(f"  Creating materialized view...")
            await conn.execute(create_sql)
            logger.info(f"  ✅ Materialized view created: {SCHEMA_NAME}.{view_name}")

            # Add indexes for common query patterns
            await self._create_indexes(conn, view_name, query_result.get('columns', []))

            # Get row count
            count_result = await conn.fetchrow(f"SELECT COUNT(*) as count FROM {SCHEMA_NAME}.{view_name}")
            row_count = count_result['count']
            logger.info(f"  📊 Row count: {row_count:,}")

            return True

        except Exception as e:
            logger.error(f"  ❌ Failed to materialize {view_name}: {e}")
            logger.exception(e)
            return False

    async def _create_indexes(self, conn: asyncpg.Connection, view_name: str, columns: List[str]):
        """Create indexes on common columns for better query performance."""
        logger.info(f"  Creating indexes...")

        # Common columns to index
        index_candidates = ['patient_id', 'id', 'code', 'status', 'date', 'effective_date']

        indexes_created = 0
        for col in index_candidates:
            if col in [c.lower() for c in columns]:
                try:
                    index_name = f"idx_{view_name}_{col}"
                    await conn.execute(f"""
                        CREATE INDEX IF NOT EXISTS {index_name}
                        ON {SCHEMA_NAME}.{view_name} ({col})
                    """)
                    indexes_created += 1
                    logger.info(f"    ✅ Index created: {index_name}")
                except Exception as e:
                    logger.warning(f"    ⚠️  Failed to create index on {col}: {e}")

        if indexes_created == 0:
            logger.info(f"    No standard indexes created")

    async def refresh_view(self, conn: asyncpg.Connection, view_name: str):
        """Refresh a materialized view with latest data."""
        try:
            logger.info(f"Refreshing view: {view_name}...")
            await conn.execute(f"""
                REFRESH MATERIALIZED VIEW {SCHEMA_NAME}.{view_name}
            """)

            # Get updated row count
            count_result = await conn.fetchrow(f"SELECT COUNT(*) as count FROM {SCHEMA_NAME}.{view_name}")
            row_count = count_result['count']
            logger.info(f"  ✅ View refreshed: {SCHEMA_NAME}.{view_name} ({row_count:,} rows)")
            return True
        except Exception as e:
            logger.error(f"  ❌ Failed to refresh {view_name}: {e}")
            return False

    async def drop_view(self, conn: asyncpg.Connection, view_name: str):
        """Drop a materialized view."""
        try:
            logger.info(f"Dropping view: {view_name}...")
            await conn.execute(f"""
                DROP MATERIALIZED VIEW IF EXISTS {SCHEMA_NAME}.{view_name} CASCADE
            """)
            logger.info(f"  ✅ View dropped: {SCHEMA_NAME}.{view_name}")
            return True
        except Exception as e:
            logger.error(f"  ❌ Failed to drop {view_name}: {e}")
            return False

    async def list_views(self, conn: asyncpg.Connection):
        """List all materialized views in the schema."""
        logger.info(f"\nMaterialized views in '{SCHEMA_NAME}' schema:")
        logger.info(f"{'='*60}")

        result = await conn.fetch(f"""
            SELECT
                schemaname,
                matviewname,
                pg_size_pretty(pg_total_relation_size(schemaname||'.'||matviewname)) as size,
                (SELECT COUNT(*) FROM {SCHEMA_NAME}."|| matviewname) as row_count
            FROM pg_matviews
            WHERE schemaname = '{SCHEMA_NAME}'
            ORDER BY matviewname
        """)

        if not result:
            logger.info("  No materialized views found")
            return

        for row in result:
            logger.info(f"  • {row['matviewname']}")
            logger.info(f"      Size: {row['size']}")
            logger.info(f"      Rows: {row['row_count']:,}")

    async def create_all_views(self):
        """Create materialized views for all ViewDefinitions."""
        logger.info(f"\n{'='*60}")
        logger.info(f"MATERIALIZE ALL VIEWS")
        logger.info(f"{'='*60}")
        logger.info(f"Database: {self.database_url}")
        logger.info(f"Schema: {SCHEMA_NAME}")

        conn = await asyncpg.connect(self.database_url)

        try:
            # Create schema
            await self.create_schema(conn)

            # Load ViewDefinitions
            logger.info(f"\nLoading ViewDefinitions from {VIEW_DEFINITIONS_DIR}...")
            view_defs = await self.get_view_definitions()
            logger.info(f"✅ Found {len(view_defs)} ViewDefinitions")

            # Materialize each view
            success_count = 0
            fail_count = 0

            for view_data in view_defs:
                success = await self.materialize_view(
                    conn,
                    view_data['name'],
                    view_data['definition'],
                    view_data['resource']
                )
                if success:
                    success_count += 1
                else:
                    fail_count += 1

            # Summary
            logger.info(f"\n{'='*60}")
            logger.info(f"SUMMARY")
            logger.info(f"{'='*60}")
            logger.info(f"  ✅ Successfully materialized: {success_count}/{len(view_defs)}")
            if fail_count > 0:
                logger.warning(f"  ❌ Failed: {fail_count}/{len(view_defs)}")

            # List all views
            await self.list_views(conn)

            logger.info(f"\n{'='*60}")
            logger.info(f"✅ ALL VIEWS MATERIALIZED")
            logger.info(f"{'='*60}")
            logger.info(f"\nYou can now query views like:")
            logger.info(f"  SELECT * FROM {SCHEMA_NAME}.patient_demographics LIMIT 10;")
            logger.info(f"  SELECT COUNT(*) FROM {SCHEMA_NAME}.condition_simple;")

        finally:
            await conn.close()

    async def refresh_all_views(self):
        """Refresh all materialized views."""
        logger.info(f"\n{'='*60}")
        logger.info(f"REFRESH ALL VIEWS")
        logger.info(f"{'='*60}")

        conn = await asyncpg.connect(self.database_url)

        try:
            # Get list of views
            result = await conn.fetch(f"""
                SELECT matviewname
                FROM pg_matviews
                WHERE schemaname = '{SCHEMA_NAME}'
                ORDER BY matviewname
            """)

            if not result:
                logger.warning(f"No materialized views found in '{SCHEMA_NAME}' schema")
                return

            view_names = [row['matviewname'] for row in result]
            logger.info(f"Found {len(view_names)} views to refresh")

            success_count = 0
            for view_name in view_names:
                if await self.refresh_view(conn, view_name):
                    success_count += 1

            logger.info(f"\n✅ Refreshed {success_count}/{len(view_names)} views")

        finally:
            await conn.close()

    async def drop_all_views(self):
        """Drop all materialized views."""
        logger.info(f"\n{'='*60}")
        logger.info(f"DROP ALL VIEWS")
        logger.info(f"{'='*60}")

        conn = await asyncpg.connect(self.database_url)

        try:
            # Get list of views
            result = await conn.fetch(f"""
                SELECT matviewname
                FROM pg_matviews
                WHERE schemaname = '{SCHEMA_NAME}'
                ORDER BY matviewname
            """)

            if not result:
                logger.warning(f"No materialized views found in '{SCHEMA_NAME}' schema")
                return

            view_names = [row['matviewname'] for row in result]
            logger.info(f"Found {len(view_names)} views to drop")

            success_count = 0
            for view_name in view_names:
                if await self.drop_view(conn, view_name):
                    success_count += 1

            # Drop schema if empty
            await conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA_NAME} CASCADE")
            logger.info(f"\n✅ Dropped schema '{SCHEMA_NAME}'")

        finally:
            await conn.close()


async def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Materialize SQL-on-FHIR ViewDefinitions in PostgreSQL"
    )
    parser.add_argument(
        '--create',
        action='store_true',
        help='Create all materialized views'
    )
    parser.add_argument(
        '--refresh',
        action='store_true',
        help='Refresh all materialized views'
    )
    parser.add_argument(
        '--drop',
        action='store_true',
        help='Drop all materialized views'
    )
    parser.add_argument(
        '--list',
        action='store_true',
        help='List all materialized views'
    )

    args = parser.parse_args()

    # Default to --create if no args
    if not any([args.create, args.refresh, args.drop, args.list]):
        args.create = True

    materializer = ViewMaterializer(HAPI_DB_URL)

    try:
        if args.create:
            await materializer.create_all_views()
        elif args.refresh:
            await materializer.refresh_all_views()
        elif args.drop:
            await materializer.drop_all_views()
        elif args.list:
            conn = await asyncpg.connect(HAPI_DB_URL)
            try:
                await materializer.list_views(conn)
            finally:
                await conn.close()

    except Exception as e:
        logger.error(f"❌ Error: {e}")
        logger.exception(e)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
