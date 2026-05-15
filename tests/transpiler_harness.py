"""Helper module for the transpiler correctness harness (test_transpiler_correctness.py).

Public interface — one helper per check the harness performs:

    view_exists(name)            -> bool
    materialized_columns(name)   -> set[str]
    view_def_columns(view_def)   -> set[str]
    query_count(name)            -> int
    query_sample(name, key, val) -> dict
    transpiled_sql(view_def)     -> str

All db-touching helpers use the HAPI_DB_URL connection. They assume the
materialize_views.py session fixture has run.
"""

import os

import asyncpg

HAPI_DB_URL = os.getenv(
    "HAPI_DB_URL",
    "postgresql://hapi:hapi@localhost:5433/hapi",  # pragma: allowlist secret
).replace("+asyncpg", "")

SCHEMA = "sqlonfhir"


async def view_exists(view_name: str) -> bool:
    """True iff sqlonfhir.<view_name> is materialized.

    Sprint 6.4 storage asymmetry: custom-path MVs land as materialized views
    (pg_class.relkind='m'); sqlonfhir-path MVs land as plain tables
    (relkind='r') because sqlonfhir.evaluate() returns rows in memory, not
    SQL. Both populate sqlonfhir.<view_name>. Match either via pg_class so
    the harness stays dispatch-agnostic.
    """
    conn = await asyncpg.connect(HAPI_DB_URL)
    try:
        row = await conn.fetchrow(
            """
            SELECT 1
            FROM pg_class c
            JOIN pg_namespace n ON c.relnamespace = n.oid
            WHERE n.nspname = $1
              AND c.relname = $2
              AND c.relkind IN ('m', 'r')
            """,
            SCHEMA,
            view_name,
        )
        return row is not None
    finally:
        await conn.close()


async def has_unique_index_on_id(view_name: str) -> bool:
    """True iff sqlonfhir.<view_name> has a UNIQUE INDEX on the `id` column.

    Required for REFRESH MATERIALIZED VIEW CONCURRENTLY (Phase 2.0). Without
    it, refresh takes an exclusive lock that blocks readers. Issue #13
    decision 8A wires this into materialize_views.py; this helper lets the
    harness verify the wiring stays correct under future refactors.
    """
    conn = await asyncpg.connect(HAPI_DB_URL)
    try:
        row = await conn.fetchrow(
            """
            SELECT 1
            FROM pg_indexes pi
            JOIN pg_class c ON c.relname = pi.indexname
            JOIN pg_index i ON i.indexrelid = c.oid
            WHERE pi.schemaname = $1
              AND pi.tablename = $2
              AND i.indisunique
              AND pi.indexdef ILIKE '%(id)'
            """,
            SCHEMA,
            view_name,
        )
        return row is not None
    finally:
        await conn.close()


async def materialized_columns(view_name: str) -> set[str]:
    """Names of columns present in the materialized view (empty set if view missing).

    Uses pg_attribute, NOT information_schema.columns. Postgres' information_schema
    intentionally excludes materialized views from the columns view (they're
    relkind='m', not 'v' or 'r'), so info_schema returns an empty set even for
    materialized views with columns. pg_attribute joined with pg_class works for
    every relkind including matviews. Caught during cycle 2 RED.
    """
    conn = await asyncpg.connect(HAPI_DB_URL)
    try:
        rows = await conn.fetch(
            """
            SELECT a.attname
            FROM pg_attribute a
            JOIN pg_class c ON a.attrelid = c.oid
            JOIN pg_namespace n ON c.relnamespace = n.oid
            WHERE n.nspname = $1
              AND c.relname = $2
              AND a.attnum > 0
              AND NOT a.attisdropped
            """,
            SCHEMA,
            view_name,
        )
        return {r["attname"] for r in rows}
    finally:
        await conn.close()


async def query_count(view_name: str) -> int:
    """COUNT(*) of the materialized view. Raises asyncpg.UndefinedTableError if missing."""
    conn = await asyncpg.connect(HAPI_DB_URL)
    try:
        row = await conn.fetchrow(f"SELECT COUNT(*) AS c FROM {SCHEMA}.{view_name}")
        return row["c"]
    finally:
        await conn.close()


def transpiled_sql(view_def: dict) -> str:
    """The SQL the production builder generates for a view def, without executing.

    Wraps app.sql_on_fhir.query_builder.create_sql_query_builder so the parse-only
    check exercises the same code path as scripts/materialize_views.py. Returns
    the SELECT body only — caller wraps in EXPLAIN or CREATE MATERIALIZED VIEW.
    """
    from app.sql_on_fhir.query_builder import create_sql_query_builder
    from app.sql_on_fhir.transpiler import (
        create_column_extractor,
        create_fhirpath_transpiler,
    )

    transpiler = create_fhirpath_transpiler()
    extractor = create_column_extractor(transpiler)
    builder = create_sql_query_builder(transpiler, extractor)
    return builder.build_query(view_definition=view_def).sql


async def execute_select(sql: str, limit: int = 100) -> list[dict]:
    """Execute a transpiled SELECT against HAPI and return rows as dicts.

    Used for regression tests on transpiler behavior that produces parseable
    BUT semantically wrong SQL (e.g., Bug 3 — array-position swap returns
    NULL instead of erroring). Adds LIMIT to keep regression tests fast.
    """
    conn = await asyncpg.connect(HAPI_DB_URL)
    try:
        rows = await conn.fetch(f"SELECT * FROM ({sql}) AS t LIMIT {limit}")
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def explain_parses(sql: str) -> tuple[bool, str]:
    """Run EXPLAIN against the SQL; return (is_parseable, error_message_if_not).

    EXPLAIN performs full parse + plan but no execution, so it surfaces every
    SQL syntax error the script's CREATE MATERIALIZED VIEW would hit, without
    actually creating anything.
    """
    conn = await asyncpg.connect(HAPI_DB_URL)
    try:
        await conn.execute(f"EXPLAIN {sql}")
        return True, ""
    except asyncpg.exceptions.PostgresSyntaxError as e:
        return False, str(e)
    finally:
        await conn.close()


async def query_sample(view_name: str, key_col: str, key_val: str) -> dict:
    """Row matching key_col=key_val as a dict; empty dict if no match.

    Empty-dict return is intentional — it's the harness signal that the row
    couldn't be located by its expected key. The most common cause is Bug 1
    (id column emits NULL because the transpiler reads from jsonb->>'id'
    instead of r.fhir_id), which means WHERE id='X' matches zero rows even
    though the patient exists.
    """
    conn = await asyncpg.connect(HAPI_DB_URL)
    try:
        row = await conn.fetchrow(
            f"SELECT * FROM {SCHEMA}.{view_name} WHERE {key_col} = $1 LIMIT 1",
            key_val,
        )
        return dict(row) if row else {}
    finally:
        await conn.close()


def view_def_columns(view_def: dict) -> set[str]:
    """Names of columns declared by the view def's select[*].column[*].name.

    Walks every select element (top-level + forEach blocks) and collects column
    names. Mirrors the SQL-on-FHIR v2 spec where `column` is an ARRAY of
    {name, path, ...} objects (NOT a string — that misread is Bug 9 in
    MaterializedViewRunner.get_schema()).
    """
    names: set[str] = set()
    for select in view_def.get("select", []):
        for col in select.get("column", []):
            name = col.get("name")
            if name:
                names.add(name)
    return names
