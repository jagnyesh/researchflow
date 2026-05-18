#!/usr/bin/env python3
"""Sprint 6.5 close gate (#72) — empirical evidence run.

Pre-committed gate criteria pin Sprint 6.5's load-bearing architectural
claim: three FreshnessAnnotation modes route through HybridRunner with
three distinct behaviors AND LangSmith cross-correlates with the
Postgres metric row.

Six assertions, each emitted as one row to logs/sprint_6_5_gate.jsonl:

  exploratory_row_count    — EXPLORATORY count == N + 5 (speed-merged)
  formal_draft_row_count   — FORMAL_DRAFT count == N + 5 (speed-merged)
  formal_draft_freshness   — freshness_delta_seconds < 90 (recent refresh)
  formal_extraction_count  — FORMAL_EXTRACTION count == N (batch-only, no merge)
  formal_extraction_anchor — batch_anchor_ts matches mv_refresh_metadata
  langsmith_cross_correlation — Postgres trace_id resolves; metadata mirrors

ASSUMPTION: MVs do not refresh during gate execution window.
Today this holds because materialize_views.py runs manually (no cron,
no autorefresh). If a future contributor wires autorefresh, the gate
may observe a batch refresh mid-execution. FORMAL_EXTRACTION would
see N+5 instead of N, producing false failure. If adding autorefresh,
also add gate isolation.

ASSUMPTION: FHIRSubscriptionService keys Redis by FHIR fhir_id, NOT
HAPI internal res_id. Verified at fhir_subscription_service.py:170
(set_fhir_resource(resource_type, fhir_id, ...)). Issue #74 documents
that the existing test in tests/test_phase20a_speed_layer.py asserts
this incorrectly under specific conditions (soft-deleted patients),
not a production bug.

Usage:
    python scripts/sprint_6_5_gate.py

    # → writes logs/sprint_6_5_gate.jsonl with one row per assertion
    # → exits 0 on all-pass, 1 on any blocking failure
    # → does NOT clean up the 5 synthetic patients it writes
       (one-shot empirical evidence run, not a unit test)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess  # nosec B404 — only used with sys.executable + literal arg lists; no shell, no untrusted input
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.cache.redis_client import RedisClient
from app.clients.hapi_db_client import HAPIDBClient
from app.services.fhir_subscription_service import FHIRSubscriptionService
from app.sql_on_fhir.runner.freshness import FreshnessAnnotation
from app.sql_on_fhir.runner.hybrid_runner import HybridRunner
from app.sql_on_fhir.view_definition_manager import ViewDefinitionManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("sprint_6_5_gate")

LOG_PATH = PROJECT_ROOT / "logs" / "sprint_6_5_gate.jsonl"
T2DM_SNOMED = "44054006"
N_WRITES = 5
POLL_TIMEOUT_S = 60
FRESHNESS_MAX_SECONDS = 90


def emit(row: Dict[str, Any]) -> None:
    """Append one JSON line to the gate's evidence artifact."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    row.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    with LOG_PATH.open("a") as f:
        f.write(json.dumps(row) + "\n")
    severity = row.get("severity", "info").upper()
    logger.info(
        f"[{severity}] {row['dimension']}: expected={row.get('expected')!r} "
        f"observed={row.get('observed')!r}"
    )


def assert_row(
    dimension: str, condition: bool, expected: Any, observed: Any, note: str = ""
) -> bool:
    """Record one assertion row. Returns True if pass, False if blocking."""
    severity = "pass" if condition else "blocking"
    emit(
        {
            "dimension": dimension,
            "expected": expected,
            "observed": observed,
            "severity": severity,
            "note": note,
        }
    )
    return condition


def count_t2dm_rows(rows: List[Dict[str, Any]]) -> int:
    """Count rows where snomed_code == T2DM. The gate filters Python-side
    because condition_simple doesn't have a snomed_code search_param."""
    return sum(1 for r in rows if r.get("snomed_code") == T2DM_SNOMED)


