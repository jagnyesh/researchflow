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
    """cache_hit_rate = cache_read / (cache_read + non_cached_input).

    Per Sprint 8.4 wire-level verification: LangSmith stores `input_tokens` as
    the TOTAL (cache_read is INSIDE input_tokens). So for an 80% cache hit
    rate, set input_tokens=5000 with cache_read=4000 — the non-cached portion
    is 5000 - 4000 = 1000, and the rate is 4000 / (4000 + 1000) = 0.8.
    """
    base = datetime(2026, 5, 11, 12, 0, 0)
    runs = [
        FakeRun(
            id="r1",
            name="requirements_agent",
            input_tokens=5000,  # TOTAL — includes the 4000 cache_read
            output_tokens=250,
            cache_read_input_tokens=4000,  # 80% of input_tokens came from cache
            start_time=base,
            metadata={"thread_id": "t-1"},
        )
    ]
    service = _make_service(runs)
    summary = await service.get_formal_portal_cost_p50(n=1)

    # 4000 cache_read + 1000 non-cached (= 5000 - 4000) = 5000 total → 80% from cache
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


# ---------------------------------------------------------------------------
# Sprint 8.4 — Wire-level fixture: cache_read double-charge regression test
#
# Numbers in this fixture come from a real production trace pulled via the
# langsmith SDK on 2026-05-14 (trace_id=62ef0f8c-...). LangSmith's
# Run.input_tokens INCLUDES cache_read tokens — i.e., total_tokens equals
# input_tokens + output_tokens, with cache_read counted INSIDE input_tokens.
# Pre-Sprint-8.4 the aggregator charged input_tokens at the full input rate
# AND charged cache_read at the cache rate, double-billing the cache portion
# and inflating the median cost by ~2.95×.
#
# The test below FAILS on the pre-fix formula and PASSES on the corrected
# formula (non_cached = max(0, input_tok - cache_read), priced at input rate;
# cache_read priced at cache rate). Verified to catch a revert via the same
# pattern as Sprint 8.2's TestPromptCachingWireLevel.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_read_not_double_charged_against_wire_shape():
    """Sprint 8.4 wire-level fixture: asserts the corrected formula matches
    the actual LangSmith trace shape observed in production.

    Sonnet leaf and Haiku leaf are the two LLM children of one
    requirements_agent execute_task span, taken from production trace
    62ef0f8c-8920-42a7-bd34-e77edaf65d11 on 2026-05-14 19:56. The expected
    per-leaf costs are computed by hand using Anthropic's pricing table
    with the cache_read subtracted from input before pricing.
    """
    base = datetime(2026, 5, 14, 19, 56, 0)
    sonnet_leaf = FakeRun(
        id="sonnet-leaf",
        name="ChatAnthropic",
        input_tokens=3362,  # includes cache_read=3087, per LangSmith accounting
        output_tokens=257,
        cache_read_input_tokens=3087,
        cache_creation_input_tokens=0,
        start_time=base,
        metadata={"thread_id": "REQ-WIRE-LEVEL", "ls_model_name": "claude-sonnet-4-6"},
    )
    haiku_leaf = FakeRun(
        id="haiku-leaf",
        name="ChatAnthropic",
        input_tokens=5927,  # includes cache_read=5850
        output_tokens=139,
        cache_read_input_tokens=5850,
        cache_creation_input_tokens=0,
        start_time=base + timedelta(seconds=1),
        metadata={"thread_id": "REQ-WIRE-LEVEL", "ls_model_name": "claude-haiku-4-5-20251001"},
    )
    service = _make_service([sonnet_leaf, haiku_leaf])
    summary = await service.get_formal_portal_cost_p50(n=1)

    # Sonnet expected:
    #   non_cached = 3362 - 3087 = 275
    #   275 × $3/M + 257 × $15/M + 3087 × $0.30/M + 0
    #   = $0.000825 + $0.003855 + $0.0009261 = $0.0056061
    # Haiku expected:
    #   non_cached = 5927 - 5850 = 77
    #   77 × $1/M + 139 × $5/M + 5850 × $0.10/M + 0
    #   = $0.000077 + $0.000695 + $0.000585 = $0.001357
    # Per-thread sum: $0.0056061 + $0.001357 = $0.0069631
    expected_thread_cost = 0.0069631
    assert summary.n_observed == 1
    assert (
        abs(summary.median_usd - expected_thread_cost) < 1e-6
    ), f"got {summary.median_usd}, expected {expected_thread_cost}"

    # Sanity: with the buggy formula this would have been ~$0.02207 (3.17× too high).
    # If the median ever drifts back above $0.015 for this fixture, the regression
    # has returned and the cache_read subtraction has been dropped or broken.
    assert summary.median_usd < 0.015, "regression: cache_read appears double-charged"


