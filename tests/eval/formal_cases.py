"""#239: gold cases for the Formal Portal's phenotype SQL.

Case format:
  - id: stable case id (used in the JSONL evidence).
  - request: the formal form fields a researcher submits: initial_request plus
    structured_requirements (inclusion/exclusion criteria, data elements,
    time period). The harness sends them through the Requirements Agent and
    SQLGenerator exactly as a real request goes (record mode), or replays the
    recorded requirements (CI).
  - oracle_sql: hand-written SQL over sqlonfhir.* selecting the correct
    cohort's patient_id. It runs against the same database as the generated
    SQL (same-run oracle), so counts are never hardcoded.
  - required_predicates: what the request requires, in words. The predicate
    check slice (#242) scores against this list.
  - signoff: "pending" until an informatician approves the oracle's cohort
    definition; only "approved" cases count toward the gold-set score.
  - verified_count: the oracle's count on the local Synthea corpus when it was
    hand-verified, for the record (not used for scoring).
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class FormalCase:
    id: str
    request: Dict
    oracle_sql: str
    required_predicates: List[str] = field(default_factory=list)
    signoff: str = "pending"
    verified_count: Optional[int] = None


_DIABETES_MELLITUS = """
    (c.code_text ILIKE '%diabetes mellitus%'
     OR c.icd10_display ILIKE '%diabetes mellitus%'
     OR c.snomed_display ILIKE '%diabetes mellitus%')
"""

FORMAL_CASES: List[FormalCase] = [
    FormalCase(
        id="female_over_65_diabetes_mellitus",
        # #206's synthetic case (REQ-20261030-B2B6AD86).
        request={
            "initial_request": "Female patients older than 65 with diabetes mellitus",
            "structured_requirements": {
                "inclusion_criteria": ["female", "older than 65", "diabetes mellitus"],
                "exclusion_criteria": [],
                "data_elements": ["demographics"],
                "time_period": {"start": None, "end": None},
            },
        },
        oracle_sql=f"""
            SELECT p.patient_id
            FROM sqlonfhir.patient_demographics p
            WHERE p.gender = 'female'
              AND p.birth_date::date <= CURRENT_DATE - INTERVAL '66 years'
              AND EXISTS (
                  SELECT 1 FROM sqlonfhir.condition_simple c
                  WHERE c.patient_id = p.patient_id AND {_DIABETES_MELLITUS}
              )
        """,
        required_predicates=["gender = female", "age > 65", "condition: diabetes mellitus"],
        signoff="approved",  # repo owner, 2026-11-04
        verified_count=13,
    ),
    FormalCase(
        id="hypertension_without_diabetes_mellitus",
        request={
            "initial_request": "Patients with hypertension who do not have diabetes mellitus",
            "structured_requirements": {
                "inclusion_criteria": ["hypertension"],
                "exclusion_criteria": ["diabetes mellitus"],
                "data_elements": ["demographics"],
                "time_period": {"start": None, "end": None},
            },
        },
        oracle_sql=f"""
            SELECT p.patient_id
            FROM sqlonfhir.patient_demographics p
            WHERE EXISTS (
                  SELECT 1 FROM sqlonfhir.condition_simple c
                  WHERE c.patient_id = p.patient_id
                    AND (c.code_text ILIKE '%hypertension%'
                         OR c.icd10_display ILIKE '%hypertension%'
                         OR c.snomed_display ILIKE '%hypertension%')
              )
              AND NOT EXISTS (
                  SELECT 1 FROM sqlonfhir.condition_simple c
                  WHERE c.patient_id = p.patient_id AND {_DIABETES_MELLITUS}
              )
        """,
        required_predicates=["condition: hypertension", "exclude condition: diabetes mellitus"],
        signoff="approved",  # repo owner, 2026-11-04
        verified_count=37,
    ),
]
