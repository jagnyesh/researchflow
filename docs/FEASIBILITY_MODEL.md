# Feasibility Model (as wired, 2026-10-20)

Reference for the feasibility estimate that a model card, calibration work (#148, #149), and drift monitoring (#151) describe. It documents the code as it runs today, not a target design.

**The model is rule-based.** Weights, the feasible threshold, the data-availability value, and the confidence interval are all hardcoded constants. Nothing in it is fitted to observed (predicted, actual) pairs.

## Where feasibility is computed

A whole-tree search (`grep -rniE "feasibility_score|def .*feasib|min\(1\.0" app scripts --include='*.py'`) finds one weighted formula and one binary score on live paths. The `min(1.0, count/100)` formula in `langchain_agents.py` is gone; that file was deleted in #116 (PR #120).

| Path | Where | Score | Live? |
|---|---|---|---|
| Formal portal (LangGraph → PhenotypeAgent) | `app/agents/phenotype_agent.py:797` `_calculate_feasibility_score` | Weighted composite, below | Yes — the model this doc describes |
| Exploratory portal (`FeasibilityService`) | `app/services/feasibility_service.py:193` | `1.0 if estimated_cohort > 0 else 0.0` | Yes, but not a model: the research notebook never renders it |
| LangGraph stub branch (`use_real_agents=False`) | `app/langchain_orchestrator/langgraph_workflow.py:749` | Constant `0.95` | Test/E2E path only |

## Formal-portal formula

`_calculate_feasibility_score(estimated_count, data_availability, requirements)` returns `min(score, 1.0)`, the sum of three factors:

| Factor | Weight | Rule | Pointer |
|---|---|---|---|
| Cohort size | 0.4 | `n ≥ 2·min` → 0.4; `n ≥ min` → 0.3; `n ≥ 0.5·min` → 0.2; else 0.0. `min = requirements["minimum_cohort_size"]`, default 50 | `phenotype_agent.py:811` |
| Data availability | 0.4 | `overall_availability × 0.4` | `phenotype_agent.py:823` |
| Time period | 0.2 | both `start` and `end` → 0.2; one of them → 0.1; neither → 0.0 | `phenotype_agent.py:828` |

### Inputs

- **`estimated_count`** — the actual count of matching patients from `_estimate_cohort_size` (`phenotype_agent.py:248`). It runs through HybridRunner in `FORMAL_DRAFT` mode, with Python post-filtering. No scaling factor is applied; the old 0.7× factor was removed as Bug #8.
- **`overall_availability`** — pinned to **0.9** for any request with at least one data element (`phenotype_agent.py:734`–`745`). Both `use_view_definitions` (`phenotype_agent.py:62`) and `use_materialized_views` (`phenotype_agent.py:44`) are hardcoded `True`, so the per-element measurement loop below that branch never runs. A request with no data elements gets 0.0. In practice this factor contributes 0.36 or 0.0. It is never measured.

### Outputs

- **`feasible = feasibility_score > 0.6`** (`phenotype_agent.py:151`). Its only effect is the informational `auto_feasibility_assessment` banner in the admin dashboard (`phenotype_agent.py:240`, `app/web_ui/admin_dashboard.py:1536`). It does **not** route: `_route_after_feasibility_validation` always returns `phenotype_review` (`langgraph_workflow.py:1434`), so an informatician reviews every request.
- **`confidence_interval = (int(n·0.85), int(n·1.15))`** (`phenotype_agent.py:154`). A fixed ±15% band, not derived from any error data. #148 replaces it.
- **`feasibility_score`** — shown in the admin dashboard as "Feasibility Score" (`admin_dashboard.py:1521`) and persisted to `FeasibilityReport.feasibility_score` (`app/database/models.py:107`).

## Observed behavior

Measured by calling `_calculate_feasibility_score` directly, with `minimum_cohort_size=50`. `F` means `feasible`.

| availability | time period | n=100 | n=50 | n=25 | n=24 | n=0 |
|---|---|---|---|---|---|---|
| 0.9 (pinned) | start+end | 0.96 F | 0.86 F | 0.76 F | 0.56 | 0.56 |
| 0.9 (pinned) | one bound | 0.86 F | 0.76 F | 0.66 F | 0.46 | 0.46 |
| 0.9 (pinned) | none | 0.76 F | 0.66 F | 0.56 | 0.36 | 0.36 |
| 0.0 (no elements) | start+end | 0.60 F | 0.50 | 0.40 | 0.20 | 0.20 |

Consequences for anyone citing this score:

1. **A cohort at half the minimum can still be marked `feasible`.** For n=25 with a full time period, the score is 0.76, while the same report carries a `small_cohort` warning (`phenotype_agent.py:165`–`169`). The banner and the warning disagree.
2. **An empty cohort scores 0.56 when the request is well-formed.** Two of the three factors don't depend on the cohort at all, so the score mostly measures whether the request is complete, not whether it's feasible.
3. **The `> 0.6` cut-off sits on a float edge.** `0.4 + 0.0 + 0.2` evaluates to `0.6000000000000001`, so n=100 with no data elements passes a threshold it ties in exact arithmetic.
4. **No unit test exercises `_calculate_feasibility_score` directly.** The table above is the only recorded characterization.

None of these are fixed here. They are the baseline that calibration (#148, #149) and subgroup error work (#150) should measure against.
