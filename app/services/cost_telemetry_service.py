"""Cost telemetry service for Sprint 8.1 prompt-optimization verification.

Reads LangSmith run data and aggregates it into per-portal cost-per-request
medians. The dashboard's "Cost Telemetry" tile renders the output.

Architecture choice: LangSmith is the source-of-truth for LLM cost data (no
parallel `QueryTelemetry` Postgres table). Per the ADR in DECISIONS.md
("Sprint 8.1 — LangSmith is source-of-truth..."), this service queries
LangSmith via the `langsmith` SDK and computes cost from per-run token
counts using a local pricing table (Anthropic published prices, last
updated 2026-05-11). We don't depend on LangSmith's own cost computation
because that requires LangSmith's pricing config to be current and we'd
rather own the source of truth on what we paid.

Filter strategy (Sprint 8.1 #29 prerequisite):
- Formal portal: runs tagged `portal:formal`, grouped by `thread_id`
  metadata (one thread = one user submission). Cost-per-request = sum of
  per-run cost across the thread's runs.
- Exploratory portal: runs tagged `portal:exploratory` at the root.
  Cost-per-query = sum across the root + its descendants.

The gate fires at rolling-N (default 30): need at least N requests/queries
observed to declare green or red. Fewer → gray.
"""

from __future__ import annotations

import asyncio
import logging
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, List, Literal, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pricing constants
#
# Source: https://www.anthropic.com/pricing (USD per 1M tokens), last updated
# 2026-05-11. If Anthropic adjusts prices, update here and the dashboard
# automatically reflects new numbers on the next render.
#
# Cache read = 10% of standard input (Anthropic's published discount).
# Cache write (5-min ephemeral) = 1.25× standard input.
# ---------------------------------------------------------------------------

_PRICING_USD_PER_1M: Dict[str, Dict[str, float]] = {
    # Sonnet family — used by the formal portal agents (requirements, phenotype,
    # delivery, etc.) and by the exploratory SQL synthesizer (SQLSynthesizer).
    "claude-sonnet-4-6": {
        "input": 3.00,
        "output": 15.00,
        "cache_read": 0.30,
        "cache_creation": 3.75,
    },
    "claude-sonnet-4-5": {
        "input": 3.00,
        "output": 15.00,
        "cache_read": 0.30,
        "cache_creation": 3.75,
    },
    # Haiku family — used by concept extraction.
    "claude-haiku-4-5-20251001": {
        "input": 1.00,
        "output": 5.00,
        "cache_read": 0.10,
        "cache_creation": 1.25,
    },
    "claude-haiku-4-5": {
        "input": 1.00,
        "output": 5.00,
        "cache_read": 0.10,
        "cache_creation": 1.25,
    },
}

_DEFAULT_MODEL = "claude-sonnet-4-6"  # If a run has no model metadata, assume Sonnet.

# Sprint 8.3 gate ceilings — 1.3× MEASURED MEDIAN per portal (re-derived 2026-05-14).
#
# Semantic shift from Sprint 8.1: the original ceilings were `projection × 1.3`
# (tolerance band around an aspirational cost target). Sprint 8.3 ceilings are
# `measured_median × 1.3` (tolerance band around the current operating point).
# Math identical; meaning shifts from "cost target with tolerance" to
# "regression alarm against current baseline." This is the honest framing —
# the Sprint 8 series projections were falsified by Sprint 8.2 Task 3 (3×
# call-count overestimate + 9× per-call cost underestimate). Setting the
# ceiling at measured-median × 1.3 is calibrated to catch regressions, not
# to enforce the projection that didn't match reality.
#
# Traffic-pattern assumption: medians come from BURSTY harness traffic
# (`scripts/drive_qa_traffic.py` → 30 requests in 6-7 min, within Anthropic's
# 5-min cache TTL). Sparse real-world traffic (gaps > 5 min between requests)
# would shift the median toward the worst-case (cache_create) cost. The
# ceilings below are calibrated for bursty patterns; sparse-traffic
# measurement is filed as a Sprint 8.5+ candidate in BACKLOG.md.
#
# Source measurements (post-Sprint-8.4 corrected aggregator, verified by manual
# LLM-leaf sum within 0.01%):
#   Formal (2026-05-14):      median $0.007754 across 30 threads, cache_hit_rate 94.88%
#   Exploratory (2026-07-12): median $0.003586 across 30 root traces, cache_hit_rate 95.00%
#
# DISCONTINUITY — the exploratory number changed PATH at Sprint 6.7 #100. Before:
# the QueryInterpreter path, median $0.003540, cache_hit_rate 0.0000% (the
# below-threshold prompt Sprint 8.6 flagged). After: the LLM-synthesis path
# (SQLSynthesizer), median $0.003586, cache_hit_rate 95.00% — the schema-context
# prompt block finally clears Anthropic's caching threshold, closing the Sprint
# 8.6 candidate. The median is essentially flat (+1.3%) DESPITE cache going
# 0%→95%, because the synthesis prompt is larger (the schema block) but now
# caches: bigger-prompt-cached ≈ smaller-prompt-uncached. The ceiling barely
# moves; the cost is now cache_read-dominated (cheap) instead of full-input.
FORMAL_BAND_CEILING_USD = 0.010080  # $0.007754 measured × 1.3
EXPLORATORY_BAND_CEILING_USD = 0.004661  # $0.003586 measured × 1.3 (Sprint 6.7 synthesis path)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


