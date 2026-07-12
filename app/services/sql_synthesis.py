"""SQL Synthesis — single LLM call turning a natural-language cohort question
into {sql, explanation} for the exploratory portal.

Sprint 6.7 #91 tracer + #94 live schema block (ADR 0028 decisions 1+4). The
system prompt's schema knowledge comes from pg_catalog introspection at first
use (process-cached; reset via reset_schema_prompt_cache) — the database is
the only schema authority. Introspection failure is loud: a stale fallback
block would silently reintroduce the #76 drift class. Retry/honest-failure
handling lives in the caller (#96), not here — this module does exactly one
LLM call per synthesize().
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Optional

from langsmith import traceable

from ..clients.hapi_db_client import HAPIDBClient
from ..utils.llm_client import LLMClient
from .schema_introspection import get_cached_schemas, render_schema_block

logger = logging.getLogger(__name__)

# Declared here so the caching-threshold test derives its bound from the model
# this call site actually uses (_ANTHROPIC_CACHE_THRESHOLDS in llm_client:
# sonnet 1024, haiku 4096). Switching to Haiku makes the threshold test demand
# 4096 tokens automatically.
SYNTHESIS_MODEL = "claude-sonnet-4-6"


class SynthesisError(Exception):
    """The LLM did not return a usable {sql, explanation} JSON object — a
    refusal or malformed response, not a crash. The caller renders the honest
    error card (#97)."""


@dataclass
class SynthesisResult:
    sql: str
    explanation: str


# Hand-maintained domain guidance — NOT introspected. The authoritative column
# list is the introspected block rendered above this text; if a column named
# here is ever renamed, the two will disagree and #95's column checks catch the
# synthesized SQL at validation time.
_GUIDANCE_BLOCK = """Join and type guidance:

- Join key: patient_demographics.patient_id = <other>.patient_id.
  (patient_simple has NO patient_id column — avoid it for joins.)
- Date columns are stored as TEXT — always cast before comparing:
  birth_date::date, recorded_date::date, authored_on::date, etc.
- Age arithmetic: "under 65" => birth_date::date > CURRENT_DATE - INTERVAL '65 years';
  "over 18" => birth_date::date <= CURRENT_DATE - INTERVAL '18 years'.
- Condition matching: case-insensitive substring OR across code_text,
  icd10_display, snomed_display. The corpus is Synthea: SNOMED display text is
  the most reliably populated; icd10_display is often NULL — never rely on a
  single column.
- Medication matching: ILIKE on medication_display.
- Lab matching: ILIKE on code_display; numeric thresholds via value_quantity
  with value_unit sanity-checked in the WHERE clause.

Rules:
1. Produce exactly ONE Postgres SELECT statement. Never any other statement type.
2. Reference ONLY the sqlonfhir tables listed above, always schema-qualified.
3. Output must be a SINGLE aggregate count — exactly one row, one column
   (COUNT or COUNT DISTINCT). No GROUP BY breakdowns yet. Never raw patient
   rows or identifying columns (names, addresses, ids in output).
4. For cohort counts, count DISTINCT patients.
5. No SQL comments, no CTEs, no semicolons.

Worked examples:

Q: "Female patients with hypertension under 65"
{"sql": "SELECT COUNT(DISTINCT p.patient_id) FROM sqlonfhir.patient_demographics p JOIN sqlonfhir.condition_simple c ON c.patient_id = p.patient_id WHERE p.gender = 'female' AND p.birth_date::date > CURRENT_DATE - INTERVAL '65 years' AND (c.code_text ILIKE '%hypertension%' OR c.icd10_display ILIKE '%hypertension%' OR c.snomed_display ILIKE '%hypertension%')", "explanation": "Counts distinct female patients younger than 65 with any hypertension condition record."}

Q: "How many patients are on metformin?"
{"sql": "SELECT COUNT(DISTINCT m.patient_id) FROM sqlonfhir.medication_requests m WHERE m.medication_display ILIKE '%metformin%'", "explanation": "Counts distinct patients with at least one metformin medication request."}

Q: "Male patients over 18 with diabetes"
{"sql": "SELECT COUNT(DISTINCT p.patient_id) FROM sqlonfhir.patient_demographics p JOIN sqlonfhir.condition_simple c ON c.patient_id = p.patient_id WHERE p.gender = 'male' AND p.birth_date::date <= CURRENT_DATE - INTERVAL '18 years' AND (c.code_text ILIKE '%diabetes%' OR c.icd10_display ILIKE '%diabetes%' OR c.snomed_display ILIKE '%diabetes%')", "explanation": "Counts distinct adult male patients with any diabetes condition record."}

Respond with ONLY a JSON object, no markdown, in this exact shape:
{"sql": "<the SQL statement>", "explanation": "<one plain-English sentence describing what the query counts>"}"""


_system_prompt_cache: Optional[str] = None
_cache_lock = asyncio.Lock()


def reset_schema_prompt_cache() -> None:
    """Testing/ops hook. Note: a schema-changing MV rebuild while a portal
    process is up leaves this cache stale until process restart — same
    operational class as the known streamlit module-cache restart requirement
    (BACKLOG). Failure mode is loud (undefined column at execute), not
    silent-wrong."""
    global _system_prompt_cache
    _system_prompt_cache = None


def _build_system_prompt(schema_block: str) -> str:
    return (
        "You are a clinical research SQL writer for a FHIR analytics database.\n\n"
        f"{schema_block}\n\n{_GUIDANCE_BLOCK}"
    )


class SQLSynthesizer:
    """One LLM call: natural language -> SynthesisResult."""

    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        db_client: Optional[HAPIDBClient] = None,
    ):
        self.llm_client = llm_client or LLMClient()
        # HAPIDBClient's own default already reads HAPI_DB_URL. Single-DB
        # assumption: the process-level prompt cache is keyed on nothing, so
        # all synthesizers in a process must point at the same database.
        self.db_client = db_client or HAPIDBClient()

    async def _get_system_prompt(self) -> str:
        global _system_prompt_cache
        if _system_prompt_cache is None:
            async with _cache_lock:
                if _system_prompt_cache is None:
                    # Shared introspection cache — the SAME schemas object the
                    # validator checks columns against (#95), so prompt and
                    # validator can never diverge.
                    schemas = await get_cached_schemas(self.db_client)
                    _system_prompt_cache = _build_system_prompt(render_schema_block(schemas))
                    logger.info(
                        "Schema prompt built from live introspection (%d views, %d chars)",
                        len(schemas),
                        len(_system_prompt_cache),
                    )
        return _system_prompt_cache

    @traceable(name="sql_synthesis", tags=["sql-synthesis", "portal:exploratory"])
    async def synthesize(
        self, natural_language_query: str, feedback: Optional[str] = None
    ) -> SynthesisResult:
        """`feedback` (#96): the prior attempt's rejected SQL + validator
        violations, appended so the retry sees the specific rule it broke."""
        system_prompt = await self._get_system_prompt()
        prompt = f"Write the SQL for this research question: {natural_language_query}"
        if feedback:
            prompt += (
                f"\n\nYour previous attempt was REJECTED by the validator. Fix it:\n{feedback}"
            )
        response = await self.llm_client.complete(
            prompt=prompt,
            model=SYNTHESIS_MODEL,
            system=system_prompt,
            temperature=0.0,
        )
        # The model may return prose instead of JSON — e.g. it declines a
        # row-level PHI request, or emits a malformed object. That's a failure
        # to produce SQL, NOT a crash: raise a clean domain error so the caller
        # renders the honest-error card (#97; the raw JSONDecodeError otherwise
        # crashes the portal with a traceback).
        try:
            data = json.loads(_strip_markdown_fences(response))
            result = SynthesisResult(sql=data["sql"], explanation=data["explanation"])
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("LLM did not return usable synthesis JSON: %s", e)
            raise SynthesisError(
                "The model did not return a valid SQL query for this request."
            ) from e
        logger.info("Synthesized SQL for query %r: %s", natural_language_query, result.sql)
        return result


def _strip_markdown_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        first_newline = text.index("\n")
        text = text[first_newline + 1 :]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()
