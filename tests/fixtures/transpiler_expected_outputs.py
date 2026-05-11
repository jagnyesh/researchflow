"""Hand-verified expected outputs for the SQL-on-FHIR transpiler correctness gate.

Data source: tests/fixtures/hapi_seed/bundle.json — a 5-patient hand-curated
FHIR transaction bundle that scripts/seed.sh POSTs into HAPI before pytest
runs in the service-dependent-tests CI job. Replaces the prior Synthea-based
dataset (361 patients) per /plan-eng-review on 2026-05-11. The pivot was
driven by GitHub's 100MB push limit, which the original "plain git pg_dump"
plan had assumed away.

Anchor expectations are sourced from direct queries against the populated
materialized views (psql -h localhost -p 5433 -U hapi -d hapi -c "SELECT ...
FROM sqlonfhir.<anchor> WHERE id LIKE 'fixture-%'"), captured after running
seed.sh + materialize_views.py --refresh against a clean hapi-db. They
represent what the transpiler actually emits — every value here can be
re-derived by re-running that pipeline.

The 5 fixture patients exercise all 15 cataloged Sprint 6.2 transpiler bugs:

- Bug 1 (id NULL on patient_simple): every fixture row's id == its fhir_id
- Bug 2 (deceasedDateTime extraction): patient A has deceasedDateTime;
  patients B-E have no deceased field (deceased=false, deceased_date=null).
  Matches Synthea's "deceasedDateTime OR field-absent" pattern. The
  deceasedBoolean:false path was explored and removed — `deceased.exists()`
  treats a present-but-false bool as deceased=true, which is a quirk of
  the view def, not a transpiler bug.
- Bug 3 (array-position swap on plain `name.family`): covered by the
  synthetic inline view def in test_bug3_array_position_regression; every
  patient's name[0].family is populated so the test gets non-null results.
- Bugs 4/5/6 (function-call parser for `coding.where(system=...)`):
  conditions a1/c1/d1 have BOTH ICD-10 + SNOMED codings, exercising the
  filter happy path. Conditions a2/b1/d2/e1 have SNOMED ONLY, exercising
  the filter no-match path (icd10_* columns must be NULL).
- Bug 7 (address.where(use='home') no-match): no fixture address has a
  `use` field, so address_line/city/state/postal_code are all NULL. Matches
  the documented Synthea behavior.
- Bug 8 (given.first() on multi-element array): patient B has
  given=["Jane","Marie"] — first()-extraction yields "Jane", proving the
  array indexing is correct.
- Bug 9 (MVR.get_schema v2-spec compliance): no fixture data needed; the
  test parses view defs directly.
- Bugs 10/11/12 (full_name concat + telecom): all 5 patients have
  family + given populated, all 5 have phone (no `use` filter — proves
  Synthea-pattern partial-filter still works), only patient B has email
  (proves email filter works independently of phone filter).
- Bug 13 (UNIQUE INDEX on id): structural; verified via has_unique_index_on_id
  helper. No fixture data dependency.
- Bugs 14/15 (non-anchor view defs materialize): MedicationRequest (2),
  Procedure (1), Observation (3) resources are present so non-anchor view
  defs produce at least some rows (or empty MVs that still materialize
  with correct schema).

Field-coverage note: every value below is sourced from a direct SQL query
against the actual MV after seed.sh runs. Address `country` is omitted from
sample_rows because it's not in the address-without-`use` filter result
(same as the prior fixture).
"""

PATIENT_SIMPLE = {
    "view_def": "patient_simple",
    "oracle_source": "hand-curated-fixture",
    "expected_row_count": 5,
    "sample_rows": {
        "fixture-patient-a": {
            "id": "fixture-patient-a",
            "active": None,
            "birth_date": "1925-04-16",
            "gender": "male",
        },
        "fixture-patient-b": {
            "id": "fixture-patient-b",
            "active": None,
            "birth_date": "1995-12-31",
            "gender": "female",
        },
        "fixture-patient-c": {
            "id": "fixture-patient-c",
            "active": None,
            "birth_date": "1980-01-01",
            "gender": "male",
        },
    },
    "key_column": "id",
}


