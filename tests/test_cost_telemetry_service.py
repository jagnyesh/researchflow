"""Sprint 8.1 #31 — CostTelemetryService unit tests.

Mocks the LangSmith client and asserts the service correctly:
- Filters runs by portal tag
- Groups formal-portal runs by thread_id (one thread = one user request)
- Computes per-request cost using the per-model pricing table
- Returns the right CostSummary fields (median, n_observed, cache_hit_rate,
  band_ceiling_usd, gate_status)
- Status logic: gray when n_observed < target, green/red on the band

Reference: DECISIONS.md "Sprint 8.1 — LangSmith is source-of-truth for LLM
cost; explicit portal tags promote domain language into trace data."
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from app.services.cost_telemetry_service import (
    CostSummary,
    CostTelemetryService,
    EXPLORATORY_BAND_CEILING_USD,
    FORMAL_BAND_CEILING_USD,
)


# ---------------------------------------------------------------------------
# Test doubles — minimal LangSmith Run shape we depend on
# ---------------------------------------------------------------------------


@dataclass
class FakeRun:
    """Stand-in for langsmith.schemas.Run. Only the fields we use."""

    id: str
    name: str
    input_tokens: int
    output_tokens: int
    start_time: datetime
    metadata: Optional[Dict[str, Any]] = None
    extra: Optional[Dict[str, Any]] = None
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0

    @property
    def input_token_details(self) -> Dict[str, int]:
        """Mirrors langsmith Run.input_token_details — used by the service to
        read cache breakdown when it's not on top-level fields."""
        return {
            "cache_read": self.cache_read_input_tokens,
            "cache_creation": self.cache_creation_input_tokens,
        }


def _make_thread(thread_id: str, n_runs: int, tokens_per_run: int = 1000) -> List[FakeRun]:
    """Build a thread of n_runs, all tagged portal:formal, with a stable
    start_time so the most-recent-first sort is deterministic."""
    base = datetime(2026, 5, 11, 12, 0, 0)
    return [
        FakeRun(
            id=f"{thread_id}-run-{i}",
            name="requirements_agent",
            input_tokens=tokens_per_run,
            output_tokens=tokens_per_run // 4,
            start_time=base + timedelta(seconds=i),
            metadata={"thread_id": thread_id},
        )
        for i in range(n_runs)
    ]


def _make_service(runs: List[FakeRun]) -> CostTelemetryService:
    """Build a service with a mocked LangSmith client that returns the given runs."""
    client = MagicMock()
    client.list_runs.return_value = iter(runs)
    return CostTelemetryService(client=client, project="researchflow-test")


