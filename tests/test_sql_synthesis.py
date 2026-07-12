"""Sprint 6.7 #91+#94 — SQLSynthesizer: single LLM call NL -> {sql, explanation},
system prompt built from live-introspected schema (process-cached).

The LLM is mocked at the LLMClient boundary (external service); introspection
is stubbed via the autouse fixture so unit tests never need a DB. Wire-level
and live-model behavior are covered by the gated integration tests and #98's
eval harness, not here.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

import app.services.sql_synthesis as sql_synthesis_module
from app.services.schema_introspection import (
    ColumnInfo,
    SchemaIntrospectionError,
    ViewSchema,
)
from app.services.sql_synthesis import SQLSynthesizer, SynthesisResult

CANNED_SCHEMAS = {
    "patient_demographics": ViewSchema(
        name="patient_demographics",
        description="Core demographics",
        columns=(
            ColumnInfo("patient_id", "text"),
            ColumnInfo("gender", "text"),
            ColumnInfo("birth_date", "text"),
            ColumnInfo("zz_marker_col", "text"),
        ),
    ),
}


@pytest.fixture(autouse=True)
def _hermetic_schema():
    """Reset the process-level prompt cache and stub the shared introspection
    cache (#95: one getter serves prompt AND validator) so unit tests never
    need a DB."""
    sql_synthesis_module.reset_schema_prompt_cache()
    with patch(
        "app.services.sql_synthesis.get_cached_schemas",
        new=AsyncMock(return_value=CANNED_SCHEMAS),
    ) as mock_introspect:
        yield mock_introspect
    sql_synthesis_module.reset_schema_prompt_cache()


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


class TestIntrospectedSchemaBlock:
    async def test_system_prompt_contains_introspected_columns(self, _hermetic_schema):
        # #94: the prompt's schema knowledge comes from live introspection,
        # not a hand-maintained stub. zz_marker_col exists only in the canned
        # introspection result — its presence proves the source.
        client = _client_returning(json.dumps({"sql": "SELECT 1", "explanation": "x"}))

        await SQLSynthesizer(llm_client=client).synthesize("any query")

        system = client.complete.await_args.kwargs["system"]
        assert "zz_marker_col" in system
        assert "birth_date text" in system

    async def test_introspection_runs_once_per_process_across_synthesizers(self, _hermetic_schema):
        client = _client_returning(json.dumps({"sql": "SELECT 1", "explanation": "x"}))

        await SQLSynthesizer(llm_client=client).synthesize("first")
        await SQLSynthesizer(llm_client=client).synthesize("second")

        assert _hermetic_schema.await_count == 1

    async def test_introspection_failure_is_loud_no_stub_fallback(self, _hermetic_schema):
        # A stale fallback block would silently reintroduce the #76 drift
        # class. If the DB is unreachable, synthesis must fail, not guess.
        _hermetic_schema.side_effect = SchemaIntrospectionError("db unreachable")
        client = _client_returning(json.dumps({"sql": "SELECT 1", "explanation": "x"}))

        with pytest.raises(SchemaIntrospectionError):
            await SQLSynthesizer(llm_client=client).synthesize("any query")

        client.complete.assert_not_awaited()


class TestCacheControlWireLevel:
    """#94 acceptance: cache_control must arrive in the outbound Anthropic
    `system` kwarg for the SYNTHESIS call site — the Sprint 8.2 bug class
    (langchain-anthropic drops cache_control on string-form system params).
    Mocks AsyncMessages.create, the actual SDK entrypoint (wire layer, not
    wrapper layer)."""

    async def test_synthesis_system_prompt_reaches_wire_with_cache_control(self, monkeypatch):
        from anthropic.resources.messages.messages import AsyncMessages
        from unittest.mock import MagicMock

        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-for-mock")
        captured_kwargs = {}

        async def capture_create(self, *args, **kwargs):
            captured_kwargs.update(kwargs)
            response = MagicMock()
            response.content = [
                MagicMock(type="text", text='{"sql": "SELECT 1", "explanation": "x"}')
            ]
            response.stop_reason = "end_turn"
            response.usage = MagicMock(
                input_tokens=10,
                output_tokens=5,
                cache_creation_input_tokens=0,
                cache_read_input_tokens=0,
            )
            response.id = "msg_test"
            response.model = "claude-sonnet-4-6"
            response.role = "assistant"
            response.type = "message"
            return response

        with patch.object(AsyncMessages, "create", new=capture_create):
            from app.utils.llm_client import LLMClient

            try:
                await SQLSynthesizer(llm_client=LLMClient()).synthesize("count patients")
            except Exception:
                # Only the captured outbound kwargs matter; the mock response
                # shape may not survive the parser.
                pass

        system_param = captured_kwargs.get("system")
        assert system_param is not None, "synthesis call never reached the Anthropic SDK"
        assert isinstance(system_param, list), (
            "system param is string-form — cache_control is silently dropped "
            "(the 6-month Sprint 8 bug)"
        )
        first_block = system_param[0]
        assert first_block.get("type") == "text"
        assert "cache_control" in first_block
        assert first_block["cache_control"] == {"type": "ephemeral"}
        # And it is OUR introspected schema prompt on the wire, not a default.
        assert "zz_marker_col" in first_block["text"]