async def run_materialize_refresh() -> None:
    """Reset batch_anchor_ts to NOW by running scripts/materialize_views.py
    --refresh. Subprocess invocation keeps lifecycle simple."""
    logger.info("Step 1/7: Refreshing MVs to reset batch_anchor_ts...")
    result = subprocess.run(  # nosec B603 — fixed cmd, no shell, no untrusted input
        [sys.executable, "scripts/materialize_views.py", "--refresh"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.error(f"MV refresh failed: {result.stderr[:500]}")
        raise RuntimeError("MV refresh failed; gate cannot proceed")
    logger.info("  ✅ MVs refreshed")


async def run_writer() -> List[str]:
    """Fire drive_fhir_traffic.py one-shot. Returns list of new patient
    fhir_ids that were written."""
    logger.info(
        f"Step 3/7: Writing {N_WRITES} synthetic t2dm patients via drive_fhir_traffic.py..."
    )
    result = subprocess.run(  # nosec B603 — fixed cmd, no shell, no untrusted input
        [
            sys.executable,
            "scripts/drive_fhir_traffic.py",
            "--cohort=t2dm",
            f"--count={N_WRITES}",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.error(f"Writer failed: {result.stderr[:500]}")
        raise RuntimeError("drive_fhir_traffic failed; gate cannot proceed")

    # Parse for the patient ids the writer logged. drive_fhir_traffic.py
    # uses logging which writes to stderr by default — check both streams.
    patient_ids: List[str] = []
    for line in (result.stdout + result.stderr).splitlines():
        # Format: "[1/5] POST'd Patient/807970 + Condition/807971 + Observation/807972"
        if "POST'd Patient/" in line:
            try:
                pid = line.split("POST'd Patient/")[1].split(" ")[0]
                patient_ids.append(pid)
            except IndexError:
                pass
    logger.info(f"  ✅ Wrote {len(patient_ids)} patients: {patient_ids}")
    return patient_ids


async def force_subscription_poll(hapi: HAPIDBClient, redis: RedisClient) -> None:
    """Force FHIRSubscriptionService to poll HAPI for recent writes and
    mirror them into Redis. Production runs this on a 30s timer; gate
    invokes it directly for determinism."""
    logger.info("Step 4/7: Forcing FHIRSubscriptionService poll to mirror writes into Redis...")
    svc = FHIRSubscriptionService(hapi_client=hapi, redis_client=redis)
    svc.last_sync_time = datetime.utcnow() - timedelta(minutes=5)
    await svc._poll_and_cache()
    logger.info("  ✅ Polling complete")


async def wait_for_keys_in_redis(redis: RedisClient, patient_ids: List[str]) -> bool:
    """After polling, verify the new patient + condition keys are in Redis."""
    logger.info("Step 5/7: Verifying Redis cache contains the new resources...")
    deadline = time.time() + POLL_TIMEOUT_S
    while time.time() < deadline:
        missing = []
        for pid in patient_ids:
            cached = await redis.get_fhir_resource("Patient", pid)
            if cached is None:
                missing.append(pid)
        if not missing:
            logger.info(f"  ✅ All {len(patient_ids)} patient keys present in Redis")
            return True
        await asyncio.sleep(2)
    logger.warning(f"  ⚠ Timeout: still missing {len(missing)}/{len(patient_ids)} keys: {missing}")
    return False


async def run_gate() -> int:
    """Returns shell exit code: 0 on all-pass, 1 on any blocking failure."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Truncate previous gate run for cleanliness — only the most recent run's
    # evidence matters for "did this gate pass."
    LOG_PATH.unlink(missing_ok=True)
    emit({"dimension": "gate_started", "expected": "ok", "observed": "ok", "severity": "info"})

    blockers = 0

    # Step 1: Reset batch_anchor_ts via materialize_views.py --refresh
    await run_materialize_refresh()

    # Step 2: Construct HybridRunner + load view-def
    logger.info("Step 2/7: Constructing HybridRunner + loading condition_simple view-def...")
    hapi_url = os.getenv("HAPI_DB_URL", "postgresql://hapi:hapi@localhost:5433/hapi").replace(
        "postgresql+asyncpg://", "postgresql://"
    )
    hapi = HAPIDBClient(connection_url=hapi_url)
    await hapi.connect()
    redis = RedisClient(redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/1"))
    await redis.connect()
    hybrid = HybridRunner(db_client=hapi, redis_client=redis, enable_cache=False)
    view_def = ViewDefinitionManager().load("condition_simple")
    logger.info("  ✅ Clients + view-def ready")

    # Baseline count via EXPLORATORY mode (so the metric row gets the
    # caller='sprint_6_5_gate' attribution from the very first call)
    baseline_rows = await hybrid.execute(
        view_definition=view_def,
        search_params={},
        max_resources=None,
        mode=FreshnessAnnotation.EXPLORATORY,
        caller="sprint_6_5_gate",
    )
    baseline_count = count_t2dm_rows(baseline_rows)
    logger.info(f"  📊 Baseline t2dm count: N = {baseline_count}")

    # Step 3: Fire the writer
    patient_ids = await run_writer()
    if len(patient_ids) != N_WRITES:
        emit(
            {
                "dimension": "writer_output",
                "expected": f"{N_WRITES} patients",
                "observed": f"{len(patient_ids)} patients",
                "severity": "blocking",
            }
        )
        blockers += 1
        return 1

    # Step 4 + 5: Force poll + verify Redis state
    await force_subscription_poll(hapi, redis)
    keys_present = await wait_for_keys_in_redis(redis, patient_ids)
    if not assert_row(
        "redis_speed_layer_seeded",
        keys_present,
        f"all {N_WRITES} patient keys",
        "present" if keys_present else "missing",
    ):
        blockers += 1

    # Step 6: Three-mode assertions
    logger.info("Step 6/7: Three-mode assertions...")
    expected_with_merge = baseline_count + N_WRITES

    # EXPLORATORY: speed-merged
    explor_rows = await hybrid.execute(
        view_definition=view_def,
        search_params={},
        max_resources=None,
        mode=FreshnessAnnotation.EXPLORATORY,
        caller="sprint_6_5_gate",
    )
    explor_count = count_t2dm_rows(explor_rows)
    if not assert_row(
        "exploratory_row_count",
        explor_count == expected_with_merge,
        expected_with_merge,
        explor_count,
        note=f"EXPLORATORY should speed-merge the {N_WRITES} new t2dm patients",
    ):
        blockers += 1

    # FORMAL_DRAFT: speed-merged + metadata
    fd_rows = await hybrid.execute(
        view_definition=view_def,
        search_params={},
        max_resources=None,
        mode=FreshnessAnnotation.FORMAL_DRAFT,
        caller="sprint_6_5_gate",
    )
    fd_count = count_t2dm_rows(fd_rows)
    if not assert_row(
        "formal_draft_row_count",
        fd_count == expected_with_merge,
        expected_with_merge,
        fd_count,
        note="FORMAL_DRAFT should also speed-merge (same as EXPLORATORY)",
    ):
        blockers += 1

    anchor = hybrid.get_last_batch_anchor_ts()
    fd_freshness = (
        int((datetime.now(timezone.utc) - anchor).total_seconds())
        if anchor and anchor.tzinfo
        else (int((datetime.now() - anchor).total_seconds()) if anchor else -1)
    )
    if not assert_row(
        "formal_draft_freshness",
        anchor is not None and 0 <= fd_freshness < FRESHNESS_MAX_SECONDS,
        f"0 <= freshness_delta_seconds < {FRESHNESS_MAX_SECONDS}",
        fd_freshness,
        note="MV refresh happened in step 1; gate ran shortly after",
    ):
        blockers += 1

    # FORMAL_EXTRACTION: batch only
    fe_rows = await hybrid.execute(
        view_definition=view_def,
        search_params={},
        max_resources=None,
        mode=FreshnessAnnotation.FORMAL_EXTRACTION,
        caller="sprint_6_5_gate",
    )
    fe_count = count_t2dm_rows(fe_rows)
    if not assert_row(
        "formal_extraction_count",
        fe_count == baseline_count,
        baseline_count,
        fe_count,
        note="FORMAL_EXTRACTION must skip speed-merge; result is the MV snapshot",
    ):
        blockers += 1

    fe_anchor = hybrid.get_last_batch_anchor_ts()
    expected_max = await hapi.execute_scalar(
        "SELECT MAX(refreshed_at) FROM sqlonfhir.mv_refresh_metadata WHERE view_name = $1",
        ["condition_simple"],
    )
    if not assert_row(
        "formal_extraction_anchor",
        fe_anchor == expected_max,
        str(expected_max),
        str(fe_anchor),
        note="FORMAL_EXTRACTION anchor must match latest mv_refresh_metadata entry",
    ):
        blockers += 1

    # Step 7: LangSmith cross-correlation
    logger.info("Step 7/7: LangSmith cross-correlation...")
    if not os.getenv("LANGCHAIN_API_KEY"):
        emit(
            {
                "dimension": "langsmith_cross_correlation",
                "expected": "queryable",
                "observed": "LANGCHAIN_API_KEY not set; skipped",
                "severity": "skipped",
            }
        )
    else:
        # Find the most recent FORMAL_DRAFT row from this gate run
        row = await hapi.execute_query(
            """
            SELECT trace_id, mode, freshness_delta_seconds, speed_layer_hit
            FROM sqlonfhir.hybrid_runner_metrics
            WHERE caller = 'sprint_6_5_gate' AND mode = 'formal_draft'
            ORDER BY id DESC LIMIT 1
            """
        )
        if not row or row[0]["trace_id"] is None:
            assert_row(
                "langsmith_trace_id_present",
                False,
                "non-null trace_id in Postgres metric row",
                "None" if row else "no rows",
            )
            blockers += 1
        else:
            metric_row = row[0]
            from langsmith import Client as LangSmithClient

            client = LangSmithClient()
            ls_run = None
            deadline = time.time() + 5
            while time.time() < deadline:
                try:
                    ls_run = client.read_run(metric_row["trace_id"])
                    if ls_run is not None:
                        break
                except Exception:
                    pass
                await asyncio.sleep(0.5)

            if ls_run is None:
                assert_row(
                    "langsmith_run_queryable",
                    False,
                    "run queryable within 5s",
                    "timeout",
                    note=f"trace_id={metric_row['trace_id']}",
                )
                blockers += 1
            else:
                extra = getattr(ls_run, "extra", {}) or {}
                meta = extra.get("metadata", {}) if isinstance(extra, dict) else {}
                ls_mode = meta.get("hybrid_runner.mode")
                ls_freshness = meta.get("hybrid_runner.freshness_delta_seconds")
                ls_hit = meta.get("hybrid_runner.speed_layer_hit")

                correlation_ok = (
                    ls_mode == metric_row["mode"]
                    and ls_freshness == metric_row["freshness_delta_seconds"]
                    and ls_hit == metric_row["speed_layer_hit"]
                )
                if not assert_row(
                    "langsmith_cross_correlation",
                    correlation_ok,
                    {
                        "mode": metric_row["mode"],
                        "freshness_delta_seconds": metric_row["freshness_delta_seconds"],
                        "speed_layer_hit": metric_row["speed_layer_hit"],
                    },
                    {
                        "mode": ls_mode,
                        "freshness_delta_seconds": ls_freshness,
                        "speed_layer_hit": ls_hit,
                    },
                ):
                    blockers += 1

    # Final emit + cleanup
    emit(
        {
            "dimension": "gate_completed",
            "expected": "0 blocking",
            "observed": f"{blockers} blocking",
            "severity": "pass" if blockers == 0 else "blocking",
        }
    )
    await redis.disconnect()
    await hapi.close()

    if blockers == 0:
        logger.info(f"✅ Sprint 6.5 gate PASSED — {LOG_PATH} captured all assertions")
        return 0
    logger.error(f"❌ Sprint 6.5 gate FAILED — {blockers} blocking; see {LOG_PATH}")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run_gate()))
