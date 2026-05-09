"""Phase 2.1 tests (issue #19) — HybridRunner merge + dedup.

Verifies the merge contract that the Lambda Architecture's "fresher wins"
guarantee depends on. The merge code path was a no-op before #19 (returned
batch_result unchanged); these tests pin the new behavior so future
refactors can't silently regress it.

Decision 9A (Redis access pattern): HSET keyed by `fhir:<type>:<id>`. This
is what RedisClient already implements and what FHIRSubscriptionService
writes to (issue #17). The sorted-set-with-versionId-score alternative
would be needed for time-range scans by recency; the current architecture
doesn't need that. Documented as resolved in TODOS.md.
"""

from unittest.mock import AsyncMock

import pytest


def _patient_resource(fhir_id: str, gender: str = "female") -> dict:
    """Minimal Patient resource for tests."""
    return {
        "resourceType": "Patient",
        "id": fhir_id,
        "gender": gender,
        "birthDate": "1990-01-01",
    }


def _patient_view_def() -> dict:
    """Minimal Patient view def for tests — id + gender, no forEach."""
    return {
        "resourceType": "ViewDefinition",
        "resource": "Patient",
        "name": "test_patient",
        "select": [
            {
                "column": [
                    {"name": "id", "path": "id"},
                    {"name": "gender", "path": "gender"},
                ]
            }
        ],
    }


def _make_runner_for_merge_only():
    """Construct a HybridRunner suitable for testing _merge_batch_and_speed_results
    in isolation, without real Redis/HAPI dependencies."""
    from app.sql_on_fhir.runner.hybrid_runner import HybridRunner

    runner = HybridRunner.__new__(HybridRunner)
    runner.use_speed_layer = True
    return runner


def test_merge_empty_cache_returns_batch_unchanged():
    """When speed cache has no resources for this view, batch_result passes
    through. Asserts the no-merge-overhead path still works."""
    runner = _make_runner_for_merge_only()
    batch = [{"id": "1", "gender": "female"}]
    speed = {"total_count": 0, "resources": []}

    merged = runner._merge_batch_and_speed_results(batch, speed, _patient_view_def())

    assert merged == batch, f"Empty cache must pass batch through unchanged; got {merged!r}"


def test_merge_cache_only_returns_extracted_rows():
    """When batch is empty but cache has resources, merge returns rows
    extracted from cache resources via the view def's column structure."""
    runner = _make_runner_for_merge_only()
    batch = []
    speed = {
        "total_count": 1,
        "resources": [_patient_resource("142387", "female")],
    }

    merged = runner._merge_batch_and_speed_results(batch, speed, _patient_view_def())

    assert len(merged) == 1, f"Cache-only merge should return 1 row; got {merged!r}"
    assert merged[0].get("id") == "142387"
    assert merged[0].get("gender") == "female"


def test_merge_dedup_cache_wins_on_id_collision():
    """Critical contract: when batch + cache both contain the same resource id,
    the cache version wins. Cache is fresher by definition (just polled)."""
    runner = _make_runner_for_merge_only()
    # Batch has the OLD version (gender=male)
    batch = [
        {"id": "142387", "gender": "male"},  # Stale
        {"id": "999", "gender": "female"},  # Cache doesn't have this one
    ]
    # Cache has the FRESH version (gender=female — pretend it changed)
    speed = {
        "total_count": 1,
        "resources": [_patient_resource("142387", "female")],
    }

    merged = runner._merge_batch_and_speed_results(batch, speed, _patient_view_def())

    # Should have exactly 2 rows: the cache version of 142387, plus 999 from batch
    ids_in_merged = sorted(row.get("id") for row in merged)
    assert ids_in_merged == [
        "142387",
        "999",
    ], f"Expected dedup to one row per id; got {ids_in_merged}"

    # The 142387 row should be the cache version (gender=female), not batch (male)
    row_142387 = next(r for r in merged if r.get("id") == "142387")
    assert (
        row_142387.get("gender") == "female"
    ), f"Cache version should win on id collision; got batch version: {row_142387!r}"


def test_merge_appends_cache_only_resources_to_batch():
    """When cache has resources NOT in batch, merge appends them."""
    runner = _make_runner_for_merge_only()
    batch = [{"id": "1", "gender": "male"}]
    speed = {
        "total_count": 2,
        "resources": [
            _patient_resource("2", "female"),
            _patient_resource("3", "male"),
        ],
    }

    merged = runner._merge_batch_and_speed_results(batch, speed, _patient_view_def())

    ids_in_merged = sorted(row.get("id") for row in merged)
    assert ids_in_merged == [
        "1",
        "2",
        "3",
    ], f"Expected all 3 ids in merged result; got {ids_in_merged}"
