"""Sprint 6.7 #96 — retry loop + honest-failure invariant (ADR 0028 decision 5).

The invariant (the #76 lesson): an error path may NEVER carry a numeric
estimated_cohort. Validator rejection → ONE resynthesis with the violation
appended → still invalid → structured error variant. Execution error → error
variant immediately, no retry.

Synthesizer LLM mocked at the boundary; validator is real (schemas from the
shared cache, patched as in test_feasibility_synthesis_wiring.py).
"""

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.feasibility_service import FeasibilityService
from app.services.schema_introspection import ColumnInfo, ViewSchema
from app.services.sql_synthesis import SynthesisResult

CANNED_SCHEMAS = {
    "patient_demographics": ViewSchema(
        name="patient_demographics",
        description="",
        columns=(
            ColumnInfo("patient_id", "text"),
            ColumnInfo("gender", "text"),
            ColumnInfo("family_name", "text"),
        ),
    ),
}

VALID_SQL = (
    "SELECT COUNT(DISTINCT patient_id) FROM sqlonfhir.patient_demographics WHERE gender = 'female'"
)
INVALID_SQL = "SELECT family_name FROM sqlonfhir.patient_demographics"


def _sequenced_synthesizer(*results: SynthesisResult) -> MagicMock:
    """A synthesizer whose synthesize() yields the given results in order and
    records every (query, feedback) call."""
    instance = MagicMock()
    instance.synthesize = AsyncMock(side_effect=list(results))
    return instance


@contextmanager
def _synthesis_path(synthesizer: MagicMock):
    with patch("app.services.feasibility_service.SQLSynthesizer", return_value=synthesizer):
        with patch(
            "app.services.feasibility_service.get_cached_schemas",
            new=AsyncMock(return_value=CANNED_SCHEMAS),
        ):
            yield


async def _run(fs, synthesizer, monkeypatch, nl="any query"):
    monkeypatch.setenv("USE_LLM_SQL_SYNTHESIS", "true")
    with _synthesis_path(synthesizer):
        return await fs.execute_feasibility_check(
            {"view_definitions": []}, natural_language_query=nl
        )


class TestRetryThenSucceed:
    async def test_rejection_retries_once_with_feedback_then_succeeds(self, monkeypatch):
        fs = FeasibilityService()
        fs.exploratory_db_client = MagicMock()
        fs.exploratory_db_client.execute_query = AsyncMock(return_value=[{"count": 21}])
        synth = _sequenced_synthesizer(
            SynthesisResult(sql=INVALID_SQL, explanation="bad"),
            SynthesisResult(sql=VALID_SQL, explanation="good"),
        )

        result = await _run(fs, synth, monkeypatch)

        # Exactly two synthesize calls: original + one retry.
        assert synth.synthesize.await_count == 2
        # The retry carried the specific violation text as feedback.
        retry_feedback = synth.synthesize.await_args_list[1].kwargs.get("feedback")
        assert retry_feedback is not None
        assert "aggregate" in retry_feedback.lower()
        # And the second (valid) attempt executed and mapped normally.
        assert result["estimated_cohort"] == 21