GateStatus = Literal["green", "red", "gray"]


@dataclass
class CostSummary:
    """What the dashboard panel renders for one portal."""

    median_usd: float
    n_observed: int
    cache_hit_rate: float
    band_ceiling_usd: float
    gate_status: GateStatus


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class CostTelemetryService:
    """Wraps the LangSmith client and exposes per-portal cost aggregation.

    The LangSmith Python SDK's `list_runs` is synchronous, so each public
    async method off-loads the query to a thread via `asyncio.to_thread`.
    Streamlit dashboards re-render on every interaction; the small per-call
    cost is fine.
    """

    def __init__(
        self,
        client: Optional[Any] = None,
        project: str = "researchflow-production",
        # Over-fetch headroom: a thread has ~5–15 runs, so fetch ~10× the
        # target thread count to make it likely we observe enough threads.
        fetch_multiplier: int = 15,
    ):
        self._client = client
        self._project = project
        self._fetch_multiplier = fetch_multiplier

    def _ensure_client(self) -> Any:
        """Lazy-construct a real langsmith Client if none was injected."""
        if self._client is None:
            from langsmith import Client  # imported lazily to keep tests fast

            self._client = Client()
        return self._client

    # -------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------

    async def get_formal_portal_cost_p50(self, n: int = 30) -> CostSummary:
        """Median cost-per-request across the last n threads tagged portal:formal."""
        runs = await asyncio.to_thread(
            self._fetch_runs_by_tag,
            "portal:formal",
            n * self._fetch_multiplier,
        )
        return self._summarize_threaded(runs, target_n=n, band_ceiling=FORMAL_BAND_CEILING_USD)

    async def get_exploratory_portal_cost_p50(self, n: int = 30) -> CostSummary:
        """Median cost-per-query across the last n root-traces tagged portal:exploratory.

        Aggregation is per ROOT TRACE (not per thread like formal). LangSmith
        propagates child-run usage_metadata up to the root, so each root's
        input_tokens/output_tokens already represents the whole trace tree's
        cost — no descendant walking needed. The exploratory synthesizer's
        Sonnet call shows up as a child run whose tokens roll up into the
        root's aggregated counts.
        """
        roots = await asyncio.to_thread(
            self._fetch_root_runs_by_tag,
            "portal:exploratory",
            n * 2,  # exploratory queries are typically one root each, less over-fetch needed
        )
        return self._summarize_per_root(
            roots, target_n=n, band_ceiling=EXPLORATORY_BAND_CEILING_USD
        )

    # -------------------------------------------------------------------
    # Internals
    # -------------------------------------------------------------------

    def _fetch_runs_by_tag(self, tag: str, limit: int) -> List[Any]:
        """Sync fetch from LangSmith — all runs (root + descendants) matching tag.

        Used by formal-portal aggregation, where each thread has 5-15 runs and
        we need every one to roll up per-thread cost. Wrapped in
        asyncio.to_thread by callers.
        """
        client = self._ensure_client()
        try:
            runs_iter = client.list_runs(
                project_name=self._project,
                filter=f'has(tags, "{tag}")',
                limit=limit,
            )
            return list(runs_iter)
        except Exception as exc:  # langsmith API may be unavailable
            logger.warning("LangSmith fetch failed for tag %r: %s", tag, exc)
            return []

    def _fetch_root_runs_by_tag(self, tag: str, limit: int) -> List[Any]:
        """Sync fetch for ROOT runs only — used by exploratory aggregation.

        LangSmith auto-aggregates child usage_metadata into the parent, so
        each root run's token counts already cover the whole query. One API
        call gets N data points (vs N+1 for trace-tree walking).
        """
        client = self._ensure_client()
        try:
            runs_iter = client.list_runs(
                project_name=self._project,
                filter=f'has(tags, "{tag}")',
                is_root=True,
                limit=limit,
            )
            return list(runs_iter)
        except Exception as exc:
            logger.warning("LangSmith root-run fetch failed for tag %r: %s", tag, exc)
            return []

    def _summarize_threaded(
        self,
        runs: List[Any],
        target_n: int,
        band_ceiling: float,
    ) -> CostSummary:
        """Group runs by thread_id (one thread = one request) and summarize.

        Used by formal-portal aggregation. Each thread becomes one data point
        whose cost is the sum across its constituent runs.
        """
        threads: Dict[str, List[Any]] = defaultdict(list)
        for run in runs:
            thread_id = _extract_thread_id(run)
            if thread_id is not None:
                threads[thread_id].append(run)

        # Convert each thread to a (cost, cache_read, input, recency) data point
        points = [
            _RequestPoint(
                cost_usd=_sum_thread_cost_usd(thread_runs),
                cache_read_tokens=sum(_get_cache_read_tokens(r) for r in thread_runs),
                non_cached_input_tokens=sum(_get_non_cached_input_tokens(r) for r in thread_runs),
                start_time=max(_run_start_time(r) for r in thread_runs),
            )
            for _, thread_runs in threads.items()
        ]
        return _summarize_points(points, target_n=target_n, band_ceiling=band_ceiling)

    def _summarize_per_root(
        self,
        roots: List[Any],
        target_n: int,
        band_ceiling: float,
    ) -> CostSummary:
        """Each root run = one query = one data point. No grouping.

        Used by exploratory-portal aggregation. LangSmith's usage_metadata
        propagation means root.input_tokens already includes descendants'
        usage, so we just compute one cost per root.
        """
        points = [
            _RequestPoint(
                cost_usd=_run_cost_usd(root),
                cache_read_tokens=_get_cache_read_tokens(root),
                non_cached_input_tokens=_get_non_cached_input_tokens(root),
                start_time=_run_start_time(root),
            )
            for root in roots
        ]
        return _summarize_points(points, target_n=target_n, band_ceiling=band_ceiling)