PATIENT_DEMOGRAPHICS = {
    "view_def": "patient_demographics",
    "oracle_source": "hand-curated-fixture",
    "expected_row_count": 5,
    "sample_rows": {
        # Address fields are None because the fixture addresses have no `use`
        # field; the view def's `address.where(use = 'home').first()` returns
        # no match. Matches the documented Synthea behavior and the prior
        # fixture's address-coverage rationale. The view def, not the data,
        # defines correctness.
        "fixture-patient-a": {
            "id": "fixture-patient-a",
            "patient_id": "fixture-patient-a",
            "active": None,
            "birth_date": "1925-04-16",
            "gender": "male",
            "deceased": True,
            "deceased_date": "2001-02-03T01:13:45-06:00",
            "family_name": "Smith",
            "given_name": "Alice",
            "full_name": "Alice Smith",
            "phone": "555-1234",
            "email": None,
            "address_line": None,
            "city": None,
            "state": None,
            "postal_code": None,
        },
        "fixture-patient-b": {
            "id": "fixture-patient-b",
            "patient_id": "fixture-patient-b",
            "active": None,
            "birth_date": "1995-12-31",
            "gender": "female",
            "deceased": False,
            "deceased_date": None,
            "family_name": "Doe",
            "given_name": "Jane",
            "full_name": "Jane Doe",
            "phone": "555-5678",
            "email": "jane@example.com",
            "address_line": None,
            "city": None,
            "state": None,
            "postal_code": None,
        },
        "fixture-patient-c": {
            "id": "fixture-patient-c",
            "patient_id": "fixture-patient-c",
            "active": None,
            "birth_date": "1980-01-01",
            "gender": "male",
            "deceased": False,
            "deceased_date": None,
            "family_name": "Roe",
            "given_name": "John",
            "full_name": "John Roe",
            "phone": "555-2345",
            "email": None,
            "address_line": None,
            "city": None,
            "state": None,
            "postal_code": None,
        },
    },
    "key_column": "id",
}


CONDITION_SIMPLE = {
    "view_def": "condition_simple",
    "oracle_source": "hand-curated-fixture",
    "expected_row_count": 7,
    "sample_rows": {
        # cond-a1: ICD-10 + SNOMED (filter happy path on both column families)
        "fixture-cond-a1": {
            "id": "fixture-cond-a1",
            "patient_ref": "Patient/fixture-patient-a",
            "patient_id": "fixture-patient-a",
            "clinical_status": "active",
            "icd10_code": "I10",
            "icd10_display": "Essential (primary) hypertension",
            "snomed_code": "59621000",
            "snomed_display": "Essential hypertension (disorder)",
            "code_text": "Essential hypertension",
        },
        # cond-a2: SNOMED only (icd10_* must be NULL — filter no-match path)
        "fixture-cond-a2": {
            "id": "fixture-cond-a2",
            "patient_ref": "Patient/fixture-patient-a",
            "patient_id": "fixture-patient-a",
            "clinical_status": "active",
            "icd10_code": None,
            "icd10_display": None,
            "snomed_code": "82423001",
            "snomed_display": "Chronic pain (finding)",
            "code_text": "Chronic pain (finding)",
        },
        # cond-c1: diabetes with ICD-10 + SNOMED (drives the cohort test)
        "fixture-cond-c1": {
            "id": "fixture-cond-c1",
            "patient_ref": "Patient/fixture-patient-c",
            "patient_id": "fixture-patient-c",
            "clinical_status": "active",
            "icd10_code": "E11.9",
            "icd10_display": "Type 2 diabetes mellitus without complications",
            "snomed_code": "44054006",
            "snomed_display": "Diabetes mellitus type 2 (disorder)",
            "code_text": "Diabetes mellitus type 2 (disorder)",
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
