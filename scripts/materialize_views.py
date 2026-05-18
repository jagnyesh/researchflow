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

import sqlonfhir

from app.sql_on_fhir.runner.backend_dispatcher import select_backend
from app.sql_on_fhir.runner.hapi_db_resource_reader import fetch_fhir_resources_for_view
from app.sql_on_fhir.runner.mv_health_check import post_write_health_check
from app.sql_on_fhir.view_definition_manager import ViewDefinitionManager
from app.sql_on_fhir.runner.postgres_runner import PostgresRunner

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Configuration
SCHEMA_NAME = "sqlonfhir"
VIEW_DEFINITIONS_DIR = Path(__file__).parent.parent / "app" / "sql_on_fhir" / "view_definitions"
# asyncpg can't parse SQLAlchemy's "postgresql+asyncpg://" prefix; strip it so
# both shell-loaded and .env-loaded HAPI_DB_URL values work. Same fix that
# landed in tests/test_drive_fhir_traffic.py during Sprint 6.5 /qa pass.
HAPI_DB_URL = os.getenv("HAPI_DB_URL", "postgresql://hapi:hapi@localhost:5433/hapi").replace(
    "postgresql+asyncpg://", "postgresql://"
)


class ViewMaterializer:
    """Materializes ViewDefinitions as PostgreSQL materialized views."""

    def __init__(self, database_url: str):
        self.database_url = database_url
        self.manager = ViewDefinitionManager(str(VIEW_DEFINITIONS_DIR))
        self.runner = PostgresRunner(database_url)

    async def create_schema(self, conn: asyncpg.Connection):
        """Create the sqlonfhir schema if it doesn't exist."""
        logger.info(f"Creating schema '{SCHEMA_NAME}' if not exists...")
        await conn.execute(
            f"""
            CREATE SCHEMA IF NOT EXISTS {SCHEMA_NAME}
        """
        )
        logger.info(f"✅ Schema '{SCHEMA_NAME}' ready")

    async def create_metadata_table(self, conn: asyncpg.Connection):
        """Create mv_refresh_metadata table for batch_anchor_ts tracking.

        Sprint 6.5 Phase 1 (#68): HybridRunner reads MAX(refreshed_at)
        from this table to compute batch_anchor_ts for FORMAL_EXTRACTION
        mode reads. Append-only log; one row per successful refresh per
        view. Lives in HAPI :5433 alongside the MVs so both the writer
        (this script) and reader (HybridRunner via HAPIDBClient) reach
        it without cross-DB connections.
        """
        await conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {SCHEMA_NAME}.mv_refresh_metadata (
                id           SERIAL PRIMARY KEY,
                view_name    TEXT NOT NULL,
                refreshed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                row_count    INTEGER NOT NULL
            )
            """
        )
        await conn.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_mv_refresh_view_time
                ON {SCHEMA_NAME}.mv_refresh_metadata(view_name, refreshed_at DESC)
            """
        )
        logger.info(f"✅ Table '{SCHEMA_NAME}.mv_refresh_metadata' ready")

    async def _record_refresh_completion(
        self, conn: asyncpg.Connection, view_name: str, row_count: int
    ):
        """Append one row to mv_refresh_metadata after a successful refresh.

        Best-effort: failures here are logged but do NOT roll back the
        underlying MV refresh (the refresh has already committed by the
        time we record completion). The next successful refresh writes a
        new row, so a single missed record self-heals.
        """
        try:
            await conn.execute(
                f"""
                INSERT INTO {SCHEMA_NAME}.mv_refresh_metadata
                    (view_name, row_count)
                VALUES ($1, $2)
                """,
                view_name,
                row_count,
            )
        except Exception as e:
            logger.warning(
                f"  ⚠ Failed to record refresh completion for {view_name}: {e}. "
                f"MV refresh itself succeeded; next refresh will self-heal the metadata gap."
            )

    async def get_view_definitions(self) -> List[Dict[str, Any]]:
        """Load all ViewDefinitions from the directory."""
        view_defs = []

        for json_file in VIEW_DEFINITIONS_DIR.glob("*.json"):
            try:
                with open(json_file, "r") as f:
                    view_def = json.load(f)
                    view_defs.append(
                        {
                            "name": view_def.get("name"),
                            "resource": view_def.get("resource"),
                            "definition": view_def,
                            "file": json_file.name,
                        }
                    )
                    logger.info(
                        f"  Loaded ViewDefinition: {view_def.get('name')} ({json_file.name})"
                    )
            except Exception as e:
                logger.error(f"  Failed to load {json_file.name}: {e}")

        return view_defs

    async def materialize_view(
        self, conn: asyncpg.Connection, view_name: str, view_def: Dict[str, Any], resource_type: str
    ):
        """Dispatch to the right backend and materialize the view.

        Sprint 6.4 cycle 3 — refactored from cycle 2's _build_view_sql() seam.
        sqlonfhir doesn't produce SQL (returns rows from in-memory FHIRPath
        evaluation), so the two backends produce different artifacts and
        need different storage paths. Embracing the asymmetry:

          - custom backend: CREATE MATERIALIZED VIEW ... AS <sql> (existing)
          - sqlonfhir backend: CREATE TABLE + TRUNCATE + INSERT (cycle 3)

        See Sprint 6.4 ADR for the operational impact of the storage
        asymmetry on refresh mechanics.
        """
        backend = select_backend(view_def)
        if backend == "sqlonfhir":
            return await self._materialize_via_sqlonfhir(conn, view_name, view_def, resource_type)
        return await self._materialize_via_custom(conn, view_name, view_def, resource_type)

    async def _materialize_via_custom(
        self, conn: asyncpg.Connection, view_name: str, view_def: Dict[str, Any], resource_type: str
    ):
        """Custom transpiler path: build SQL and CREATE MATERIALIZED VIEW."""
        try:
            logger.info(f"\n{'='*60}")
            logger.info(f"Materializing view: {view_name} (custom transpiler)")
            logger.info(f"{'='*60}")

            logger.info(f"  Generating SQL for {resource_type}...")
            query = self.runner.builder.build_query(view_definition=view_def)
            generated_sql = query.sql

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

            # Decision 8A (issue #13): UNIQUE INDEX on id is required for
            # REFRESH MATERIALIZED VIEW CONCURRENTLY (Phase 2.0).
            try:
                index_sql = (
                    f"CREATE UNIQUE INDEX IF NOT EXISTS {view_name}_id_idx "
                    f"ON {SCHEMA_NAME}.{view_name} (id)"
                )
                await conn.execute(index_sql)
                logger.info(f"  ✅ Created UNIQUE INDEX on id")
            except Exception as idx_err:
                logger.warning(
                    f"  ⚠ UNIQUE INDEX on id failed: {idx_err}. "
                    f"REFRESH MATERIALIZED VIEW CONCURRENTLY will not work for "
                    f"{SCHEMA_NAME}.{view_name}."
                )

            # Get row count
            count_result = await conn.fetchrow(
                f"SELECT COUNT(*) as count FROM {SCHEMA_NAME}.{view_name}"
            )
            row_count = count_result["count"]
            logger.info(f"  📊 Row count: {row_count:,}")

            # Sprint 6.4 cycle 5 — post-write health check vs HAPI oracle.
            # No-op for MVs without an oracle in mv_row_count_oracles.sql
            # (the 4 custom-path MVs today). Logs WARN if delta > threshold
            # or alarm fires (N=3 consecutive warn records).
            await post_write_health_check(conn, view_name, row_count)

            # Sprint 6.5 Phase 1 (#68) — record refresh completion for
            # HybridRunner's batch_anchor_ts lookup.
            await self._record_refresh_completion(conn, view_name, row_count)

            return True

        except Exception as e:
            logger.error(f"  ❌ Failed to materialize {view_name}: {e}")
            logger.exception(e)
            return False

    async def _materialize_via_sqlonfhir(
        self, conn: asyncpg.Connection, view_name: str, view_def: Dict[str, Any], resource_type: str
    ):
        """sqlonfhir backend path (Sprint 6.4 cycle 3).

        Fetch FHIR resources from HAPI :5433 Postgres directly, evaluate
        the view-def via sqlonfhir.evaluate() in-memory, and write rows
        to a regular Postgres TABLE (not a materialized view — sqlonfhir
        produces rows, not SQL).

        Refresh mechanics differ from the custom path:
          - custom: REFRESH MATERIALIZED VIEW CONCURRENTLY
          - sqlonfhir (here): TRUNCATE + INSERT (idempotent re-run)

        Schema for the destination table is declared explicitly from the
        view-def's column declarations — fail-fast on malformed view-defs
        rather than inferring schema from the first row.
        """
        try:
            logger.info(f"\n{'='*60}")
            logger.info(f"Materializing view: {view_name} (sqlonfhir)")
            logger.info(f"{'='*60}")

            # Build explicit column schema from view-def declarations BEFORE
            # evaluation. sqlonfhir 0.0.2 mutates view_def in place during
            # evaluate(): nested forEach/forEachOrNull blocks have their
            # `column` key renamed to `select`. Reading columns after
            # evaluate() silently misses every nested-block column (caught
            # by Sprint 6.2 transpiler harness on procedure_history's 6
            # forEachOrNull columns; CI surfaced it 2026-05-15).
            columns: List[str] = []
            for select_block in view_def.get("select", []):
                for col in select_block.get("column", []):
                    name = col.get("name")
                    if not name:
                        raise ValueError(f"view-def {view_name} has a column without a name field")
                    if name not in columns:
                        columns.append(name)
            if not columns:
                raise ValueError(f"view-def {view_name} declared no columns; cannot create table")

            # Fetch FHIR resources from HAPI's internal Postgres
            logger.info(f"  Reading {resource_type} resources from HAPI :5433...")
            resources = await fetch_fhir_resources_for_view(conn, view_def)
            logger.info(f"  ✅ Loaded {len(resources):,} {resource_type} resource(s)")

            # In-memory FHIRPath evaluation via sqlonfhir
            logger.info(f"  Evaluating view-def via sqlonfhir.evaluate()...")
            rows = sqlonfhir.evaluate(resources, view_def)
            logger.info(f"  ✅ Produced {len(rows):,} row(s)")

            # Drop any prior object at this name. Sprint 6.4 converts
            # previously-materialized-view objects (Sprint 6.2 era) to plain
            # tables for sqlonfhir-backed paths. Postgres's DROP ... IF EXISTS
            # only suppresses "not found"; it raises "wrong object type" if
            # something exists but of the other kind. So we check pg_class
            # first and dispatch to the matching DROP statement.
            existing_kind = await conn.fetchval(
                """
                SELECT c.relkind
                FROM pg_class c
                JOIN pg_namespace n ON c.relnamespace = n.oid
                WHERE n.nspname = $1 AND c.relname = $2
                """,
                SCHEMA_NAME,
                view_name,
            )
            # asyncpg returns pg_class.relkind as a single-byte `bytes` object
            # (Postgres `char` type), so compare against b"m" / b"r" not "m" / "r".
            if existing_kind == b"m":  # materialized view
                logger.info(f"  Dropping prior materialized view {SCHEMA_NAME}.{view_name}...")
                await conn.execute(f"DROP MATERIALIZED VIEW {SCHEMA_NAME}.{view_name} CASCADE")
            elif existing_kind == b"r":  # ordinary table
                logger.info(f"  Dropping prior table {SCHEMA_NAME}.{view_name}...")
                await conn.execute(f"DROP TABLE {SCHEMA_NAME}.{view_name} CASCADE")
            # existing_kind is None when no object exists; nothing to drop

            # CREATE TABLE — schema declared explicitly from view-def columns.
            # Typed as TEXT for now (sqlonfhir output is JSON-typed); future
            # cycle may infer typed columns from view-def path expressions.
            col_defs = ", ".join(f'"{c}" TEXT' for c in columns)
            create_sql = f"CREATE TABLE {SCHEMA_NAME}.{view_name} ({col_defs})"
            logger.info(f"  Creating table...")
            await conn.execute(create_sql)

            if rows:
                placeholders = ", ".join(f"${i + 1}" for i in range(len(columns)))
                col_list = ", ".join(f'"{c}"' for c in columns)
                insert_sql = (
                    f"INSERT INTO {SCHEMA_NAME}.{view_name} ({col_list}) "
                    f"VALUES ({placeholders})"
                )
                logger.info(f"  Inserting {len(rows):,} rows...")
                records = [
                    tuple(None if row.get(c) is None else str(row.get(c)) for c in columns)
                    for row in rows
                ]
                await conn.executemany(insert_sql, records)
                logger.info(f"  ✅ Inserted {len(records):,} rows")

            # UNIQUE INDEX on id — matches the custom path's invariant.
            # If sqlonfhir produced rows with NULL id (e.g., fhir_id merge
            # failed in fetch_fhir_resources_for_view), this fails loudly.
            try:
                index_sql = (
                    f"CREATE UNIQUE INDEX IF NOT EXISTS {view_name}_id_idx "
                    f"ON {SCHEMA_NAME}.{view_name} (id)"
                )
                await conn.execute(index_sql)
                logger.info(f"  ✅ Created UNIQUE INDEX on id")
            except Exception as idx_err:
                logger.warning(
                    f"  ⚠ UNIQUE INDEX on id failed: {idx_err}. "
                    f"Check that fhir_id merge in fetch_fhir_resources_for_view "
                    f"applied correctly (NULL ids in sqlonfhir output are the "
                    f"usual cause)."
                )

            row_count = await conn.fetchval(f"SELECT COUNT(*) FROM {SCHEMA_NAME}.{view_name}")
            logger.info(f"  📊 Row count: {row_count:,}")

            # Sprint 6.4 cycle 5 — post-write health check vs HAPI oracle.
            # The sqlonfhir-backed MVs all have oracles defined; this fires
            # the same-run delta check + JSONL log + N=3 alarm filter.
            await post_write_health_check(conn, view_name, row_count)

            # Sprint 6.5 Phase 1 (#68) — record refresh completion for
            # HybridRunner's batch_anchor_ts lookup.
            await self._record_refresh_completion(conn, view_name, row_count)

            return True

        except Exception as e:
            logger.error(f"  ❌ Failed to materialize {view_name} via sqlonfhir: {e}")
            logger.exception(e)
            return False

    async def _create_indexes(self, conn: asyncpg.Connection, view_name: str, columns: List[str]):
        """Create indexes on common columns for better query performance."""
        logger.info(f"  Creating indexes...")

        # Common columns to index
        index_candidates = ["patient_id", "id", "code", "status", "date", "effective_date"]

        indexes_created = 0
        for col in index_candidates:
            if col in [c.lower() for c in columns]:
                try:
                    index_name = f"idx_{view_name}_{col}"
                    await conn.execute(
                        f"""
                        CREATE INDEX IF NOT EXISTS {index_name}
                        ON {SCHEMA_NAME}.{view_name} ({col})
                    """
                    )
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
            await conn.execute(
                f"""
                REFRESH MATERIALIZED VIEW {SCHEMA_NAME}.{view_name}
            """
            )

            # Get updated row count
            count_result = await conn.fetchrow(
                f"SELECT COUNT(*) as count FROM {SCHEMA_NAME}.{view_name}"
            )
            row_count = count_result["count"]
            logger.info(f"  ✅ View refreshed: {SCHEMA_NAME}.{view_name} ({row_count:,} rows)")

            # Sprint 6.5 Phase 1 (#68) — record refresh completion for
            # HybridRunner's batch_anchor_ts lookup.
            await self._record_refresh_completion(conn, view_name, row_count)

            return True
        except Exception as e:
            logger.error(f"  ❌ Failed to refresh {view_name}: {e}")
            return False

    async def drop_view(self, conn: asyncpg.Connection, view_name: str):
        """Drop a materialized view."""
        try:
            logger.info(f"Dropping view: {view_name}...")
            await conn.execute(
                f"""
                DROP MATERIALIZED VIEW IF EXISTS {SCHEMA_NAME}.{view_name} CASCADE
            """
            )
            logger.info(f"  ✅ View dropped: {SCHEMA_NAME}.{view_name}")
            return True
        except Exception as e:
            logger.error(f"  ❌ Failed to drop {view_name}: {e}")
            return False

    async def list_views(self, conn: asyncpg.Connection):
        """List all materialized views in the schema."""
        logger.info(f"\nMaterialized views in '{SCHEMA_NAME}' schema:")
        logger.info(f"{'='*60}")

        result = await conn.fetch(
            f"""
            SELECT
                schemaname,
                matviewname,
                pg_size_pretty(pg_total_relation_size(schemaname||'.'||matviewname)) as size,
                0 as row_count
            FROM pg_matviews
            WHERE schemaname = '{SCHEMA_NAME}'
            ORDER BY matviewname
        """
        )

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
            # Create schema + metadata table (Sprint 6.5 Phase 1 #68)
            await self.create_schema(conn)
            await self.create_metadata_table(conn)

            # Load ViewDefinitions
            logger.info(f"\nLoading ViewDefinitions from {VIEW_DEFINITIONS_DIR}...")
            view_defs = await self.get_view_definitions()
            logger.info(f"✅ Found {len(view_defs)} ViewDefinitions")

            # Materialize each view
            success_count = 0
            fail_count = 0

            for view_data in view_defs:
                success = await self.materialize_view(
                    conn, view_data["name"], view_data["definition"], view_data["resource"]
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
            # Ensure metadata table exists for refresh-only flows that may
            # predate Sprint 6.5 Phase 1 (#68) on long-running deployments.
            await self.create_metadata_table(conn)

            # Get list of views
            result = await conn.fetch(
                f"""
                SELECT matviewname
                FROM pg_matviews
                WHERE schemaname = '{SCHEMA_NAME}'
                ORDER BY matviewname
            """
            )

            if not result:
                logger.warning(f"No materialized views found in '{SCHEMA_NAME}' schema")
                return

            view_names = [row["matviewname"] for row in result]
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
            result = await conn.fetch(
                f"""
                SELECT matviewname
                FROM pg_matviews
                WHERE schemaname = '{SCHEMA_NAME}'
                ORDER BY matviewname
            """
            )

            if not result:
                logger.warning(f"No materialized views found in '{SCHEMA_NAME}' schema")
                return

            view_names = [row["matviewname"] for row in result]
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
    parser.add_argument("--create", action="store_true", help="Create all materialized views")
    parser.add_argument("--refresh", action="store_true", help="Refresh all materialized views")
    parser.add_argument("--drop", action="store_true", help="Drop all materialized views")
    parser.add_argument("--list", action="store_true", help="List all materialized views")

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