# ---------------------------------------------------------------------------
# Aggregation primitives — both formal and exploratory portals reduce to a
# list of "request points" and the same summarization logic.
# ---------------------------------------------------------------------------


@dataclass
class _RequestPoint:
    """One data point in a cost-per-request distribution.

    Formal portal: one per thread (sum of runs).
    Exploratory portal: one per root trace.
    """

    cost_usd: float
    cache_read_tokens: int
    non_cached_input_tokens: int
    start_time: datetime


def _summarize_points(
    points: List[_RequestPoint],
    target_n: int,
    band_ceiling: float,
) -> CostSummary:
    """Sort points by recency, take last target_n, return CostSummary.

    Gate logic: gray when sample is insufficient (n < target_n); otherwise
    green when median ≤ band, red when median > band.
    """
    sorted_points = sorted(points, key=lambda p: p.start_time, reverse=True)
    recent = sorted_points[:target_n]

    n_observed = len(recent)
    if n_observed == 0:
        return CostSummary(
            median_usd=0.0,
            n_observed=0,
            cache_hit_rate=0.0,
            band_ceiling_usd=band_ceiling,
            gate_status="gray",
        )

    median = statistics.median(p.cost_usd for p in recent)

    total_cache_read = sum(p.cache_read_tokens for p in recent)
    total_input_excl_cache = sum(p.non_cached_input_tokens for p in recent)
    denom = total_cache_read + total_input_excl_cache
    cache_hit_rate = (total_cache_read / denom) if denom > 0 else 0.0

    if n_observed < target_n:
        status: GateStatus = "gray"
    else:
        status = "green" if median <= band_ceiling else "red"

    return CostSummary(
        median_usd=median,
        n_observed=n_observed,
        cache_hit_rate=cache_hit_rate,
        band_ceiling_usd=band_ceiling,
        gate_status=status,
    )


# ---------------------------------------------------------------------------
# Run helpers — tolerant of both real langsmith.Run and test FakeRun shapes.
# ---------------------------------------------------------------------------


