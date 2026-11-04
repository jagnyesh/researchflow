"""#240: the exploratory eval reports cost per passing query and full-denominator accuracy.

Pure functions only; no API key, no database.
"""

import json

from tests.eval.cases import unsupported_cases
from tests.eval.harness import load_fixture, summarize


def _r(kind, matched=None, escaped=None, cost=None):
    return {
        "kind": kind,
        "matched": matched,
        "escaped": escaped,
        "cost_usd": cost,
    }


def test_cost_per_passing_query_divides_median_cost_by_pass_rate():
    results = [
        _r("scored", True, cost=0.002),
        _r("scored", True, cost=0.004),
        _r("scored", False, cost=0.003),
        _r("scored", True, cost=0.005),
        _r("adversarial", escaped=False, cost=0.001),
    ]

    s = summarize(results, n_unsupported=0)

    # Scored queries only: the pass rate is a scored-query rate, so the cost it
    # divides must be too. The adversarial attempt is excluded.
    assert s["median_cost_per_attempt_usd"] == 0.0035
    assert s["accuracy"] == 0.75
    assert s["cost_per_passing_query_usd"] == round(0.0035 / 0.75, 6)


def test_full_denominator_accuracy_counts_unsupported_as_fails():
    results = [_r("scored", True, cost=0.001), _r("scored", True, cost=0.001)]

    s = summarize(results, n_unsupported=2)

    assert s["accuracy"] == 1.0  # the ADR 0028 gate number, unchanged
    assert s["full_denominator_accuracy"] == 0.5


def test_costs_missing_report_as_unknown_not_zero():
    s = summarize([_r("scored", True)], n_unsupported=0)

    assert s["median_cost_per_attempt_usd"] is None
    assert s["cost_per_passing_query_usd"] is None


def test_fixture_with_costs_round_trips_and_old_sql_only_fixtures_still_load(tmp_path):
    new = tmp_path / "new.json"
    new.write_text(json.dumps({"a": {"sql": "SELECT 1", "cost_usd": 0.0021}}))
    old = tmp_path / "old.json"
    old.write_text(json.dumps({"a": "SELECT 1", "b": None}))

    assert load_fixture(new) == {"a": ("SELECT 1", 0.0021)}
    assert load_fixture(old) == {"a": ("SELECT 1", None), "b": (None, None)}


def test_the_suite_has_unsupported_cases_to_count():
    assert unsupported_cases(), "full-denominator accuracy needs the unsupported set"