class TestHonestFailureInvariant:
    async def test_double_rejection_returns_error_variant_no_cohort(self, monkeypatch):
        fs = FeasibilityService()
        fs.exploratory_db_client = MagicMock()
        fs.exploratory_db_client.execute_query = AsyncMock()
        synth = _sequenced_synthesizer(
            SynthesisResult(sql=INVALID_SQL, explanation="attempt 1"),
            SynthesisResult(sql=INVALID_SQL, explanation="attempt 2"),
        )

        result = await _run(fs, synth, monkeypatch)

        # THE INVARIANT: an error path never carries a numeric cohort (#76).
        assert result["status"] == "error"
        assert "estimated_cohort" not in result
        assert result["rejected_sql"] == INVALID_SQL
        assert "aggregate" in result["reason"].lower()
        # Exactly one retry (2 synth calls); the SQL never reached the DB.
        assert synth.synthesize.await_count == 2
        fs.exploratory_db_client.execute_query.assert_not_called()

    async def test_at_most_one_retry(self, monkeypatch):
        # Even if the model would keep failing, synthesize is called at most
        # twice — no unbounded retry loop.
        fs = FeasibilityService()
        fs.exploratory_db_client = MagicMock()
        fs.exploratory_db_client.execute_query = AsyncMock()
        synth = _sequenced_synthesizer(
            SynthesisResult(sql=INVALID_SQL, explanation="1"),
            SynthesisResult(sql=INVALID_SQL, explanation="2"),
            SynthesisResult(sql=INVALID_SQL, explanation="3-should-never-be-called"),
        )

        await _run(fs, synth, monkeypatch)

        assert synth.synthesize.await_count == 2

    async def test_execution_error_returns_error_variant_immediately_no_retry(self, monkeypatch):
        fs = FeasibilityService()
        fs.exploratory_db_client = MagicMock()
        # EXPLAIN dry-run succeeds; the real execution raises.
        fs.exploratory_db_client.execute_query = AsyncMock(
            side_effect=[[{"QUERY PLAN": "Aggregate"}], Exception("connection reset")]
        )
        synth = _sequenced_synthesizer(
            SynthesisResult(sql=VALID_SQL, explanation="valid but DB dies")
        )

        result = await _run(fs, synth, monkeypatch)

        assert result["status"] == "error"
        assert "estimated_cohort" not in result
        assert "execution failed" in result["reason"]
        # Execution errors do NOT retry — synthesize called exactly once.
        assert synth.synthesize.await_count == 1

    async def test_execution_error_reason_does_not_leak_the_exception_value(self, monkeypatch):
        # #96 review F1: a query can pass validation + EXPLAIN yet fail at
        # execution with an error embedding a raw column value. The user-facing
        # reason must carry only the exception TYPE, never the value — #39 keeps
        # this UI field unauthenticated.
        fs = FeasibilityService()
        fs.exploratory_db_client = MagicMock()
        leaked = 'invalid input syntax for type integer: "Alice Smith"'
        fs.exploratory_db_client.execute_query = AsyncMock(
            side_effect=[[{"QUERY PLAN": "Aggregate"}], Exception(leaked)]
        )
        synth = _sequenced_synthesizer(
            SynthesisResult(sql=VALID_SQL, explanation="valid, execution leaks")
        )

        result = await _run(fs, synth, monkeypatch)

        assert result["status"] == "error"
        assert "Alice Smith" not in result["reason"]
        assert "Alice Smith" not in str(result)

    async def test_llm_refusal_nonjson_is_error_variant_not_a_crash(self, monkeypatch):
        # #97 browser QA: when the model returns prose instead of JSON (e.g. it
        # declines a row-level request), synthesize() raises SynthesisError —
        # which must become the honest-error card, NOT an uncaught JSONDecodeError
        # traceback on the researcher's screen.
        from app.services.sql_synthesis import SynthesisError

        fs = FeasibilityService()
        fs.exploratory_db_client = MagicMock()
        fs.exploratory_db_client.execute_query = AsyncMock()
        synth = MagicMock()
        synth.synthesize = AsyncMock(side_effect=SynthesisError("model returned prose"))

        result = await _run(fs, synth, monkeypatch)

        assert result["status"] == "error"
        assert "estimated_cohort" not in result
        assert "model returned prose" in result["reason"]
        fs.exploratory_db_client.execute_query.assert_not_called()

    async def test_non_scalar_result_is_error_variant_not_fabricated_zero(self, monkeypatch):
        # A breakdown/empty result (the #76 shape) must become an error
        # variant, never a rendered 0.
        fs = FeasibilityService()
        fs.exploratory_db_client = MagicMock()
        fs.exploratory_db_client.execute_query = AsyncMock(
            side_effect=[[{"QUERY PLAN": "Aggregate"}], []]  # EXPLAIN ok, then empty
        )
        synth = _sequenced_synthesizer(
            SynthesisResult(sql=VALID_SQL, explanation="valid, empty result")
        )

        result = await _run(fs, synth, monkeypatch)

        assert result["status"] == "error"
        assert "estimated_cohort" not in result
