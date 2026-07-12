"""SQL Synthesis — single LLM call turning a natural-language cohort question
into {sql, explanation} for the exploratory portal.

Sprint 6.7 #91 tracer (ADR 0028 decision 1). The schema block below is a
hardcoded stub; #94 replaces it with live information_schema introspection
shared with the validator. Retry/honest-failure handling lives in the caller
(#96), not here — this module does exactly one call.
"""

import json
import logging
from dataclasses import dataclass
from typing import Optional

from langsmith import traceable

from ..utils.llm_client import LLMClient

logger = logging.getLogger(__name__)


@dataclass
class SynthesisResult:
    sql: str
    explanation: str


# Stub schema block (#91). Column names + type warts verified against the live
# MVs via pg_catalog on 2026-07-12 (note: the 4 custom-path MVs do NOT appear
# in information_schema.columns — #94's introspection must use pg_catalog).
# Do NOT extend by hand; #94 makes live introspection the source.
_STUB_SCHEMA_BLOCK = """Available tables (Postgres, schema `sqlonfhir`) — these are the ONLY tables you may reference:

- sqlonfhir.patient_demographics(patient_id, gender, birth_date, family_name, given_name, city, state, postal_code)
- sqlonfhir.patient_simple(id, gender, birth_date)  -- no patient_id column; avoid for joins
- sqlonfhir.condition_simple(id, patient_id, icd10_code, icd10_display, snomed_code, snomed_display, code_text, clinical_status)
- sqlonfhir.condition_diagnoses(patient_id, icd10_code, icd10_display, snomed_code, snomed_display, code_text, recorded_date)
- sqlonfhir.observation_labs(patient_id, code, code_display, value_quantity, value_unit, effective_datetime)
- sqlonfhir.medication_requests(patient_id, status, medication_code, medication_display, authored_on)
- sqlonfhir.procedure_history(patient_id, status, cpt_code, cpt_display, snomed_code, snomed_display, performed_datetime)

Join key: patient_demographics.patient_id = <other>.patient_id.
IMPORTANT: birth_date is stored as TEXT — always cast: birth_date::date.
Age: "under 65" => birth_date::date > CURRENT_DATE - INTERVAL '65 years'.
Condition matching: case-insensitive substring OR across code_text, icd10_display, snomed_display
(the corpus is Synthea; SNOMED display text is the most reliably populated)."""

_SYSTEM_PROMPT = f"""You are a clinical research SQL writer for a FHIR analytics database.

{_STUB_SCHEMA_BLOCK}

Rules:
1. Produce exactly ONE Postgres SELECT statement. Never any other statement type.
2. Reference ONLY the sqlonfhir tables listed above, always schema-qualified.
3. Output must be a SINGLE aggregate count — exactly one row, one column
   (COUNT or COUNT DISTINCT). No GROUP BY breakdowns yet. Never raw patient
   rows or identifying columns (names, addresses, ids in output).
4. For cohort counts, count DISTINCT patients.
5. No SQL comments, no CTEs, no semicolons.

Respond with ONLY a JSON object, no markdown, in this exact shape:
{{"sql": "<the SQL statement>", "explanation": "<one plain-English sentence describing what the query counts>"}}"""


def _strip_markdown_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        first_newline = text.index("\n")
        text = text[first_newline + 1 :]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


class SQLSynthesizer:
    """One LLM call: natural language -> SynthesisResult."""

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm_client = llm_client or LLMClient()

    @traceable(name="sql_synthesis", tags=["sql-synthesis", "portal:exploratory"])
    async def synthesize(self, natural_language_query: str) -> SynthesisResult:
        response = await self.llm_client.complete(
            prompt=f"Write the SQL for this research question: {natural_language_query}",
            system=_SYSTEM_PROMPT,
            temperature=0.0,
        )
        data = json.loads(_strip_markdown_fences(response))
        result = SynthesisResult(sql=data["sql"], explanation=data["explanation"])
        logger.info("Synthesized SQL for query %r: %s", natural_language_query, result.sql)
        return result
