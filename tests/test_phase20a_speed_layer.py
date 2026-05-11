"""Phase 2.0a tests (issue #17) — FHIRSubscriptionService speed layer.

Verifies the production behavior the speed-layer polling needs to provide:
- Default poll interval matches the README's "<1 minute freshness" claim
- Cache keys use FHIR logical id (not HAPI internal res_id) so downstream
  consumers (HybridRunner, SpeedLayerRunner) can match against materialized
  view rows
- Class docstring describes polling as the production pattern, not "mock"
"""

import os
from datetime import datetime, timedelta

import pytest

from app.cache.redis_client import RedisClient
from app.clients.hapi_db_client import HAPIDBClient
from app.services.fhir_subscription_service import FHIRSubscriptionService


def test_poll_interval_default_under_60_seconds():
    """The Lambda Architecture's <1 minute freshness claim requires polling
    at least once per minute. Default was 5 minutes (300s) — too coarse to
    back the README claim. Issue #17 drops to 30s to give margin.
    """
    svc = FHIRSubscriptionService(hapi_client=None, redis_client=None)
    # Convert whatever unit the implementation uses to seconds for assertion.
    # The constructor previously took poll_interval_minutes; this assertion
    # forces the default to a sub-minute value regardless of the unit.
    interval_seconds = getattr(svc, "poll_interval_seconds", None)
    if interval_seconds is None:
        # Backward-compat: previous attribute was poll_interval (minutes)
        interval_minutes = getattr(svc, "poll_interval", None)
        interval_seconds = interval_minutes * 60 if interval_minutes else None
    assert interval_seconds is not None and interval_seconds <= 60, (
        f"Default poll interval is {interval_seconds}s; needs to be <=60s for "
        f"the Lambda speed-layer <1-minute-freshness guarantee."
    )


@pytest.mark.asyncio
async def test_polling_caches_patients_by_fhir_id():
    """Production callsite contract: after polling, Redis contains an entry
    keyed by the patient's FHIR logical id (not HAPI's internal res_id bigint).

    Without this fix, downstream HybridRunner can't merge cache results with
    materialized-view results because the cache uses internal-IDs while MVs
    use FHIR IDs (Bug 1 territory). The merge silently misses everything.

    Picks the most-recent-updated patient in HAPI as the assertion target
    (rather than a hardcoded id) so the test works regardless of which 100
    patients the LIMIT clause returns.
    """
    hapi_url = os.getenv("HAPI_DB_URL", "postgresql://hapi:hapi@localhost:5433/hapi")
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/2")  # DB 2 for this test

    hapi = HAPIDBClient(hapi_url)
    redis = RedisClient(redis_url=redis_url)
    await redis.connect()
    await redis.flush_all()  # clean slate

    # Find the most-recently-updated patient — that's guaranteed to be in the
    # LIMIT 100 window the polling SQL uses.
    rows = await hapi.execute_query(
        "SELECT fhir_id FROM hfj_resource WHERE res_type='Patient' "
        "ORDER BY res_updated DESC LIMIT 1"
    )
    target_fhir_id = rows[0]["fhir_id"]

    svc = FHIRSubscriptionService(hapi_client=hapi, redis_client=redis)
    # Force a backstop window large enough to cover the existing dataset
    svc.last_sync_time = datetime.utcnow() - timedelta(days=365 * 5)

    await svc._poll_and_cache()

    cached = await redis.get_fhir_resource("Patient", target_fhir_id)
    assert cached is not None, (
        f"Cache MISS for fhir:patient:{target_fhir_id} after polling. The service "
        f"is still writing keys with HAPI's internal res_id bigint instead of "
        f"fhir_id, so downstream consumers can't find resources by their FHIR "
        f"logical id."
    )

    # Regression for the e2e bug found pre-#20: HAPI strips `id` from the JSON
    # body it stores in res_text_vc. If the service doesn't augment the resource
    # dict with `id = fhir_id` before caching, downstream HybridRunner's merge
    # extracts id=None for every cache row, breaking dedup-by-id (silent failure
    # — produces duplicates in merged results without any error message).
    cached_resource = cached.get("resource", cached)
    assert cached_resource.get("id") == target_fhir_id, (
        f"Cached resource missing 'id' field (got {cached_resource.get('id')!r}). "
        f"HAPI strips id from JSON; FHIRSubscriptionService must augment the "
        f"resource dict with id=fhir_id before caching, or downstream merge "
        f"dedup breaks silently."
    )
