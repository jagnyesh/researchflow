"""Phase 1.1 transpiler correctness harness (issue #9).

Each test in this file produces a per-view PASS/FAIL signal that the
Phase 1.5 correctness gate consumes. The harness is built TDD-style;
production view defs are parametrized in cycle 6 once cycles 1-5 prove
the five check categories work against patient_simple.

Initial baseline (before Phase 1.2 transpiler bug fixes):
- view_exists:    1/7 PASS (patient_simple only)
- schema_shape:   1/7 PASS
- row_count:      1/7 PASS
- sample_values:  0/7 PASS (Bug 1: id NULL on patient_simple, others not materialized)
- parse_only:     1-2/7 PASS (patient_simple + maybe patient_demographics; others have function-call SQL gaps)

The harness MUST report these baseline failures correctly. A "false PASS"
on Bug 1 would invalidate the Phase 1.5 gate.
"""

import json
from pathlib import Path

import pytest

from tests.fixtures.transpiler_expected_outputs import (
    ANCHOR_EXPECTATIONS,
    NON_ANCHOR_VIEW_DEFS,
)
from tests.transpiler_harness import (
    execute_select,
    explain_parses,
    materialized_columns,
    query_count,
    query_sample,
    transpiled_sql,
    view_def_columns,
    view_exists,
)

VIEW_DEFS_DIR = Path(__file__).parent.parent / "app" / "sql_on_fhir" / "view_definitions"

ANCHOR_VIEW_DEFS = tuple(ANCHOR_EXPECTATIONS.keys())
ALL_VIEW_DEFS = ANCHOR_VIEW_DEFS + NON_ANCHOR_VIEW_DEFS


def _load_view_def(name: str) -> dict:
    return json.loads((VIEW_DEFS_DIR / f"{name}.json").read_text())


# ---------------------------------------------------------------------------
# Per-check tests, parametrized over all 7 view defs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("view_name", ALL_VIEW_DEFS)
async def test_view_exists(view_name, materialized_views):
    """Cycle 1+6: view materialized in pg_matviews. FAIL → 'view-not-yet-materialized'."""
    assert await view_exists(view_name), f"view-not-yet-materialized: sqlonfhir.{view_name}"


@pytest.mark.asyncio
@pytest.mark.parametrize("view_name", ALL_VIEW_DEFS)
async def test_schema_shape(view_name, materialized_views):
    """Cycle 2+6: MV's columns must be a superset of the view def's column names."""
    assert await view_exists(view_name), f"view-not-yet-materialized: sqlonfhir.{view_name}"
    expected = view_def_columns(_load_view_def(view_name))
    actual = await materialized_columns(view_name)
    missing = expected - actual
    assert not missing, f"{view_name} MV missing columns from view def: {missing}"


@pytest.mark.asyncio
@pytest.mark.parametrize("view_name", ANCHOR_VIEW_DEFS)
async def test_row_count_anchor(view_name, materialized_views):
    """Cycle 3+6 (anchors only): COUNT(*) matches fixture's hand-verified expected_row_count.

    Limited to anchor view defs — non-anchors don't have hand-verified expected
    counts in the fixture (they'd need InMemoryRunner derivation, which we
    haven't generated yet). Add non-anchor row counts if/when needed.
    """
    assert await view_exists(view_name), f"view-not-yet-materialized: sqlonfhir.{view_name}"
    expected = ANCHOR_EXPECTATIONS[view_name]["expected_row_count"]
    actual = await query_count(view_name)
    assert (
        actual == expected
    ), f"{view_name} row count {actual} != fixture's hand-verified {expected}"


def _anchor_sample_params() -> list[tuple[str, str]]:
    """(view_name, key_val) pairs for every sample patient in every anchor."""
    pairs = []
    for view_name, anchor in ANCHOR_EXPECTATIONS.items():
        for key_val in anchor["sample_rows"]:
            pairs.append((view_name, key_val))
    return pairs