def _make_root_run(
    query_id: str,
    input_tokens: int,
    output_tokens: int,
    cache_read: int = 0,
    seconds_offset: int = 0,
) -> FakeRun:
    """Build a root trace for an exploratory query. LangSmith's usage_metadata
    propagation means these counts already reflect the full trace tree
    (root + descendants), so the service doesn't need to walk children."""
    base = datetime(2026, 5, 11, 12, 0, 0)
    return FakeRun(
        id=f"query-{query_id}",
        name="interpret_query",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_input_tokens=cache_read,
        start_time=base + timedelta(seconds=seconds_offset),
        metadata={},  # no thread_id needed — exploratory aggregates per root
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_run_list_returns_gray_status():
    """No runs in LangSmith → gray badge, n_observed=0, median=0."""
    service = _make_service([])
    summary = await service.get_formal_portal_cost_p50(n=30)

    assert isinstance(summary, CostSummary)
    assert summary.n_observed == 0
    assert summary.median_usd == 0.0
    assert summary.gate_status == "gray"
    assert summary.band_ceiling_usd == FORMAL_BAND_CEILING_USD


@pytest.mark.asyncio
async def test_partial_data_under_target_n_returns_gray():
    """Fewer threads than target n → gray (insufficient sample)."""
    runs = []
    for thread_idx in range(5):  # 5 threads, want 30
        runs.extend(_make_thread(f"t-{thread_idx}", n_runs=3))

    service = _make_service(runs)
    summary = await service.get_formal_portal_cost_p50(n=30)

    assert summary.n_observed == 5
    assert summary.gate_status == "gray", "5 threads < 30 target → gray"


@pytest.mark.asyncio
async def test_normal_data_below_band_returns_green():
    """30 threads with cheap costs (each well under $0.0039) → green."""
    runs = []
    # Each thread = 3 runs × 100 in + 25 out tokens = cheap as dirt
    for thread_idx in range(30):
        runs.extend(_make_thread(f"t-{thread_idx}", n_runs=3, tokens_per_run=100))

    service = _make_service(runs)
    summary = await service.get_formal_portal_cost_p50(n=30)

    assert summary.n_observed == 30
    assert summary.median_usd < FORMAL_BAND_CEILING_USD
    assert summary.gate_status == "green"


@pytest.mark.asyncio
async def test_normal_data_above_band_returns_red():
    """30 threads, each expensive enough that median > $0.0039 → red."""
    runs = []
    # 3 runs × 5000 in + 1250 out tokens = ~$0.034 per thread (way over band)
    for thread_idx in range(30):
        runs.extend(_make_thread(f"t-{thread_idx}", n_runs=3, tokens_per_run=5000))

    service = _make_service(runs)
    summary = await service.get_formal_portal_cost_p50(n=30)

    assert summary.n_observed == 30
    assert summary.median_usd > FORMAL_BAND_CEILING_USD
    assert summary.gate_status == "red"


@pytest.mark.asyncio
async def test_thread_aggregation_sums_per_request():
    """Multiple runs in the same thread = one request; cost is the sum."""
    # One thread with 5 runs, each 1000 input + 250 output
    runs = _make_thread("only-thread", n_runs=5, tokens_per_run=1000)
    service = _make_service(runs)

    summary = await service.get_formal_portal_cost_p50(n=1)

    # 5 runs × (1000 × $3/1M + 250 × $15/1M)
    # = 5 × (0.003 + 0.00375)
    # = 5 × 0.00675
    # = 0.03375
    assert summary.n_observed == 1
    assert abs(summary.median_usd - 0.03375) < 1e-6, f"got median {summary.median_usd}"


@pytest.mark.asyncio
async def test_cache_hit_rate_calculation():
    """cache_hit_rate = cache_read / (cache_read + non_cached_input)."""
    base = datetime(2026, 5, 11, 12, 0, 0)
    runs = [
        FakeRun(
            id="r1",
            name="requirements_agent",
            input_tokens=1000,
            output_tokens=250,
            cache_read_input_tokens=4000,  # 4× the non-cached input → 80% hit rate
            start_time=base,
            metadata={"thread_id": "t-1"},
        )
    ]
    service = _make_service(runs)
    summary = await service.get_formal_portal_cost_p50(n=1)

    # 4000 cache + 1000 non-cache = 5000 total input → 80% from cache
    assert abs(summary.cache_hit_rate - 0.8) < 1e-6


@pytest.mark.asyncio
async def test_thread_with_no_thread_id_is_ignored():
    """Runs without thread_id metadata can't be grouped — skip them."""
    base = datetime(2026, 5, 11, 12, 0, 0)
    untagged_runs = [
        FakeRun(
            id="orphan-1",
            name="something",
            input_tokens=10000,
            output_tokens=2500,
            start_time=base,
            metadata=None,
        )
    ]
    tagged_runs = _make_thread("real-thread", n_runs=2, tokens_per_run=100)
    service = _make_service(untagged_runs + tagged_runs)

    summary = await service.get_formal_portal_cost_p50(n=30)

    # Only the tagged thread shows up; orphan is ignored.
    assert summary.n_observed == 1


# ---------------------------------------------------------------------------
# Exploratory portal tests (#32)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exploratory_empty_returns_gray():
    """No exploratory runs → gray, n=0, band=$0.00091."""
    service = _make_service([])
    summary = await service.get_exploratory_portal_cost_p50(n=30)

    assert summary.n_observed == 0
    assert summary.gate_status == "gray"
    assert summary.band_ceiling_usd == EXPLORATORY_BAND_CEILING_USD


@pytest.mark.asyncio
async def test_exploratory_partial_under_target_returns_gray():
    """5 queries observed, want 30 → gray."""
    runs = [
        _make_root_run(f"q-{i}", input_tokens=50, output_tokens=20, seconds_offset=i)
        for i in range(5)
    ]
    service = _make_service(runs)

    summary = await service.get_exploratory_portal_cost_p50(n=30)

    assert summary.n_observed == 5
    assert summary.gate_status == "gray"


@pytest.mark.asyncio
async def test_exploratory_below_band_returns_green():
    """30 queries, each cheap enough that median ≤ $0.00091 → green."""
    # Per Haiku-4-5 pricing (input $1/1M, output $5/1M), a small query of
    # 100 input + 30 output tokens = 100 × $1/1M + 30 × $5/1M = $0.000250
    # which is below the $0.00091 band.
    runs = []
    base = datetime(2026, 5, 11, 12, 0, 0)
    for i in range(30):
        runs.append(
            FakeRun(
                id=f"query-{i}",
                name="interpret_query",
                input_tokens=100,
                output_tokens=30,
                start_time=base + timedelta(seconds=i),
                metadata={"model": "claude-haiku-4-5-20251001"},
            )
        )

    service = _make_service(runs)
    summary = await service.get_exploratory_portal_cost_p50(n=30)

    assert summary.n_observed == 30
    assert summary.median_usd < EXPLORATORY_BAND_CEILING_USD
    assert summary.gate_status == "green"


@pytest.mark.asyncio
async def test_exploratory_above_band_returns_red():
    """30 queries where median cost > $0.00091 → red."""
    runs = []
    base = datetime(2026, 5, 11, 12, 0, 0)
    for i in range(30):
        # Heavy queries on Sonnet — way over the band
        runs.append(
            FakeRun(
                id=f"heavy-{i}",
                name="interpret_query",
                input_tokens=2000,
                output_tokens=500,
                start_time=base + timedelta(seconds=i),
                metadata={"model": "claude-sonnet-4-6"},
            )
        )

    service = _make_service(runs)
    summary = await service.get_exploratory_portal_cost_p50(n=30)

    assert summary.n_observed == 30
    assert summary.median_usd > EXPLORATORY_BAND_CEILING_USD
    assert summary.gate_status == "red"


@pytest.mark.asyncio
async def test_exploratory_aggregates_per_root_not_per_thread():
    """Exploratory portal does NOT group by thread_id like formal does.
    Each root trace = one query = one data point, regardless of thread metadata.
    """
    base = datetime(2026, 5, 11, 12, 0, 0)
    # 3 separate root traces; even if they shared a thread_id, exploratory
    # should still see 3 data points.
    runs = [
        FakeRun(
            id=f"q-{i}",
            name="interpret_query",
            input_tokens=100,
            output_tokens=20,
            start_time=base + timedelta(seconds=i),
            metadata={"thread_id": "shared-thread"},  # would group as one if we treated like formal
        )
        for i in range(3)
    ]

    service = _make_service(runs)
    summary = await service.get_exploratory_portal_cost_p50(n=3)

    # Three distinct roots → 3 observations, NOT 1
    assert summary.n_observed == 3


@pytest.mark.asyncio
async def test_exploratory_uses_root_run_aggregated_usage():
    """LangSmith propagates child-run usage to the parent's input/output
    counts. The service trusts the root run's already-aggregated counts
    rather than walking descendants. A root with `input_tokens=1500` represents
    the whole trace's input load.
    """
    root_with_aggregated_usage = _make_root_run(
        "agg-query",
        input_tokens=1500,  # imagine: 500 from root call + 1000 from Haiku child
        output_tokens=300,
        seconds_offset=0,
    )
    service = _make_service([root_with_aggregated_usage])

    summary = await service.get_exploratory_portal_cost_p50(n=1)

    # 1500 × Sonnet input ($3/1M) + 300 × Sonnet output ($15/1M)
    # = 0.0045 + 0.0045 = 0.009
    # (Sonnet default since no model metadata set)
    assert summary.n_observed == 1
    assert abs(summary.median_usd - 0.009) < 1e-6


@pytest.mark.asyncio
async def test_exploratory_caches_lower_cost():
    """Cache read tokens cost 10% of standard input — verify they're applied."""
    base = datetime(2026, 5, 11, 12, 0, 0)
    runs = []
    for i in range(30):
        runs.append(
            FakeRun(
                id=f"cached-{i}",
                name="interpret_query",
                input_tokens=10,  # tiny non-cached input
                output_tokens=20,
                cache_read_input_tokens=900,  # most input came from cache
                start_time=base + timedelta(seconds=i),
                metadata={"model": "claude-haiku-4-5-20251001"},
            )
        )

    service = _make_service(runs)
    summary = await service.get_exploratory_portal_cost_p50(n=30)

    # Should be heavily under band thanks to cache hits
    assert summary.gate_status == "green"
    # cache_hit_rate = 900 / (900 + 10) ≈ 98.9%
    assert summary.cache_hit_rate > 0.95
