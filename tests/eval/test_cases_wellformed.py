"""Sprint 6.7 #98 — cheap services-free sanity checks on the eval case set.

Runs in the base CI job (no HAPI, no key). The scoring itself is in
test_eval_replay.py (requires_services)."""

import json

from tests.eval.cases import (
    EVAL_CASES,
    adversarial_cases,
    scored_cases,
    unsupported_cases,
)
from tests.eval.harness import fixture_path


def test_case_ids_are_unique():
    ids = [c.id for c in EVAL_CASES]
    assert len(ids) == len(set(ids))


def test_scored_cases_carry_oracles():
    for c in scored_cases():
        assert c.oracle_sql and "sqlonfhir." in c.oracle_sql, c.id


def test_adversarial_and_unsupported_have_no_oracle():
    for c in list(adversarial_cases()) + list(unsupported_cases()):
        assert c.oracle_sql is None, c.id


def test_set_is_roughly_thirty_with_coverage():
    assert len(scored_cases()) >= 20
    assert len(adversarial_cases()) >= 6
    cats = {c.category for c in scored_cases()}
    # spans the required breadth
    for needed in ("gender", "age", "condition", "lab-threshold", "count_distinct"):
        assert any(needed in c for c in cats), needed
    assert any("negation" in c for c in cats)
    assert any("temporal" in c for c in cats)


def test_recorded_fixture_covers_every_run_case():
    # The committed Sonnet fixture must have an entry for every case the harness
    # actually runs (scored + adversarial), so CI replay never silently treats a
    # case as a refusal. Unsupported (breakdown) cases are not run/recorded.
    fixtures = json.loads(fixture_path("claude-sonnet-4-6").read_text())
    for c in list(scored_cases()) + list(adversarial_cases()):
        assert c.id in fixtures, f"fixture missing recorded SQL for {c.id}"