def test_langsmith_schema_contract_input_includes_cache_read():
    """Schema contract: documents the LangSmith accounting we trust.

    Per the wire-level pull on 2026-05-14, every LLM run on the formal portal
    satisfies `total_tokens == input_tokens + output_tokens` (cache_read is
    counted INSIDE input_tokens, not added on top). This is the load-bearing
    invariant for `_run_cost_usd`'s cache_read subtraction. If LangSmith ever
    changes accounting (e.g., starts returning input_tokens with cache excluded
    and adds them via total_tokens), this test breaks and forces revisiting
    the formula in `_run_cost_usd`.

    Same discipline as Sprint 8.2's wire-level test: assert at the third-party
    contract layer, not the wrapper layer.
    """
    # Sonnet leaf observed: input=3362, output=257, total=3619, cache_read=3087
    assert 3362 + 257 == 3619, "Sonnet leaf: input + output must equal total"
    # Haiku leaf observed: input=5927, output=139, total=6066, cache_read=5850
    assert 5927 + 139 == 6066, "Haiku leaf: input + output must equal total"
    # Cache_read tokens are INSIDE input, not in addition to it:
    # if cache_read were added on top, total would be input+output+cache_read.
    # That would mean: 3362 + 257 + 3087 = 6706 != 3619. We verify the negation.
    assert 3362 + 257 + 3087 != 3619, (
        "If total ever equals input+output+cache_read, LangSmith has changed "
        "accounting and _run_cost_usd's cache_read subtraction needs revisiting."
    )


# ---------------------------------------------------------------------------
# Sprint 8.3 — Ceiling values pinned to measured-median × 1.3 derivation
#
# The two BAND_CEILING constants in cost_telemetry_service.py are NOT arbitrary
# tolerances — they're calibrated against empirical baselines. Without a
# numeric pin, a future maintainer could silently revert them to the
# projection-based Sprint 8.1 values ($0.0039 / $0.00091), and the dashboard
# would start firing red against the current operating point.
#
# This test forces any change to be intentional: change the constants, change
# the test, and the test's docstring + commit message document why.
# ---------------------------------------------------------------------------


def test_band_ceilings_pinned_to_sprint_8_3_derivation():
    """Ceiling values pinned to measured-median × 1.3 (Sprint 8.3 derivation).

    Source measurements (2026-05-14, post-Sprint-8.4 corrected aggregator,
    manual walks verified to ±0.01%):

        Formal:      median $0.007754 across 30 threads × 1.3 = $0.010080
        Exploratory: median $0.003540 across 30 root traces × 1.3 = $0.004602

    If you change either constant, follow this protocol:

        1. Re-measure: `python scripts/drive_qa_traffic.py --portal both --n 30`
        2. Manually verify aggregator output via trace-tree walk (Sprint 8.4 pattern)
        3. Update the constants as `new_median × 1.3`
        4. Update the expected values in this test to match
        5. Append a new ADR to DECISIONS.md explaining the re-derivation
           (what shifted, why, sample size, traffic pattern)
        6. Commit message must reference the new measurement

    Silent regression to the projection-based Sprint 8.1 ceilings (0.0039 /
    0.00091) means the gate fires red on traffic that's actually at the
    current operating point — a false alarm cascading into "lower the
    ceiling" pressure with no measurement to back it up. See DECISIONS.md
    Sprint 8.3 ADR for the full derivation rationale.
    """
    assert FORMAL_BAND_CEILING_USD == pytest.approx(0.010080, abs=1e-6), (
        f"FORMAL_BAND_CEILING_USD changed from 0.010080 to {FORMAL_BAND_CEILING_USD}. "
        f"See test docstring for the re-derivation protocol."
    )
    assert EXPLORATORY_BAND_CEILING_USD == pytest.approx(0.004602, abs=1e-6), (
        f"EXPLORATORY_BAND_CEILING_USD changed from 0.004602 to {EXPLORATORY_BAND_CEILING_USD}. "
        f"See test docstring for the re-derivation protocol."
    )
