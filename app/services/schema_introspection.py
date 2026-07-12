"""Live schema introspection for the sqlonfhir views (Sprint 6.7 #94, ADR 0028
decision 4).

pg_catalog is queried, NOT information_schema: the 4 custom-path materialized
views (relkind='m') do not appear in information_schema.columns (found during
#91). One introspection result feeds BOTH the LLM synthesis prompt's schema
block and (#95) the validator's column-existence rule — the database itself is
the only schema authority, killing the #76 drift class.

Descriptions are enriched from the view-definition JSONs (human-authored
context the catalog can't provide). Missing views raise — a stale/partial
schema block silently reintroduces drift, so failure is loud.
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, FrozenSet, Optional, Tuple

from app.services.sql_validator import ALLOWED_VIEWS

logger = logging.getLogger(__name__)

_VIEW_DEF_DIR = Path(__file__).resolve().parents[1] / "sql_on_fhir" / "view_definitions"

# relkind: 'm' = materialized view (4 custom-path), 'r' = table (3 sqlonfhir-
# engine path — the Sprint 6.4 storage asymmetry), 'v' = plain view (future).
_INTROSPECTION_SQL = """
    SELECT c.relname AS view_name,
           a.attname AS column_name,
           format_type(a.atttypid, a.atttypmod) AS pg_type
    FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid
    WHERE n.nspname = 'sqlonfhir'
      AND c.relkind IN ('m', 'r', 'v')
      AND a.attnum > 0
      AND NOT a.attisdropped
      AND c.relname = ANY($1)
    ORDER BY c.relname, a.attnum
"""


class SchemaIntrospectionError(Exception):
    """An expected view is missing from the live schema."""


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    pg_type: str


@dataclass(frozen=True)
class ViewSchema:
    name: str
    description: str
    columns: Tuple[ColumnInfo, ...]


def _load_view_def_descriptions() -> Dict[str, str]:
    descriptions = {}
    for path in _VIEW_DEF_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text())
            if data.get("name") and data.get("description"):
                descriptions[data["name"]] = data["description"]
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Could not read view-def %s for description: %s", path.name, e)
    return descriptions


async def introspect_schema(
    db_client, view_names: FrozenSet[str] = ALLOWED_VIEWS
) -> Dict[str, ViewSchema]:
    """Read columns + types for the given sqlonfhir views from pg_catalog.

    Raises SchemaIntrospectionError if any expected view is absent — callers
    must never proceed with a partial schema picture.
    """
    rows = await db_client.execute_query(_INTROSPECTION_SQL, params=[list(view_names)])

    columns_by_view: Dict[str, list] = {}
    for row in rows:
        columns_by_view.setdefault(row["view_name"], []).append(
            ColumnInfo(name=row["column_name"], pg_type=row["pg_type"])
        )

    missing = sorted(view_names - columns_by_view.keys())
    if missing:
        raise SchemaIntrospectionError(
            f"expected views absent from live sqlonfhir schema: {', '.join(missing)}"
        )

    descriptions = _load_view_def_descriptions()
    return {
        name: ViewSchema(
            name=name,
            description=descriptions.get(name, ""),
            columns=tuple(cols),
        )
        for name, cols in columns_by_view.items()
    }


_schemas_cache: Optional[Dict[str, ViewSchema]] = None
_cache_lock = asyncio.Lock()


async def get_cached_schemas(db_client) -> Dict[str, ViewSchema]:
    """Process-level cached introspection — ONE result serves both the
    synthesis prompt and the validator's column checks (#95), so the two can
    never diverge. Single-DB assumption: keyed on nothing. Stale after a
    schema-changing MV rebuild until process restart (ADR 0028 deviation
    note); failure mode is loud, not silent-wrong."""
    global _schemas_cache
    if _schemas_cache is None:
        async with _cache_lock:
            if _schemas_cache is None:
                _schemas_cache = await introspect_schema(db_client)
                logger.info(
                    "sqlonfhir schema introspected and cached (%d views)",
                    len(_schemas_cache),
                )
    return _schemas_cache


def reset_schema_cache() -> None:
    global _schemas_cache
    _schemas_cache = None


def render_schema_block(schemas: Dict[str, ViewSchema]) -> str:
    """Render introspected schema as prompt text. Deterministic (sorted) so the
    block is byte-identical across processes — prompt caching keys on content.
    """
    lines = [
        "Available tables (Postgres, schema `sqlonfhir`) — these are the ONLY "
        "tables you may reference. Column types are live-introspected:",
        "",
    ]
    for name in sorted(schemas):
        view = schemas[name]
        lines.append(f"### sqlonfhir.{name}")
        if view.description:
            lines.append(f"{view.description}")
        for col in view.columns:
            lines.append(f"- {col.name} {col.pg_type}")
        lines.append("")
    return "\n".join(lines).rstrip()
