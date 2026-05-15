"""Sprint 6.4 cycle 3 — HAPI internal-Postgres FHIR resource reader.

Reads FHIR resources from HAPI's internal `:5433` Postgres directly,
NOT via the REST API. The filename makes the coupling explicit — a
future REST-based reader would live in a sibling file
(`hapi_rest_resource_reader.py`) at this same module level.

Why direct DB read instead of REST: the Sprint 6.4 60s materialization
gate (issue #40 gate #3) can't absorb HTTP pagination overhead at HAPI
scale (229k Observations, 14,832 Conditions, 66,448 Procedures). Reading
from `hfj_resource` JOIN `hfj_res_ver` is one query per resource type
and parses JSON in-memory, which fits the budget.

Schema couplings encapsulated here (load-bearing if HAPI upgrades):
  - JSON storage lives in `hfj_res_ver.res_text_vc` (text-typed JSON,
    not jsonb), NOT `hfj_resource.res_text_vc` as the 2026-05-15
    architecture review erroneously stated.
  - Resources are reached via JOIN on `res_id + res_ver` (current version
    only; the table tracks versioned history).
  - Soft-deleted resources are excluded via `res_deleted_at IS NULL`.
  - **The canonical FHIR resource ID is on `hfj_resource.fhir_id`, NOT
    in the stored JSON.** The JSON in `res_text_vc` strips the `id`
    field. This function merges `fhir_id` into the parsed dict so
    sqlonfhir's view-def `id` path resolves correctly. Without this
    merge, materialized rows have NULL ids and the UNIQUE INDEX on id
    fails.

Future HAPI upgrades that change any of the above only break this one
function, not the whole materializer flow.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

import asyncpg


async def fetch_fhir_resources_for_view(
    conn: asyncpg.Connection, view_def: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Read FHIR resources from HAPI's internal Postgres for the resource
    type specified in the view-def.

    Args:
        conn: Open asyncpg connection to HAPI Postgres (`:5433` `hapi` db).
        view_def: View-def JSON dict with a `resource` field (e.g.,
            "Condition", "Observation", "Procedure").

    Returns:
        List of parsed FHIR resource dicts, each with `id` merged from
        `hfj_resource.fhir_id` (the JSON stored in HAPI doesn't include
        the id field; this function reconstructs it).
    """
    resource_type = view_def["resource"]
    rows = await conn.fetch(
        """
        SELECT r.fhir_id, v.res_text_vc
        FROM hfj_resource r
        JOIN hfj_res_ver v ON v.res_id = r.res_id AND v.res_ver = r.res_ver
        WHERE r.res_type = $1 AND r.res_deleted_at IS NULL
        """,
        resource_type,
    )
    resources: List[Dict[str, Any]] = []
    for row in rows:
        parsed: Dict[str, Any] = json.loads(row["res_text_vc"])
        parsed["id"] = row["fhir_id"]  # canonical id merge — load-bearing
        resources.append(parsed)
    return resources
