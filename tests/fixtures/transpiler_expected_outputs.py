"""Hand-verified expected outputs for the SQL-on-FHIR transpiler correctness gate.

Sources by anchor:

- patient_simple, patient_demographics, condition_simple → "hand-verified-sql":
  expected values come from direct SQL queries against HAPI's internal schema
  (hfj_resource + hfj_res_ver via res_text_vc::jsonb). These bypass both the
  custom transpiler AND fhirpathpy, so they are independent of any code under
  test. Anchor PASS is mandatory for the Phase 1.5 correctness gate.

- Other view defs (medication_requests, procedure_history, observation_labs,
  condition_diagnoses) → "in-memory-runner": expected values are derived from
  InMemoryRunner output. This is acceptable for non-anchor views with the
  documented limitation that fhirpathpy gaps (e.g., getResourceKey()) may
  propagate into the oracle.

Counts and sample values verified against the Synthea dataset loaded into HAPI
on feature/lambda-finish branch on 2026-05-09 (361 patients, 14,825 conditions,
229,867 observations).

Critical transpiler-relevant facts captured during oracle generation:

1. Patient `id` is NOT in the JSON body — it lives in hfj_resource.fhir_id.
   `path: "id"` in a ViewDefinition must source from the resource metadata.
2. Patient `active` field is null for all 361 Synthea patients. The where
   clause `active = true or active.exists().not()` includes all via the
   .exists().not() branch.
3. All 14,825 Synthea Conditions code only in SNOMED CT — zero ICD-10. The
   icd10_code and icd10_display columns must evaluate to NULL for all rows
   (transpiler should not crash on the where(system=...) filter; the filter
   should match no codings and .first() should yield NULL).
"""

PATIENT_SIMPLE = {
    "view_def": "patient_simple",
    "oracle_source": "hand-verified-sql",
    "expected_row_count": 361,
    "sample_rows": {
        "142387": {
            "id": "142387",
            "active": None,
            "birth_date": "1995-12-31",
            "gender": "female",
        },
        "143687": {
            "id": "143687",
            "active": None,
            "birth_date": "1956-09-11",
            "gender": "male",
        },
        "144735": {
            "id": "144735",
            "active": None,
            "birth_date": "1925-04-16",
            "gender": "male",
        },
    },
    "key_column": "id",
}


PATIENT_DEMOGRAPHICS = {
    "view_def": "patient_demographics",
    "oracle_source": "hand-verified-sql",
    "expected_row_count": 361,
    "sample_rows": {
        "142387": {
            "id": "142387",
            "patient_id": "142387",
            "active": None,
            "birth_date": "1995-12-31",
            "gender": "female",
            "deceased": False,
            "deceased_date": None,
            "family_name": "Abbott774",
            "given_name": "Valda518",
            "full_name": "Valda518 Abbott774",
            "phone": "555-377-9242",
            "email": None,
            "address_line": "593 Ratke Manor",
            "city": "Chicago",
            "state": "IL",
            "postal_code": "60651",
            "country": "US",
        },
        "143687": {
            "id": "143687",
            "patient_id": "143687",
            "active": None,
            "birth_date": "1956-09-11",
            "gender": "male",
            "deceased": False,
            "deceased_date": None,
            "family_name": "Runte676",
            "given_name": "Wendell199",
            "full_name": "Wendell199 Runte676",
            "phone": "555-643-1794",
            "email": None,
            "address_line": "447 Tromp Estate Unit 24",
            "city": "Alton",
            "state": "IL",
            "postal_code": "62024",
            "country": "US",
        },
        "144735": {
            "id": "144735",
            "patient_id": "144735",
            "active": None,
            "birth_date": "1925-04-16",
            "gender": "male",
            "deceased": True,
            "family_name": "Schiller186",
            "given_name": "Ozzie259",
            "full_name": "Ozzie259 Schiller186",
            "phone": "555-976-9197",
            "email": None,
            "address_line": "1091 Grimes Lodge",
            "city": "Romeoville",
            "state": "IL",
            "postal_code": "60441",
            "country": "US",
        },
    },
    "key_column": "id",
}


CONDITION_SIMPLE = {
    "view_def": "condition_simple",
    "oracle_source": "hand-verified-sql",
    "expected_row_count": 14825,
    "sample_rows": {
        "142389": {
            "id": "142389",
            "patient_ref": "Patient/142387",
            "patient_id": "142387",
            "clinical_status": "active",
            "icd10_code": None,
            "icd10_display": None,
            "snomed_code": "82423001",
            "snomed_display": "Chronic pain (finding)",
            "code_text": "Chronic pain (finding)",
        },
        "142390": {
            "id": "142390",
            "patient_ref": "Patient/142387",
            "patient_id": "142387",
            "clinical_status": "active",
            "icd10_code": None,
            "icd10_display": None,
            "snomed_code": "278860009",
            "snomed_display": "Chronic low back pain (finding)",
            "code_text": "Chronic low back pain (finding)",
        },
        "142396": {
            "id": "142396",
            "patient_ref": "Patient/142387",
            "patient_id": "142387",
            "clinical_status": "active",
            "icd10_code": None,
            "icd10_display": None,
            "snomed_code": "105531004",
            "snomed_display": "Housing unsatisfactory (finding)",
            "code_text": "Housing unsatisfactory (finding)",
        },
    },
    "key_column": "id",
}


ANCHOR_EXPECTATIONS = {
    "patient_simple": PATIENT_SIMPLE,
    "patient_demographics": PATIENT_DEMOGRAPHICS,
    "condition_simple": CONDITION_SIMPLE,
}


NON_ANCHOR_VIEW_DEFS = (
    "medication_requests",
    "procedure_history",
    "observation_labs",
    "condition_diagnoses",
)