def _extract_thread_id(run: Any) -> Optional[str]:
    """LangGraph sets thread_id in run metadata. We tolerate test doubles
    that put it directly on the object's `metadata` dict."""
    metadata = getattr(run, "metadata", None) or {}
    if isinstance(metadata, dict):
        return metadata.get("thread_id") or metadata.get("langgraph_thread_id")
    return None


def _run_start_time(run: Any) -> datetime:
    """Used only for sorting. If absent, treat as epoch (won't sort first)."""
    return getattr(run, "start_time", None) or datetime.min


def _get_input_tokens(run: Any) -> int:
    """Total input tokens, INCLUDING cache_read.

    Despite the Anthropic API returning input_tokens as the non-cached portion,
    LangSmith's `Run.input_tokens` stores the TOTAL (verified Sprint 8.4 wire
    pull on 2026-05-14: every observed LLM leaf satisfied
    `total_tokens == input_tokens + output_tokens` with cache_read inside
    input_tokens). Callers that need the non-cached portion must subtract
    cache_read_tokens themselves via `_get_non_cached_input_tokens` below.
    """
    return int(getattr(run, "input_tokens", 0) or 0)


def _get_non_cached_input_tokens(run: Any) -> int:
    """Non-cached input tokens: input_tokens minus cache_read.

    This is the value that should be priced at the full input rate; cache_read
    is priced separately at the discounted cache rate. Used by `_run_cost_usd`
    and by cache_hit_rate computation in `_summarize_points`.
    """
    return max(0, _get_input_tokens(run) - _get_cache_read_tokens(run))


def _get_output_tokens(run: Any) -> int:
    return int(getattr(run, "output_tokens", 0) or 0)


def _get_cache_read_tokens(run: Any) -> int:
    """Try the explicit field first, then the token-details dict."""
    explicit = getattr(run, "cache_read_input_tokens", None)
    if explicit is not None:
        return int(explicit)
    details = getattr(run, "input_token_details", None) or {}
    if isinstance(details, dict):
        return int(details.get("cache_read", 0) or 0)
    return 0


def _get_cache_creation_tokens(run: Any) -> int:
    """Cache-write tokens (one-time per cache prompt)."""
    explicit = getattr(run, "cache_creation_input_tokens", None)
    if explicit is not None:
        return int(explicit)
    details = getattr(run, "input_token_details", None) or {}
    if isinstance(details, dict):
        return int(details.get("cache_creation", 0) or 0)
    return 0


def _get_model(run: Any) -> str:
    """Pull model name from run.metadata or run.extra.invocation_params.model."""
    metadata = getattr(run, "metadata", None) or {}
    if isinstance(metadata, dict):
        if "model" in metadata:
            return metadata["model"]
        if "ls_model_name" in metadata:
            return metadata["ls_model_name"]
    extra = getattr(run, "extra", None) or {}
    if isinstance(extra, dict):
        invoc = extra.get("invocation_params") or {}
        if isinstance(invoc, dict) and "model" in invoc:
            return invoc["model"]
    return _DEFAULT_MODEL


def _run_cost_usd(run: Any) -> float:
    """Compute one run's cost in USD using the per-model pricing table.

    LangSmith's accounting (verified Sprint 8.4 wire-level pull on 2026-05-14):
    `Run.input_tokens` already includes `cache_read_input_tokens` — i.e.,
    `total_tokens == input_tokens + output_tokens` and cache_read is INSIDE
    input_tokens, not added on top. The non-cached portion is
    `input_tokens - cache_read`. The schema-contract test in
    `tests/test_cost_telemetry_service.py` documents this invariant; if
    LangSmith ever changes accounting, the test breaks and forces a revisit.
    """
    model = _get_model(run)
    prices = _PRICING_USD_PER_1M.get(model)
    if prices is None:
        # Unknown model: fall back to Sonnet pricing (conservative — costs higher)
        logger.debug("Unknown model %r, using default Sonnet pricing", model)
        prices = _PRICING_USD_PER_1M[_DEFAULT_MODEL]

    non_cached_input = _get_non_cached_input_tokens(run)
    output_tok = _get_output_tokens(run)
    cache_read = _get_cache_read_tokens(run)
    cache_write = _get_cache_creation_tokens(run)

    return (
        non_cached_input * prices["input"]
        + output_tok * prices["output"]
        + cache_read * prices["cache_read"]
        + cache_write * prices["cache_creation"]
    ) / 1_000_000


def _sum_thread_cost_usd(runs: Iterable[Any]) -> float:
    return sum(_run_cost_usd(r) for r in runs)
