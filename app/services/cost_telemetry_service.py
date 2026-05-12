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
    # delivery, etc.) and as the Sonnet fallback in QueryInterpreter.
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
    # Haiku family — used by concept extraction + QueryInterpreter primary path.
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

# Sprint 8.1 gate ceilings — 1.3× projected per portal.
FORMAL_BAND_CEILING_USD = 0.0039  # $0.003 projected × 1.3
EXPLORATORY_BAND_CEILING_USD = 0.00091  # $0.0007 projected × 1.3


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

        Issue #32 (1c) implements this method's actual aggregation. Stub now
        returns a gray summary so #31's dashboard can render both panels with
        the exploratory panel showing "n_observed=0, gray" until #32 lands.
        """
        # TODO(#32): root-trace aggregation: walk root + descendants per query.
        return CostSummary(
            median_usd=0.0,
            n_observed=0,
            cache_hit_rate=0.0,
            band_ceiling_usd=EXPLORATORY_BAND_CEILING_USD,
            gate_status="gray",
        )

    # -------------------------------------------------------------------
    # Internals
    # -------------------------------------------------------------------

    def _fetch_runs_by_tag(self, tag: str, limit: int) -> List[Any]:
        """Sync fetch from LangSmith. Wrapped in asyncio.to_thread by callers."""
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

    def _summarize_threaded(
        self,
        runs: List[Any],
        target_n: int,
        band_ceiling: float,
    ) -> CostSummary:
        """Group runs by thread_id, compute per-thread cost, return summary."""
        threads: Dict[str, List[Any]] = defaultdict(list)
        for run in runs:
            thread_id = _extract_thread_id(run)
            if thread_id is not None:
                threads[thread_id].append(run)

        # Sort threads by most-recent run, take the last target_n
        def _thread_recency(item):
            _, runs_in_thread = item
            return max(_run_start_time(r) for r in runs_in_thread)

        sorted_threads = sorted(threads.items(), key=_thread_recency, reverse=True)
        recent = sorted_threads[:target_n]

        n_observed = len(recent)
        if n_observed == 0:
            return CostSummary(
                median_usd=0.0,
                n_observed=0,
                cache_hit_rate=0.0,
                band_ceiling_usd=band_ceiling,
                gate_status="gray",
            )

        thread_costs = [_sum_thread_cost_usd(thread_runs) for _, thread_runs in recent]
        median = statistics.median(thread_costs)

        # Cache hit rate: cache_read / (cache_read + non_cached_input) across all recent runs
        total_cache_read = 0
        total_input_excl_cache = 0
        for _, thread_runs in recent:
            for r in thread_runs:
                total_cache_read += _get_cache_read_tokens(r)
                total_input_excl_cache += _get_input_tokens(r)
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
    """Non-cached input tokens. Anthropic returns cache_read separately."""
    return int(getattr(run, "input_tokens", 0) or 0)


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
    """Compute one run's cost in USD using the per-model pricing table."""
    model = _get_model(run)
    prices = _PRICING_USD_PER_1M.get(model)
    if prices is None:
        # Unknown model: fall back to Sonnet pricing (conservative — costs higher)
        logger.debug("Unknown model %r, using default Sonnet pricing", model)
        prices = _PRICING_USD_PER_1M[_DEFAULT_MODEL]

    input_tok = _get_input_tokens(run)
    output_tok = _get_output_tokens(run)
    cache_read = _get_cache_read_tokens(run)
    cache_write = _get_cache_creation_tokens(run)

    return (
        input_tok * prices["input"]
        + output_tok * prices["output"]
        + cache_read * prices["cache_read"]
        + cache_write * prices["cache_creation"]
    ) / 1_000_000


def _sum_thread_cost_usd(runs: Iterable[Any]) -> float:
    return sum(_run_cost_usd(r) for r in runs)
