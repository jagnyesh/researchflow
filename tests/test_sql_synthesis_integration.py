"""Sprint 6.7 #91 — end-to-end: NL -> LLM SQL -> validator -> live HAPI.

Drives the #76 repro ("Female patients with hypertension under 65") through the
real synthesis path and compares against a SAME-RUN hand-written oracle (the
mv_row_count_oracles.sql pattern — dataset-size-independent, no pinned counts).
The retired legacy path returned 0 for this exact query (#76: stale p.dob +
swallowed exception); a non-zero oracle-matching count is the tracer's proof of
life.

Gated: requires the docker-compose stack (HAPI Postgres :5433 with materialized
views) and a real ANTHROPIC_API_KEY. #98's eval harness generalizes this single
case to ~30 scored cases.
"""

import os

import pytest
from dotenv import load_dotenv

from app.services.feasibility_service import FeasibilityService

load_dotenv()

# Hand-verified 2026-07-12 against live HAPI :5433 (returned 13 at time of
# writing; the assertion below is same-run, not pinned).
ORACLE_SQL = """
    SELECT COUNT(DISTINCT p.patient_id)
    FROM sqlonfhir.patient_demographics p
    JOIN sqlonfhir.condition_simple c ON c.patient_id = p.patient_id
    WHERE p.gender = 'female'
      AND p.birth_date::date > CURRENT_DATE - INTERVAL '65 years'
      AND (c.code_text ILIKE '%hypertension%'
           OR c.icd10_display ILIKE '%hypertension%'
           OR c.snomed_display ILIKE '%hypertension%')
"""


@pytest.mark.requires_services
@pytest.mark.requires_api_key
@pytest.mark.skipif(not os.getenv("ANTHROPIC_API_KEY"), reason="needs real ANTHROPIC_API_KEY")
class TestSynthesisEndToEnd:
    async def test_hypertension_under_65_matches_same_run_oracle(self):
        fs = FeasibilityService()

        result = await fs.execute_feasibility_check(
            {"view_definitions": []},
            natural_language_query="Female patients with hypertension under 65",
        )

        # #100: synthesis is the only path; the oracle runs through the same
        # read-only client the synthesized query used.
        oracle_rows = await fs.exploratory_db_client.execute_query(ORACLE_SQL)
        oracle_count = int(list(oracle_rows[0].values())[0])

        assert (
            oracle_count > 0
        ), "oracle itself found no patients — corpus problem, not a code problem"
        assert result["estimated_cohort"] == oracle_count
        assert result["generated_sql"].lstrip().upper().startswith("SELECT")
        assert result["filter_summary"], "explanation must accompany the SQL"
