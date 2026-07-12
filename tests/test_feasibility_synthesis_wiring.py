"""Sprint 6.7 #91 — FeasibilityService wiring for LLM SQL synthesis.

Contract under test (ADR 0028 decision 7):
- USE_LLM_SQL_SYNTHESIS unset/false => legacy path, synthesizer NEVER touched.
- Flag on + natural_language_query => synthesize -> validate -> execute via
  db_client; result dict keeps the legacy shape the notebook reads.
- Validator rejection => SQLValidationError raised and the SQL never reaches
  db_client (tracer semantics; #96 replaces the raise with the honest-error
  variant).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.feasibility_service import FeasibilityService
from app.services.sql_synthesis import SynthesisResult
from app.services.sql_validator import SQLValidationError

VALID_SQL = (
    "SELECT COUNT(DISTINCT p.patient_id) FROM sqlonfhir.patient_demographics p "
    "JOIN sqlonfhir.condition_simple c ON c.patient_id = p.patient_id "
    "WHERE p.gender = 'female'"
)


def _synthesizer_returning(sql: str, explanation: str = "test explanation") -> MagicMock:
    instance = MagicMock()
    instance.synthesize = AsyncMock(return_value=SynthesisResult(sql=sql, explanation=explanation))
    return instance


class TestFlagOff:
    async def test_legacy_path_untouched_and_synthesizer_never_called(self, monkeypatch):
        monkeypatch.delenv("USE_LLM_SQL_SYNTHESIS", raising=False)
        fs = FeasibilityService()
        fs._execute_count_query = AsyncMock(return_value=42)
        fs._calculate_data_availability = AsyncMock(return_value={})

        with patch("app.services.feasibility_service.SQLSynthesizer") as synth_cls:
            result = await fs.execute_feasibility_check(
                {"view_definitions": ["patient_demographics"], "search_params": {}},
                natural_language_query="how many patients?",
            )

        synth_cls.assert_not_called()
        assert result["estimated_cohort"] == 42


class TestFlagOn:
    async def test_synthesized_sql_validated_executed_and_mapped(self, monkeypatch):
        monkeypatch.setenv("USE_LLM_SQL_SYNTHESIS", "true")
        fs = FeasibilityService()
        fs.db_client = MagicMock()
        fs.db_client.execute_query = AsyncMock(return_value=[{"count": 13}])

        with patch(
            "app.services.feasibility_service.SQLSynthesizer",
            return_value=_synthesizer_returning(VALID_SQL),
        ):
            result = await fs.execute_feasibility_check(
                {"view_definitions": []},
                natural_language_query="female patients with hypertension under 65",
            )

        fs.db_client.execute_query.assert_awaited_once_with(VALID_SQL)
        assert result["estimated_cohort"] == 13
        assert result["generated_sql"] == VALID_SQL
        assert result["filter_summary"] == "test explanation"

    async def test_rejected_sql_raises_and_never_reaches_db(self, monkeypatch):
        monkeypatch.setenv("USE_LLM_SQL_SYNTHESIS", "true")
        fs = FeasibilityService()
        fs.db_client = MagicMock()
        fs.db_client.execute_query = AsyncMock()

        with patch(
            "app.services.feasibility_service.SQLSynthesizer",
            return_value=_synthesizer_returning("DELETE FROM sqlonfhir.patient_demographics"),
        ):
            with pytest.raises(SQLValidationError):
                await fs.execute_feasibility_check(
                    {"view_definitions": []},
                    natural_language_query="delete everything",
                )

        fs.db_client.execute_query.assert_not_called()

    async def test_breakdown_shaped_result_raises_never_a_fabricated_count(self, monkeypatch):
        # Tracer supports single-count queries only (#97 owns breakdown
        # rendering). A GROUP BY result must fail loudly, not int('female').
        monkeypatch.setenv("USE_LLM_SQL_SYNTHESIS", "true")
        fs = FeasibilityService()
        fs.db_client = MagicMock()
        fs.db_client.execute_query = AsyncMock(
            return_value=[{"gender": "female", "count": 5}, {"gender": "male", "count": 3}]
        )

        with patch(
            "app.services.feasibility_service.SQLSynthesizer",
            return_value=_synthesizer_returning(VALID_SQL),
        ):
            with pytest.raises(ValueError, match="scalar"):
                await fs.execute_feasibility_check(
                    {"view_definitions": []},
                    natural_language_query="patients by gender",
                )

    async def test_empty_result_raises_never_a_fabricated_zero(self, monkeypatch):
        # A COUNT query always returns one row; an empty result means something
        # is wrong. Rendering 0 here is exactly the #76 failure mode.
        monkeypatch.setenv("USE_LLM_SQL_SYNTHESIS", "true")
        fs = FeasibilityService()
        fs.db_client = MagicMock()
        fs.db_client.execute_query = AsyncMock(return_value=[])

        with patch(
            "app.services.feasibility_service.SQLSynthesizer",
            return_value=_synthesizer_returning(VALID_SQL),
        ):
            with pytest.raises(ValueError, match="scalar"):
                await fs.execute_feasibility_check(
                    {"view_definitions": []},
                    natural_language_query="female patients",
                )

    async def test_flag_on_without_nl_query_falls_back_to_legacy(self, monkeypatch):
        monkeypatch.setenv("USE_LLM_SQL_SYNTHESIS", "true")
        fs = FeasibilityService()
        fs._execute_count_query = AsyncMock(return_value=7)
        fs._calculate_data_availability = AsyncMock(return_value={})

        with patch("app.services.feasibility_service.SQLSynthesizer") as synth_cls:
            result = await fs.execute_feasibility_check(
                {"view_definitions": ["patient_demographics"], "search_params": {}}
            )

        synth_cls.assert_not_called()
        assert result["estimated_cohort"] == 7
