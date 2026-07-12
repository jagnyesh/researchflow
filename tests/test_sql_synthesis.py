"""Sprint 6.7 #91 — SQLSynthesizer tracer: single LLM call NL -> {sql, explanation}.

The LLM is mocked at the LLMClient boundary (external service). Wire-level and
live-model behavior are covered by the gated integration test and #98's eval
harness, not here.
"""

import json
from unittest.mock import AsyncMock

import pytest

from app.services.sql_synthesis import SQLSynthesizer, SynthesisResult


def _client_returning(payload: str) -> AsyncMock:
    client = AsyncMock()
    client.complete = AsyncMock(return_value=payload)
    return client


class TestSynthesize:
    async def test_returns_sql_and_explanation_from_json_response(self):
        client = _client_returning(
            json.dumps(
                {
                    "sql": "SELECT COUNT(DISTINCT p.patient_id) FROM sqlonfhir.patient_demographics p",
                    "explanation": "Counts all patients.",
                }
            )
        )

        result = await SQLSynthesizer(llm_client=client).synthesize("how many patients are there?")

        assert isinstance(result, SynthesisResult)
        assert result.sql.startswith("SELECT COUNT")
        assert result.explanation == "Counts all patients."

    async def test_strips_markdown_fences_from_llm_response(self):
        fenced = (
            "```json\n"
            + json.dumps(
                {"sql": "SELECT COUNT(*) FROM sqlonfhir.condition_simple", "explanation": "x"}
            )
            + "\n```"
        )
        client = _client_returning(fenced)

        result = await SQLSynthesizer(llm_client=client).synthesize("count conditions")

        assert result.sql == "SELECT COUNT(*) FROM sqlonfhir.condition_simple"

    async def test_calls_llm_once_at_temperature_zero_with_query_in_prompt(self):
        client = _client_returning(json.dumps({"sql": "SELECT 1", "explanation": "x"}))

        await SQLSynthesizer(llm_client=client).synthesize(
            "female patients with hypertension under 65"
        )

        client.complete.assert_awaited_once()
        kwargs = client.complete.await_args.kwargs
        assert kwargs["temperature"] == 0.0
        assert "female patients with hypertension under 65" in kwargs["prompt"]
        assert "sqlonfhir" in kwargs["system"]