@pytest.mark.asyncio
@pytest.mark.parametrize("view_name,key_val", _anchor_sample_params())
async def test_sample_values_anchor(view_name, key_val, materialized_views):
    """Cycle 4+6 (anchors only): per-field comparison vs hand-verified fixture.

    EXPECTED to FAIL today across all anchor samples — Bug 1 (id NULL) means
    the WHERE id=$1 filter matches no rows. The harness CORRECTLY surfacing
    this is the GREEN signal. Issue #10 fix flips these to PASS.
    """
    assert await view_exists(view_name), f"view-not-yet-materialized: sqlonfhir.{view_name}"
    anchor = ANCHOR_EXPECTATIONS[view_name]
    expected_row = anchor["sample_rows"][key_val]
    actual = await query_sample(view_name, anchor["key_column"], key_val)

    assert actual, (
        f"No row found in {view_name} WHERE {anchor['key_column']}={key_val!r}. "
        "Likely Bug 1 manifestation (id NULL) or upstream materialization failure."
    )

    mismatches = {
        k: {"expected": expected_row[k], "actual": actual.get(k)}
        for k in expected_row
        if expected_row[k] != actual.get(k)
    }
    assert not mismatches, f"Field mismatches for {view_name}/{key_val}:\n" + "\n".join(
        f"  {k}: expected={v['expected']!r}, actual={v['actual']!r}" for k, v in mismatches.items()
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("view_name", ALL_VIEW_DEFS)
async def test_parse_only(view_name, materialized_views):
    """Cycle 5+6: transpiler emits SQL that postgres can EXPLAIN.

    Independent of materialization — surfaces function-call bugs (4, 5, 6)
    that produce SQL with stray characters.
    """
    sql = transpiled_sql(_load_view_def(view_name))
    ok, err = await explain_parses(sql)
    assert ok, f"{view_name} SQL did not parse: {err}\nGenerated SQL:\n{sql}"


# ---------------------------------------------------------------------------
# Cycle 7: Bug 3 regression test (synthetic inline view def)
#
# None of the 7 production view defs use plain `name.X` paths outside forEach
# blocks, so Bug 3 (lines 139-146 of fhirpath_transpiler.py — array-position
# swap) wouldn't surface in the parametrized tests above. The bug produces
# SQL that PARSES but returns NULL because `->0` runs against the resource
# OBJECT instead of the `name` ARRAY. This test catches that explicitly.
#
# /grill-with-docs harness-fidelity audit caught the gap (Bug 3 not reachable
# from existing anchors). Per the user-confirmed strategy: synthetic test
# instead of polluting production view defs (option A).
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Bug 9 regression: MVR.get_schema() v2-spec compliance
#
# /cso audit on f5e2b0f caught this coverage gap: the rest of the harness uses
# its own materialized_columns() and view_def_columns() helpers, both of which
# bypass MaterializedViewRunner.get_schema() entirely. A wrong fix to
# MVR.get_schema() in issue #13 would PASS the rest of the harness while
# silently producing garbage for app/api/analytics.py:294 and :511 which
# consume the runner's schema directly. This test exercises MVR.get_schema()
# directly, against the same column-set the harness already trusts.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("view_name", ALL_VIEW_DEFS)
def test_mvr_get_schema_matches_view_def(view_name):
    """Bug 9 regression: MVR.get_schema() must return columns matching the view def.

    EXPECTED to FAIL today across all 7 view defs — current implementation
    expects `column` to be a string but the v2 spec defines it as an array,
    so the function returns {} for every view def. Issue #13 fix flips this
    to PASS.

    Sync test (get_schema is sync, doesn't touch db_client — see line 202+
    of materialized_view_runner.py). No fixture dependency.
    """
    from app.sql_on_fhir.runner.materialized_view_runner import MaterializedViewRunner

    vd = _load_view_def(view_name)
    expected = view_def_columns(vd)
    runner = MaterializedViewRunner(db_client=None)
    actual = set(runner.get_schema(vd).keys())
    missing = expected - actual
    assert not missing, (
        f"MVR.get_schema() returned {actual} for {view_name}; "
        f"missing {missing} from view def's column declarations. "
        f"Production callsites at app/api/analytics.py:294 + :511 silently "
        f"consume this empty/incomplete result."
    )


@pytest.mark.asyncio
async def test_bug3_array_position_regression():
    """Bug 3 regression: plain `name.family` (no forEach) must yield real text, not NULL.

    EXPECTED to FAIL today — transpiler emits `jsonb->0->'name'->>'family'`
    which evaluates ->0 on the resource object (NULL) and propagates NULL.
    Should emit `jsonb->'name'->0->>'family'` instead (access name array
    first, then element 0).

    Issue #11 (mechanical bug cluster) flips this to PASS.
    """
    inline_vd = {
        "resourceType": "ViewDefinition",
        "resource": "Patient",
        "name": "synthetic_bug3_regression",
        "select": [
            {
                "column": [
                    {"name": "family_via_plain_path", "path": "name.family"},
                ]
            }
        ],
    }
    sql = transpiled_sql(inline_vd)
    rows = await execute_select(sql, limit=20)

    non_null = [r["family_via_plain_path"] for r in rows if r["family_via_plain_path"] is not None]
    assert non_null, (
        "Bug 3 manifestation: every row's family_via_plain_path is NULL. "
        "Transpiler emits ->0 BEFORE ->'name' "
        "(fhirpath_transpiler.py:139-146); should be ->'name'->0->>'family'.\n"
        f"Generated SQL:\n{sql}"
    )
