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
  - required_predicates: what the request requires, as canonical predicates
    (see formal_predicates.py): ("gender", "=", v), ("age", op, n),
    ("condition", "has" | "lacks", term). The phenotype SQL must carry exactly
    these, no more and no fewer (#242).
  - signoff: "pending" until an informatician approves the oracle's cohort
    definition; only "approved" cases count toward the gold-set score.
  - verified_count: the oracle's count on the local Synthea corpus when it was
    hand-verified, for the record (not used for scoring).
  - seed_count: the oracle's count on CI's 5-patient seed
    (tests/fixtures/hapi_seed/bundle.json), worked by hand. 0 means the case
    is vacuous in CI and must be local-only (#241).
  - expected_fail: why the current SQLGenerator can't express the request, ""
    when it can. Expected-fail cases stay in the Pass@1 denominator (#241).
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class FormalCase:
    id: str
    request: Dict
    oracle_sql: str
    required_predicates: List[Tuple[str, str, object]] = field(default_factory=list)
    signoff: str = "pending"
    verified_count: Optional[int] = None
    seed_count: Optional[int] = None
    expected_fail: str = ""


def _has_condition(term: str) -> str:
    return f"""EXISTS (
        SELECT 1 FROM sqlonfhir.condition_simple c
        WHERE c.patient_id = p.patient_id
          AND (c.code_text ILIKE '%{term}%'
               OR c.icd10_display ILIKE '%{term}%'
               OR c.snomed_display ILIKE '%{term}%'))"""


_AGE = "EXTRACT(YEAR FROM AGE(CURRENT_DATE, p.birth_date::date))"
_HBA1C = "(o.code_display ILIKE '%a1c%' OR o.code_text ILIKE '%a1c%')"
_INSULIN = """EXISTS (
        SELECT 1 FROM sqlonfhir.medication_requests m
        WHERE m.patient_id = p.patient_id
          AND (m.medication_display ILIKE '%insulin%' OR m.medication_text ILIKE '%insulin%'))"""


def _request(text: str, inclusion, exclusion=(), time_period=None) -> Dict:
    return {
        "initial_request": text,
        "structured_requirements": {
            "inclusion_criteria": list(inclusion),
            "exclusion_criteria": list(exclusion),
            "data_elements": ["demographics"],
            "time_period": time_period or {"start": None, "end": None},
        },
    }


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
            WHERE p.deceased IS NOT TRUE
              AND p.gender = 'female'
              AND p.birth_date::date <= CURRENT_DATE - INTERVAL '66 years'
              AND EXISTS (
                  SELECT 1 FROM sqlonfhir.condition_simple c
                  WHERE c.patient_id = p.patient_id AND {_DIABETES_MELLITUS}
              )
        """,
        required_predicates=[
            ("deceased", "=", False),
            ("gender", "=", "female"),
            ("age", ">", 65),
            ("condition", "has", "diabetes mellitus"),
        ],
        # Repo owner, 2026-11-04; re-approved living-only 2026-11-07 (#241).
        signoff="approved",
        verified_count=6,
        seed_count=0,  # no woman over 65 with diabetes on the seed: vacuous in CI
        expected_fail="the generator doesn't exclude deceased patients",
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
        required_predicates=[
            ("condition", "has", "hypertension"),
            ("condition", "lacks", "diabetes mellitus"),
        ],
        signoff="approved",  # repo owner, 2026-11-04
        verified_count=37,
        seed_count=3,
    ),
]

# #241: agent-drafted cases, signed off by the repo owner on 2026-11-07.
# Age cases count living patients only (repo owner, 2026-11-07); the request
# text doesn't say so, but a research cohort by age means patients alive now.
FORMAL_CASES += [
    FormalCase(
        id="hypertension_65_or_older",
        # Inclusive boundary: 2 living local patients are exactly 65 (16 at >= 65 vs 14 at > 65).
        request=_request(
            "Patients aged 65 or older with hypertension", ["65 or older", "hypertension"]
        ),
        oracle_sql=f"""
            SELECT p.patient_id FROM sqlonfhir.patient_demographics p
            WHERE p.deceased IS NOT TRUE AND {_AGE} >= 65 AND {_has_condition('hypertension')}
        """,
        required_predicates=[
            ("deceased", "=", False),
            ("age", ">=", 65),
            ("condition", "has", "hypertension"),
        ],
        signoff="approved",  # repo owner, 2026-11-07
        verified_count=16,
        seed_count=1,
        expected_fail="the generator doesn't exclude deceased patients; no inclusive age operator: '65 or older' doesn't parse, and '>= 65' parses as > 65",
    ),
    FormalCase(
        id="diabetes_mellitus_and_hypertension",
        request=_request(
            "Patients with both diabetes mellitus and hypertension",
            ["diabetes mellitus", "hypertension"],
        ),
        oracle_sql=f"""
            SELECT p.patient_id FROM sqlonfhir.patient_demographics p
            WHERE {_has_condition('diabetes mellitus')} AND {_has_condition('hypertension')}
        """,
        required_predicates=[
            ("condition", "has", "diabetes mellitus"),
            ("condition", "has", "hypertension"),
        ],
        signoff="approved",  # repo owner, 2026-11-07
        verified_count=43,
        seed_count=1,
    ),
    FormalCase(
        id="diabetes_mellitus_not_on_insulin",
        request=_request(
            "Patients with diabetes mellitus who have no insulin prescription",
            ["diabetes mellitus"],
            ["insulin use"],
        ),
        oracle_sql=f"""
            SELECT p.patient_id FROM sqlonfhir.patient_demographics p
            WHERE {_has_condition('diabetes mellitus')} AND NOT {_INSULIN}
        """,
        required_predicates=[
            ("condition", "has", "diabetes mellitus"),
            ("medication", "lacks", "insulin"),
        ],
        signoff="approved",  # repo owner, 2026-11-07
        verified_count=31,
        seed_count=2,
        expected_fail="no medication concept: generation fails on the insulin exclusion",
    ),
    FormalCase(
        id="hba1c_result_in_2025",
        # Time window. The local corpus's labs end 2025-05-29.
        request=_request(
            "Patients with a hemoglobin A1c result in 2025",
            ["hemoglobin A1c result"],
            time_period={"start": "2025-01-01", "end": "2025-12-31"},
        ),
        oracle_sql=f"""
            SELECT p.patient_id FROM sqlonfhir.patient_demographics p
            WHERE EXISTS (
                SELECT 1 FROM sqlonfhir.observation_labs o
                WHERE o.patient_id = p.patient_id AND {_HBA1C}
                  AND o.effective_datetime >= '2025-01-01' AND o.effective_datetime < '2026-01-01')
        """,
        required_predicates=[
            ("lab", "has", "a1c"),
            ("lab_date", "between", ("2025-01-01", "2025-12-31")),
        ],
        signoff="approved",  # repo owner, 2026-11-07
        verified_count=55,
        seed_count=2,
        expected_fail="time_period becomes p.lastUpdated, which isn't a view column (the SQL errors)",
    ),
    FormalCase(
        id="hba1c_above_8",
        # value_quantity is text in the view; cast before comparing.
        request=_request("Patients with any hemoglobin A1c result above 8%", ["HbA1c > 8%"]),
        oracle_sql=f"""
            SELECT p.patient_id FROM sqlonfhir.patient_demographics p
            WHERE EXISTS (
                SELECT 1 FROM sqlonfhir.observation_labs o
                WHERE o.patient_id = p.patient_id AND {_HBA1C}
                  AND o.value_quantity::numeric > 8)
        """,
        required_predicates=[("lab_value", ">", ("a1c", 8))],
        signoff="approved",  # repo owner, 2026-11-07
        verified_count=4,
        seed_count=1,
        expected_fail="lab criteria match by name only; there's no value threshold",
    ),
    FormalCase(
        id="men_over_40_without_hypertension",
        request=_request(
            "Male patients older than 40 without hypertension",
            ["male", "older than 40"],
            ["hypertension"],
        ),
        oracle_sql=f"""
            SELECT p.patient_id FROM sqlonfhir.patient_demographics p
            WHERE p.deceased IS NOT TRUE AND p.gender = 'male' AND {_AGE} > 40 AND NOT {_has_condition('hypertension')}
        """,
        required_predicates=[
            ("deceased", "=", False),
            ("gender", "=", "male"),
            ("age", ">", 40),
            ("condition", "lacks", "hypertension"),
        ],
        signoff="approved",  # repo owner, 2026-11-07
        verified_count=42,
        seed_count=1,
        expected_fail="the generator doesn't exclude deceased patients",
    ),
    FormalCase(
        id="women_under_50_with_hypertension",
        # Exclusive boundary: 1 local woman with hypertension is exactly 50 (2 at < 50 vs 3 at <= 50).
        request=_request(
            "Female patients younger than 50 with hypertension",
            ["female", "younger than 50", "hypertension"],
        ),
        oracle_sql=f"""
            SELECT p.patient_id FROM sqlonfhir.patient_demographics p
            WHERE p.deceased IS NOT TRUE AND p.gender = 'female' AND {_AGE} < 50 AND {_has_condition('hypertension')}
        """,
        required_predicates=[
            ("deceased", "=", False),
            ("gender", "=", "female"),
            ("age", "<", 50),
            ("condition", "has", "hypertension"),
        ],
        signoff="approved",  # repo owner, 2026-11-07
        verified_count=2,
        seed_count=1,
        expected_fail="the generator doesn't exclude deceased patients",
    ),
    FormalCase(
        id="hypertension_aged_50_to_60",
        # Inclusive range: 15 living local patients at 50..60 vs 10 at 51..59.
        request=_request(
            "Patients aged 50 to 60 with hypertension",
            ["between 50 and 60 years old", "hypertension"],
        ),
        oracle_sql=f"""
            SELECT p.patient_id FROM sqlonfhir.patient_demographics p
            WHERE p.deceased IS NOT TRUE AND {_AGE} BETWEEN 50 AND 60 AND {_has_condition('hypertension')}
        """,
        required_predicates=[
            ("deceased", "=", False),
            ("age", "between", (50, 60)),
            ("condition", "has", "hypertension"),
        ],
        signoff="approved",  # repo owner, 2026-11-07
        verified_count=15,
        seed_count=1,
        expected_fail="the generator doesn't exclude deceased patients; #242's predicate check has no BETWEEN template",
    ),
]
