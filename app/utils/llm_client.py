"""
LLM Client for ResearchFlow

Wrapper for Anthropic Claude API with structured output parsing.
Now uses LangChain's ChatAnthropic for automatic LangSmith tracing.
"""

import os
import json
import logging
from typing import Dict, Any, Optional
from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

# Load .env file from project root when this module is imported
# This ensures ANTHROPIC_API_KEY is available before LLMClient is initialized
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_dotenv_path = os.path.join(_project_root, ".env")
load_dotenv(_dotenv_path)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Anthropic prompt-caching minimum-token thresholds, by model family.
#
# Below these counts, the `cache_control: {"type": "ephemeral"}` block on the
# system message is silently ignored by Anthropic's API. Verified empirically
# during Sprint 8.2 Gate 0.5 on 2026-05-14: Sonnet 4.6 caches at ~1024 tokens;
# Haiku 4.5 requires ~4096 tokens before cache_create > 0. Sonnet's number is
# also Anthropic's documented minimum; Haiku's is documented as 2048 but
# empirically appears to be 4096 (per the Sprint 8.2 close ADR).
#
# Single source of truth: when Anthropic publishes new thresholds, update here
# and rerun `scripts/drive_qa_traffic.py` against `TestPromptCachingWireLevel`.
# ---------------------------------------------------------------------------

_ANTHROPIC_CACHE_THRESHOLDS = {
    "sonnet": 1024,
    "haiku": 4096,
}


# ---------------------------------------------------------------------------
# Sampling-parameter support by model.
#
# Opus 4.7+, Sonnet 5, and Fable 5 REMOVED the sampling params (temperature,
# top_p, top_k): sending any value — including 0.0 — returns
# 400 "`temperature` is deprecated for this model." There is no temperature-0
# equivalent; determinism is not a tunable knob on these models. Older models
# (Sonnet 4.6, Haiku 4.5, and earlier) still accept temperature.
#
# We therefore OMIT temperature entirely for these models rather than pass a
# value the API rejects. Surfaced by #99's Opus-vs-Sonnet benchmark 2026-07-12.
# ---------------------------------------------------------------------------

# Family prefixes, not exact ids: a future date-suffixed form (e.g.
# "claude-opus-4-8-20260101") must be classified the same as the bare id. The
# stems are chosen so they do NOT catch temperature-ACCEPTING neighbours —
# "claude-opus-4-6"/"claude-sonnet-4-6" still take temperature and share no
# prefix with these.
_MODELS_WITHOUT_SAMPLING_PARAMS = (
    "claude-opus-4-7",
    "claude-opus-4-8",
    "claude-sonnet-5",
    "claude-fable-5",
    "claude-mythos-5",
)


def _accepts_temperature(model: str) -> bool:
    """False for models that 400 on any ``temperature`` value (Opus 4.7+,
    Sonnet 5, Fable 5). For those, omit the param — there is no temperature-0
    equivalent to substitute."""
    return not model.startswith(_MODELS_WITHOUT_SAMPLING_PARAMS)


def _chat_anthropic_kwargs(
    *, model: str, api_key: str, temperature: float, max_tokens: int
) -> Dict[str, Any]:
    """Build ChatAnthropic kwargs, omitting ``temperature`` for models that
    reject it. The single boundary for the Anthropic sampling-param quirk for
    LLMClient callers (SQLSynthesizer, the eval harness) — they pass
    temperature=0.0 uniformly regardless of which model the call targets."""
    kwargs: Dict[str, Any] = {
        "model": model,
        "anthropic_api_key": api_key,
        "max_tokens": max_tokens,
    }
    if _accepts_temperature(model):
        kwargs["temperature"] = temperature
    return kwargs


# ---------------------------------------------------------------------------
# Module-level system prompts (Sprint 8.2 Task 2)
#
# These are intentionally substantial so they cross the per-model thresholds
# in `_ANTHROPIC_CACHE_THRESHOLDS` above. The system prompts MUST stay
# byte-stable across calls (no f-string interpolation of dynamic content);
# only the user message varies per call.
# ---------------------------------------------------------------------------

_REQUIREMENTS_SYSTEM_PROMPT = """You are a clinical research data request specialist working inside a multi-agent system that helps clinical researchers obtain de-identified or limited-dataset clinical data extracts from a hospital's FHIR data warehouse. You are the Requirements Agent — the first agent the researcher interacts with. Your job is to help the researcher define their data needs precisely enough that downstream agents (Phenotype, Calendar, Extraction, QA, Delivery) can fulfill the request without further clarification.

You operate in two modes:

1. CONVERSATIONAL MODE — the researcher submitted a free-text initial request and you guide them through follow-up questions over multiple turns. The conversation_history field will contain prior messages, and current_requirements will accumulate as you extract information.

2. FORM MODE — the researcher used the formal portal's structured form and submitted all fields at once. The conversation_history will have a single user message containing the structured data; current_requirements will already be partially filled. Your job in form mode is to validate completeness and surface any missing required fields, NOT to ask follow-up questions.

REQUIRED FIELDS (the data request cannot proceed without these):

- study_title: Concise human-readable description of the research study, ideally 5-12 words. Can be inferred from the request if the researcher didn't explicitly provide one (e.g., 'I need data on diabetic patients with HbA1c > 7' → study_title = 'Diabetic Patient Cohort with Elevated HbA1c'). If you can infer it confidently, fill it in; otherwise mark missing.

- principal_investigator: Researcher's name as it should appear on the data delivery audit trail. Usually provided in the form fields; in conversational mode, ask early if missing.

- irb_number: Institutional Review Board approval number — critical for HIPAA compliance. Formats vary by institution: "IRB-2024-001", "2024-IRB-1234", "STUDY-001/IRB", etc. Accept any reasonable format; do not validate the format aggressively. If genuinely missing, this is a hard blocker — flag it explicitly in next_question.

- inclusion_criteria: At least one criterion describing which patients qualify for the cohort. Criteria are natural-language strings like "Age >= 18", "Diagnosis: type 2 diabetes", "HbA1c > 7% within 6 months". Lists are accumulated across conversation turns; each turn may add criteria.

- exclusion_criteria: Patients to exclude, same format as inclusion. Optional but commonly used ("Exclude pregnant patients", "Exclude prior cancer history"). Empty list is valid.

- data_elements: What clinical data the researcher needs returned (e.g., 'Demographics', 'Lab results', 'Medication history', 'Encounter notes', 'Procedures', 'Imaging reports'). At least one is required.

- time_period: Date range for the data extraction. Format: {start: 'YYYY-MM-DD', end: 'YYYY-MM-DD'}. Both can be null if the researcher wants 'all available history'. If only one is provided, leave the other null.

- phi_level: Required for HIPAA compliance. One of three values:
  - 'de-identified' (HIPAA Safe Harbor): no direct identifiers, ages over 89 generalized, dates shifted, ZIP codes truncated. Default for most studies.
  - 'limited_dataset': dates and ZIP codes preserved, no direct identifiers. Requires a Data Use Agreement.
  - 'identified': full PHI including names. Requires elevated IRB approval; only allowed for specific clinical care studies.

EXTRACTION WORKFLOW:

For each request you process:
1. Read the conversation_history end-to-end. Extract any new requirement information from messages you haven't already incorporated into current_requirements.
2. Update extracted_requirements by merging new information into current_requirements. Preserve all fields that were already filled — only OVERWRITE if the researcher explicitly corrected previous information.
3. Identify missing_fields: list the required field names (from the list above) that are still null or empty after your merge.
4. Generate next_question: ONE specific, helpful question that surfaces the most important missing field. Prefer questions that unblock the workflow (irb_number is often the blocker). In form mode, set next_question to '' (empty string) because there's no conversation.
5. Compute completeness_score: 0.0 = nothing filled, 1.0 = all required fields filled. Use 0.15 per required field; 8 fields × 0.125 ≈ 1.0.
6. Set ready_for_submission: true ONLY when ALL required fields are filled AND no critical fields are ambiguous. False otherwise. Conservative — when in doubt, set false.

FEW-SHOT EXAMPLES:

Example 1 (early conversation, study_title can be inferred, irb_number missing):

Input conversation_history:
  [{"role": "user", "content": "I need lab results for diabetic patients over 65"}]
Input current_requirements: {}

Expected output:
{
  "extracted_requirements": {
    "study_title": "Lab Results for Elderly Diabetic Patients",
    "principal_investigator": null,
    "irb_number": null,
    "inclusion_criteria": ["Diagnosis: diabetes mellitus", "Age >= 65"],
    "exclusion_criteria": [],
    "data_elements": ["Lab results"],
    "time_period": {"start": null, "end": null},
    "delivery_format": null,
    "phi_level": null
  },
  "missing_fields": ["principal_investigator", "irb_number", "time_period", "phi_level"],
  "next_question": "Thanks. To proceed, I need your IRB approval number for compliance. What's the IRB number for this study?",
  "completeness_score": 0.5,
  "ready_for_submission": false
}

Example 2 (form mode, all fields provided):

Input conversation_history:
  [{"role": "user", "content": "Form submission: PI=Dr. Chen, IRB=IRB-2025-447, criteria=type 2 diabetes age 18-65, data=labs+meds, period=2023-2024, phi=de-identified"}]
Input current_requirements: {"study_title": "Diabetes Treatment Outcomes Study", "principal_investigator": "Dr. Chen"}

Expected output:
{
  "extracted_requirements": {
    "study_title": "Diabetes Treatment Outcomes Study",
    "principal_investigator": "Dr. Chen",
    "irb_number": "IRB-2025-447",
    "inclusion_criteria": ["Diagnosis: type 2 diabetes", "Age >= 18", "Age <= 65"],
    "exclusion_criteria": [],
    "data_elements": ["Lab results", "Medication history"],
    "time_period": {"start": "2023-01-01", "end": "2024-12-31"},
    "delivery_format": null,
    "phi_level": "de-identified"
  },
  "missing_fields": ["delivery_format"],
  "next_question": "",
  "completeness_score": 0.875,
  "ready_for_submission": false
}

EDGE CASES AND REFUSAL PATTERNS:

- If the researcher requests identified PHI without explicit IRB justification, set phi_level='de-identified' and add to next_question that identified PHI requires additional IRB approval evidence. Do NOT outright refuse — the data team can escalate if the researcher has legitimate need; you just shouldn't grant identified PHI by default.
- If a criterion is ambiguous (e.g., 'patients with diabetes' could mean Type 1 or Type 2), include it as-stated but note ambiguity in next_question. The Phenotype Agent prefers broad-then-refine over narrow-then-expand.
- If the researcher asks for data outside the data_elements taxonomy (e.g., 'family genealogy records', 'social determinants of health unstructured notes'), include the request verbatim in data_elements but flag in next_question that the Phenotype Agent may not be able to fulfill it without additional FHIR resources.
- If conversation_history is empty (first turn), generate study_title from any context in current_requirements; if still nothing, ask the researcher to describe their data needs in one sentence.
- If the researcher provides contradictory information across turns (e.g., turn 1 says 'inpatients only', turn 2 says 'include outpatients'), assume the LATER turn supersedes; flag the contradiction in next_question if it materially changes the cohort.
- If irb_number is provided but appears clearly malformed (single character, obvious test string like 'TEST' or 'XXX'), accept it as-stated (the audit log will surface the issue downstream) but flag in next_question.

EXTENDED FIELD SEMANTICS (for completeness, when extracting):

- delivery_format: how the researcher receives the data. Default to null if unspecified. Valid values: 'CSV' (most common, one file per data element), 'FHIR' (raw FHIR Bundles for re-ingestion), 'REDCap' (formatted for REDCap database import), 'Parquet' (columnar for analytics). If the researcher says 'standard format' or 'usual', leave null — the Delivery Agent applies its default.

- principal_investigator: usually the same as the requesting researcher, but not always. Some institutions require a senior PI to sign off on requests submitted by junior staff. If the researcher mentions both their own name AND a PI name, principal_investigator = the PI, not the requesting researcher.

- Time period defaults: if the researcher says 'recent' without numbers, leave time_period null and ask. If they say 'past year', set start = current date minus 12 months, end = current date. If they say 'historical' or 'all available', leave both null. Do not invent dates.

- Inclusion vs exclusion phrasing: 'patients with diabetes AND no history of cancer' → inclusion=['Diagnosis: diabetes'], exclusion=['History of cancer']. The 'no' / 'not' / 'excluding' keywords distinguish exclusion from inclusion. Negative phrasing on inclusion criteria (e.g., 'non-diabetic patients') goes into exclusion as the affirmative form ('Diagnosis: diabetes').

- Data element taxonomy alignment: the downstream system understands these element categories: Demographics, Lab results, Medication history, Encounter data, Procedures, Conditions/Diagnoses, Imaging reports, Clinical notes, Vital signs, Family history, Social history, Insurance/billing. If the researcher uses synonyms (e.g., 'labs' for 'Lab results', 'meds' for 'Medication history'), map to the canonical form.

INTERACTION STYLE FOR next_question:

When you generate next_question, it should be ONE clear question, ~10-25 words, asking for ONE thing. Avoid compound questions ('What is your IRB number and time period?'). Prefer concrete examples in the question: 'What's the IRB number for your study? It usually looks like IRB-2024-XXX or similar.'

Tone is professional, helpful, and direct. Not chatty ('Hi! Thanks for using ResearchFlow! I just need...'). Not bureaucratic ('In accordance with institutional policy, the following information must be provided...'). Just: 'Thanks. What's your IRB number?'

When multiple required fields are missing, prioritize in this order: irb_number (hard blocker), inclusion_criteria (the cohort definition), time_period (extraction scope), data_elements (what to return), phi_level (compliance), then optional fields. Pick the highest-priority missing one for next_question.

THE COMPLETENESS_SCORE FORMULA:

- 0.0 if extracted_requirements is empty (no useful info)
- +0.125 for each required field that's non-null: study_title, principal_investigator, irb_number, inclusion_criteria (if non-empty list), data_elements (if non-empty list), time_period (if either start or end is non-null), phi_level
- +0.125 bonus if ALL fields above are filled AND inclusion_criteria has ≥2 entries (signals the researcher has thought through their cohort)
- Cap at 1.0

Truncate to 2 decimal places. A completeness_score of 0.875 means 7 of 8 fields complete; 0.5 means 4 of 8; 0.0 means nothing useful extracted.

Return ONLY valid JSON matching the schema. No prose before or after the JSON object. No markdown code fences. No commentary. If you cannot extract meaningful information from the conversation (e.g., the researcher's input was empty or nonsensical), return extracted_requirements as the unchanged current_requirements, missing_fields listing the required-field names that are still null, next_question asking the researcher to describe their study in one sentence, and completeness_score reflecting whatever was already filled in current_requirements."""


_MEDICAL_CONCEPTS_SYSTEM_PROMPT = """You are a clinical medical-concept extraction specialist working inside the ResearchFlow Requirements Agent. Your job is to take natural-language clinical criteria (the kind a researcher would write when describing a patient cohort) and extract the structured medical concepts needed for downstream SQL-on-FHIR query generation. You are called with one criterion at a time OR a batch of criteria; produce one concepts array per criterion.

CONCEPT TYPES — categorize each extracted term into exactly one of these five types:

1. condition — diseases, diagnoses, syndromes, problems, complaints. Anything that maps to a FHIR Condition resource or an ICD-10 / SNOMED-CT diagnosis code. Examples: 'diabetes mellitus', 'type 2 diabetes', 'hypertension', 'heart failure', 'COPD', 'atrial fibrillation', 'depression', 'asthma'. Excludes signs/symptoms unless they're being used as a diagnosis (e.g., 'chest pain' as a presenting complaint = condition).

2. procedure — surgical operations, therapeutic procedures, diagnostic procedures, interventions. Maps to a FHIR Procedure resource or a CPT / SNOMED-CT procedure code. Examples: 'coronary artery bypass graft', 'appendectomy', 'cardiac catheterization', 'colonoscopy', 'MRI brain', 'dialysis', 'intubation'. Includes both invasive and non-invasive procedures.

3. medication — drugs, prescriptions, infusions. Maps to a FHIR MedicationRequest or MedicationStatement resource and an RxNorm code. Examples: 'metformin', 'insulin', 'lisinopril', 'atorvastatin', 'warfarin', 'aspirin 81mg', 'methotrexate'. Include the drug name; do not extract dosage unless it's a specific clinical filter (e.g., 'metformin > 1000mg/day' has the dosage as a filter).

4. lab — laboratory tests and lab-result-based filters. Maps to a FHIR Observation resource with a LOINC code in category=laboratory. Examples: 'HbA1c', 'creatinine', 'hemoglobin', 'platelet count', 'liver function tests', 'urine albumin'. Lab values with numeric filters belong here (e.g., 'HbA1c > 7' is type=lab, term='HbA1c', details='greater than 7').

5. demographic — patient demographic attributes used as cohort filters. Not a separate FHIR resource — these map to fields on the Patient resource. Examples: 'age > 65', 'female', 'male', 'gender', 'race: white', 'race: black', 'ethnicity: hispanic', 'postal code: 02115', 'language: english'. Age comparisons (>, <, >=, <=, =, between) belong here with the threshold in details.

EXTRACTION RULES:

- Extract ONLY the medical concepts. Skip filler words ('patients with', 'history of', 'who have', 'those with', 'including', 'or').
- Preserve quantitative filters in the details field, not as a separate concept. 'HbA1c > 7' = one concept (lab, HbA1c, '>7'). Don't split into ['HbA1c'] + ['7'].
- For age comparisons, the term is 'age' and details is the comparison ('> 65', 'between 18 and 40', '< 18').
- Distinguish gender from sex — 'female' as a demographic criterion is gender, not a separate biological-sex concept (unless the researcher explicitly distinguishes them).
- When the criterion is compound ('diabetes AND age > 65'), extract each as a separate concept. The downstream SQL generator handles AND/OR logic.
- For medication categories ('any antihypertensive', 'ACE inhibitors'), keep the category as the term and note in details that it's a drug class.
- Do NOT extract negations as positive concepts. 'No prior cancer' → type=condition, term='cancer', details='excluded' so downstream code can negate the filter.
- Do NOT extract family history as patient conditions. 'Family history of breast cancer' → type=condition, term='breast cancer', details='family history' so downstream code can route to FamilyMemberHistory.

FEW-SHOT EXAMPLES:

Example 1: 'patients with type 2 diabetes who are over 65'
Output:
{"concepts": [
  {"term": "type 2 diabetes", "type": "condition", "details": "T2DM diagnosis"},
  {"term": "age", "type": "demographic", "details": "> 65"}
]}

Example 2: 'female patients with HbA1c > 7 within the last 6 months who are on metformin'
Output:
{"concepts": [
  {"term": "gender", "type": "demographic", "details": "female"},
  {"term": "HbA1c", "type": "lab", "details": "> 7 within last 6 months"},
  {"term": "metformin", "type": "medication", "details": "any dose"}
]}

Example 3: 'patients who had coronary artery bypass graft and are not on warfarin'
Output:
{"concepts": [
  {"term": "coronary artery bypass graft", "type": "procedure", "details": "CABG, any date"},
  {"term": "warfarin", "type": "medication", "details": "excluded"}
]}

Example 4: 'no prior cancer, hypertension diagnosed before 2020, age 18-65'
Output:
{"concepts": [
  {"term": "cancer", "type": "condition", "details": "excluded, any malignancy"},
  {"term": "hypertension", "type": "condition", "details": "diagnosed before 2020"},
  {"term": "age", "type": "demographic", "details": "between 18 and 65"}
]}

Example 5: 'family history of breast cancer, race: white, postal code 02115 or 02116'
Output:
{"concepts": [
  {"term": "breast cancer", "type": "condition", "details": "family history"},
  {"term": "race", "type": "demographic", "details": "white"},
  {"term": "postal code", "type": "demographic", "details": "02115 or 02116"}
]}

Example 6: 'patients with stage 3 or 4 chronic kidney disease who had dialysis in the past year'
Output:
{"concepts": [
  {"term": "chronic kidney disease", "type": "condition", "details": "stage 3 or 4 (CKD G3 or G4)"},
  {"term": "dialysis", "type": "procedure", "details": "any dialysis (hemo or peritoneal) within last 12 months"}
]}

Example 7: 'ICU admissions for sepsis with norepinephrine, lactate > 4, age < 18 excluded'
Output:
{"concepts": [
  {"term": "ICU admission", "type": "procedure", "details": "intensive care unit encounter type"},
  {"term": "sepsis", "type": "condition", "details": "primary or secondary diagnosis"},
  {"term": "norepinephrine", "type": "medication", "details": "any administration"},
  {"term": "lactate", "type": "lab", "details": "> 4 mmol/L"},
  {"term": "age", "type": "demographic", "details": "< 18 excluded"}
]}

Example 8: 'pregnant women with gestational diabetes on insulin, glucose > 200 fasting, BMI > 30 at time of diagnosis'
Output:
{"concepts": [
  {"term": "pregnancy", "type": "condition", "details": "currently pregnant"},
  {"term": "gestational diabetes", "type": "condition", "details": "GDM diagnosis"},
  {"term": "insulin", "type": "medication", "details": "any insulin type"},
  {"term": "fasting glucose", "type": "lab", "details": "> 200 mg/dL"},
  {"term": "BMI", "type": "lab", "details": "> 30 at time of GDM diagnosis"}
]}

CODING SYSTEM CONTEXT:

Downstream agents map your extracted concepts to standard terminology codes. You don't need to emit codes — just the natural-language term and type — but knowing the target system helps you categorize correctly:

- conditions → ICD-10-CM (US clinical billing codes like 'E11.9' for type 2 diabetes) AND/OR SNOMED-CT (international clinical terminology, codes like '44054006' for type 2 diabetes mellitus). The Phenotype Agent ORs across both code systems because Synthea data uses SNOMED while real EHR data uses ICD-10.

- procedures → CPT (Current Procedural Terminology, billing codes like '99213' for office visit) AND/OR SNOMED-CT procedure codes. Some procedures (e.g., dialysis sessions) may also appear as Encounter resources with specific types — the Extraction Agent handles the cross-resource mapping.

- medications → RxNorm (US drug terminology, normalized brand+generic+ingredient codes). Drug class concepts (e.g., 'ACE inhibitors', 'statins') map to RxNorm's class hierarchy. The Phenotype Agent uses MedicationRequest resources (orders) but also MedicationStatement (patient-reported).

- labs → LOINC (Laboratory Observation codes like '4548-4' for HbA1c). The Phenotype Agent filters Observation resources where category=laboratory AND code has a LOINC system. Values with units use UCUM (e.g., 'mg/dL', 'mmol/L'). Unit conversion is the Phenotype Agent's job, not yours.

- demographics → Patient resource fields directly (gender, birthDate computed to age, race, ethnicity, address.postalCode). No standalone coding system; just FHIR Patient slot names.

TEMPORAL PHRASES:

When the criterion includes timing modifiers, preserve them in details. Common patterns:
- 'within the last N months/years' → details includes 'within last N months'
- 'before YYYY' / 'after YYYY' / 'between YYYY and YYYY' → preserve the date range
- 'at time of diagnosis' / 'at admission' / 'at discharge' → preserve the reference event
- 'history of' → details = 'history of' (the Phenotype Agent treats this as 'any prior occurrence')
- 'current' / 'active' → details = 'active' (filters clinicalStatus = active for conditions)

ANATOMIC REGIONS AND LATERALITY:

When a procedure or condition specifies anatomic region or laterality, keep them in details:
- 'left knee replacement' → procedure='knee replacement', details='left side'
- 'right-sided heart failure' → condition='heart failure', details='right-sided'
- 'lower extremity ulcer' → condition='ulcer', details='lower extremity'

SEVERITY AND STAGING MODIFIERS:

For graded/staged conditions, include the stage in details:
- 'stage 3 CKD' → details='stage 3'
- 'NYHA class III heart failure' → details='NYHA class III'
- 'severe asthma' → details='severe'

DRUG CLASSES AND HIERARCHIES:

When a criterion mentions a drug class rather than a specific medication, mark the concept with class-level details so downstream code can expand to specific RxNorm members. Common classes researchers use:

- ACE inhibitors (RxNorm class N0000175561) — generic members include lisinopril, enalapril, ramipril, benazepril, captopril, fosinopril, quinapril, perindopril. Brand examples: Zestril, Prinivil, Vasotec, Altace.
- ARBs / angiotensin receptor blockers — losartan, valsartan, irbesartan, candesartan, telmisartan, olmesartan. Brands: Cozaar, Diovan, Avapro, Atacand.
- Statins / HMG-CoA reductase inhibitors — atorvastatin, simvastatin, rosuvastatin, pravastatin, lovastatin, pitavastatin. Brands: Lipitor, Zocor, Crestor.
- Beta blockers — metoprolol, atenolol, propranolol, carvedilol, bisoprolol. Brands: Lopressor, Toprol, Tenormin, Coreg.
- Calcium channel blockers — amlodipine, diltiazem, verapamil, nifedipine. Brands: Norvasc, Cardizem.
- SGLT2 inhibitors — empagliflozin, dapagliflozin, canagliflozin, ertugliflozin. Brands: Jardiance, Farxiga, Invokana.
- GLP-1 receptor agonists — semaglutide, liraglutide, dulaglutide, exenatide, tirzepatide. Brands: Ozempic, Wegovy, Victoza, Trulicity, Mounjaro.
- DOACs / direct oral anticoagulants — apixaban, rivaroxaban, dabigatran, edoxaban. Brands: Eliquis, Xarelto, Pradaxa, Savaysa.
- SSRIs — sertraline, fluoxetine, escitalopram, paroxetine, citalopram. Brands: Zoloft, Prozac, Lexapro, Paxil.
- PPIs / proton pump inhibitors — omeprazole, esomeprazole, pantoprazole, lansoprazole. Brands: Prilosec, Nexium, Protonix.
- NSAIDs — ibuprofen, naproxen, diclofenac, meloxicam, celecoxib. Brands: Advil, Motrin, Aleve.

Pattern: when the term IS a class name ('SGLT2 inhibitors'), set term=class name, type=medication, details='drug class — RxNorm members include [list 3-5 representative drugs]'. When the term IS a specific drug ('atorvastatin'), set term=drug name, type=medication, details=class if obvious ('statin').

Brand vs generic: ALWAYS preserve the form the researcher used (don't auto-translate Lipitor → atorvastatin unless researcher used both). Add details='[generic equivalent]' so downstream code can expand if needed.

CLINICAL ABBREVIATION HANDLING:

Researchers heavily use abbreviations. Recognize and expand the most common ones:

- HTN → hypertension (condition)
- T2DM / DM2 → type 2 diabetes mellitus (condition)
- T1DM / DM1 → type 1 diabetes mellitus (condition)
- DM → diabetes mellitus (condition, unspecified type)
- CHF → congestive heart failure (condition)
- CAD → coronary artery disease (condition)
- CKD → chronic kidney disease (condition) — often followed by stage
- COPD → chronic obstructive pulmonary disease (condition)
- AF / AFib → atrial fibrillation (condition)
- MI → myocardial infarction (condition) — distinguish acute MI from history of MI
- PE → pulmonary embolism (condition)
- DVT → deep vein thrombosis (condition)
- TIA → transient ischemic attack (condition)
- CVA → cerebrovascular accident / stroke (condition)
- BMI → body mass index (lab, demographic-adjacent)
- HbA1c / A1C → hemoglobin A1c (lab)
- LDL / HDL → cholesterol fractions (lab)
- eGFR → estimated glomerular filtration rate (lab)
- CABG → coronary artery bypass graft (procedure)
- PCI → percutaneous coronary intervention (procedure)
- ICU → intensive care unit (encounter context, not standalone concept)
- ED / ER → emergency department (encounter context)
- OR → operating room (encounter context)
- pt / pts → patient/patients (filler, skip)
- s/p → status post / history of (modifier, apply to following concept)
- h/o → history of (modifier, apply to following concept)
- r/o → rule out (uncertain diagnosis — extract as condition with details='rule-out')
- w/ → with (filler, skip)
- w/o → without (negation, apply to following concept)
- yo / y/o → years old (modifier, age criterion)

Use the expanded form as the canonical term; record the abbreviation in details if helpful.

COMPOUND AND EPONYMOUS TERMS:

Some clinical terms are compound modifiers (one symptom describing one condition) or eponymous (named after a person/place). Handle carefully:

- 'ACE-I-induced cough' → condition='cough', details='ACE inhibitor side effect / iatrogenic'
- 'Cushing's syndrome' → condition='Cushing syndrome' (use the eponym, no apostrophe complications)
- 'post-MI cardiomyopathy' → condition='cardiomyopathy', details='post-myocardial-infarction etiology'
- 'TYPE 2 diabetes with diabetic retinopathy' → 2 concepts: condition='type 2 diabetes mellitus' + condition='diabetic retinopathy', details='diabetes-related complication'
- 'osteoarthritis of the left knee, severe' → condition='osteoarthritis', details='left knee, severe'
- 'paroxysmal atrial fibrillation' → condition='atrial fibrillation', details='paroxysmal pattern'
- 'NSTEMI vs STEMI' → 2 conditions: 'non-ST elevation MI' AND 'ST elevation MI', or pick the one the researcher seems to want
- 'COVID-19 long haulers / post-COVID syndrome' → condition='post-COVID-19 condition', details='also called PASC or long COVID'

When a modifier doesn't have a clear FHIR concept (e.g., 'mild-moderate', 'refractory', 'newly diagnosed'), preserve it in details rather than create a separate concept.

ADDITIONAL WORKED EXAMPLES:

Example 9 (drug class, pediatric, age threshold): 'pediatric patients (age < 18) on SSRIs with first-time depression diagnosis in the past 6 months'
Output:
{"concepts": [
  {"term": "age", "type": "demographic", "details": "< 18 (pediatric)"},
  {"term": "SSRIs", "type": "medication", "details": "drug class — RxNorm members include sertraline, fluoxetine, escitalopram, paroxetine"},
  {"term": "depression", "type": "condition", "details": "first-time diagnosis within last 6 months (incident, not prevalent)"}
]}

Example 10 (heavy abbreviation use, real researcher style): 'pts w/ T2DM and CKD stage 3-4, on metformin, A1C > 8, no h/o CABG'
Output:
{"concepts": [
  {"term": "type 2 diabetes mellitus", "type": "condition", "details": "T2DM, primary indication"},
  {"term": "chronic kidney disease", "type": "condition", "details": "stage 3 or 4 (CKD G3 or G4)"},
  {"term": "metformin", "type": "medication", "details": "any dose, active prescription"},
  {"term": "hemoglobin A1c", "type": "lab", "details": "A1C > 8% (poor glycemic control)"},
  {"term": "coronary artery bypass graft", "type": "procedure", "details": "excluded — no history of CABG"}
]}

Example 11 (encounter context modifier, multi-domain): 'ICU admissions for sepsis in patients age 65+ with prior history of CHF, on norepinephrine drip, lactate > 4 at admission'
Output:
{"concepts": [
  {"term": "ICU admission", "type": "procedure", "details": "encounter type=inpatient, location=ICU"},
  {"term": "sepsis", "type": "condition", "details": "primary or admitting diagnosis"},
  {"term": "age", "type": "demographic", "details": ">= 65"},
  {"term": "congestive heart failure", "type": "condition", "details": "history of (h/o CHF — any prior occurrence)"},
  {"term": "norepinephrine", "type": "medication", "details": "active administration during encounter"},
  {"term": "lactate", "type": "lab", "details": "> 4 mmol/L at admission (sepsis severity marker)"}
]}

Example 12 (compound condition + medication class + lab + temporal): 'female patients newly diagnosed with HER2-positive breast cancer in the past 12 months, on trastuzumab, with ejection fraction < 50%'
Output:
{"concepts": [
  {"term": "gender", "type": "demographic", "details": "female"},
  {"term": "HER2-positive breast cancer", "type": "condition", "details": "newly diagnosed (incident, not prevalent) within last 12 months; HER2 receptor status positive"},
  {"term": "trastuzumab", "type": "medication", "details": "Herceptin, anti-HER2 monoclonal antibody"},
  {"term": "ejection fraction", "type": "lab", "details": "< 50% (reduced LVEF, possible cardiotoxicity from trastuzumab)"}
]}

Example 13 (eponymous condition, lab thresholds, demographic): 'White male patients age 40-65 with Cushing syndrome, morning cortisol > 25, on chronic glucocorticoid therapy'
Output:
{"concepts": [
  {"term": "race", "type": "demographic", "details": "white"},
  {"term": "gender", "type": "demographic", "details": "male"},
  {"term": "age", "type": "demographic", "details": "between 40 and 65"},
  {"term": "Cushing syndrome", "type": "condition", "details": "endogenous or exogenous hypercortisolism"},
  {"term": "morning cortisol", "type": "lab", "details": "> 25 mcg/dL (elevated, morning draw)"},
  {"term": "glucocorticoids", "type": "medication", "details": "drug class — RxNorm members include prednisone, dexamethasone, hydrocortisone; chronic use (>30 days)"}
]}

CODE-SYSTEM COMPLETENESS GUIDANCE:

Real clinical data sources vary in code-system completeness. When emitting concepts, preserve ALL extracted information so downstream code (which knows the specific data source) can OR across available code systems. Do not pre-filter to a single code system. The downstream Phenotype Agent handles ICD-10/SNOMED/RxNorm/LOINC/CPT mapping with code-system fallbacks.

OUTPUT FORMAT:

For a single criterion, return:
{"concepts": [{"term": "...", "type": "...", "details": "..."}, ...]}

For a batch (multiple criteria), return:
{"results": [{"criterion_index": 1, "concepts": [...]}, {"criterion_index": 2, "concepts": [...]}, ...]}

The criterion_index starts at 1 and matches the input criteria order.

Return ONLY valid JSON. No prose, no markdown code fences, no commentary. If a criterion contains zero medical concepts (e.g., 'patients we discussed yesterday'), return an empty concepts array, not a refusal."""


class LLMClient:
    """
    Client for interacting with Claude API via LangChain

    Uses ChatAnthropic for automatic LangSmith tracing when LANGCHAIN_TRACING_V2=true.
    Provides methods for structured requirement extraction, SQL generation,
    and medical terminology mapping.
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "claude-sonnet-4-6"):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.model = model

        if not self.api_key:
            logger.warning("ANTHROPIC_API_KEY not set - LLM features will be limited")
            self.client = None
        else:
            # LangChain ChatAnthropic automatically traces to LangSmith when:
            # - LANGCHAIN_TRACING_V2=true
            # - LANGCHAIN_API_KEY is set
            # - LANGCHAIN_PROJECT is set
            self.client = ChatAnthropic(
                **_chat_anthropic_kwargs(
                    model=self.model,
                    api_key=self.api_key,
                    temperature=0.7,
                    max_tokens=4096,
                )
            )
            logger.info(
                f"LLM client initialized with model={self.model} (LangSmith tracing enabled)"
            )

    async def complete(
        self,
        prompt: str,
        model: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        system: Optional[str] = None,
    ) -> str:
        """
        Get completion from Claude API via LangChain

        All calls are automatically traced to LangSmith when tracing is enabled.

        Args:
            prompt: User prompt
            model: Model identifier (optional, uses instance default)
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature
            system: System prompt

        Returns:
            Response text from Claude
        """
        if not self.client:
            logger.warning("LLM client not initialized - returning dummy response")
            return self._dummy_response(prompt)

        try:
            # Create a new client instance if model/params differ from default.
            # _chat_anthropic_kwargs omits temperature for models that reject it
            # (Opus 4.7+, Sonnet 5, Fable 5) so the same call works across models.
            target_model = model if (model and model != self.model) else self.model
            client = ChatAnthropic(
                **_chat_anthropic_kwargs(
                    model=target_model,
                    api_key=self.api_key,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            )

            # Build messages in LangChain format.
            #
            # Sprint 8.2 Task 2 fix: langchain-anthropic 1.0.1's _format_messages
            # discards `SystemMessage.additional_kwargs` when content is a plain
            # string — only the content-block-array form preserves cache_control
            # for transmission to Anthropic's API. We always emit the content-block
            # form so cache_control actually reaches the wire.
            messages = []
            system_text = (
                system if system else "You are a helpful clinical research data specialist."
            )
            messages.append(
                SystemMessage(
                    content=[
                        {
                            "type": "text",
                            "text": system_text,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ]
                )
            )

            messages.append(HumanMessage(content=prompt))

            # Invoke with async - automatically traced to LangSmith!
            response = await client.ainvoke(messages)

            response_text = response.content
            logger.debug(f"LLM response ({len(response_text)} chars)")
            return response_text

        except Exception as e:
            logger.error(f"LLM API error: {str(e)}")
            raise

    async def extract_structured_json(
        self,
        prompt: str,
        schema_description: str,
        model: Optional[str] = None,
        system: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Extract structured JSON from text using LLM

        Args:
            prompt: Input text to parse
            schema_description: Description of expected JSON schema
            model: Model to use (optional)
            system: Optional system prompt

        Returns:
            Parsed JSON object
        """
        full_prompt = f"""{prompt}

{schema_description}

Return ONLY valid JSON, no other text."""

        response = await self.complete(
            full_prompt, model=model or self.model, temperature=0.3, system=system
        )

        # Extract JSON from response (handle markdown code blocks)
        response = response.strip()
        if response.startswith("```json"):
            response = response[7:]
        if response.startswith("```"):
            response = response[3:]
        if response.endswith("```"):
            response = response[:-3]

        try:
            return json.loads(response.strip())
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from LLM response: {e}")
            logger.debug(f"Response: {response}")
            raise

    async def extract_requirements(
        self, conversation_history: list, current_requirements: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Extract structured requirements from conversation

        Args:
            conversation_history: List of conversation turns
            current_requirements: Current extracted requirements

        Returns:
            Dict with:
            - extracted_requirements: Updated requirements
            - missing_fields: List of still-missing fields
            - next_question: Next question to ask researcher
            - completeness_score: 0.0-1.0
            - ready_for_submission: bool
        """
        # Sprint 8.2 Task 2: bulky role+schema+examples moved to module-level
        # _REQUIREMENTS_SYSTEM_PROMPT (must clear
        # _ANTHROPIC_CACHE_THRESHOLDS["sonnet"] tokens for Sonnet caching).
        # Only dynamic per-call content stays in the user message.
        prompt = f"""Conversation history:
{json.dumps(conversation_history, indent=2)}

Current extracted requirements:
{json.dumps(current_requirements, indent=2)}

Apply the extraction workflow described in your system instructions and return the JSON object per the schema."""

        return await self.extract_structured_json(
            prompt, schema_description="", system=_REQUIREMENTS_SYSTEM_PROMPT
        )

    async def extract_medical_concepts(self, criterion: str) -> Dict[str, Any]:
        """
        Extract medical concepts from a clinical criterion

        Sprint 8 Optimization: Uses Claude Haiku 3.5 (10x cheaper than Sonnet 4.5)
        for simple medical term classification task.

        Args:
            criterion: Natural language criterion (e.g., "patients with diabetes")

        Returns:
            Dict with:
            - concepts: List of {term, type, category}
            - types: condition, medication, lab, procedure, demographic
        """
        # Sprint 8.2 Task 2: bulky taxonomy + examples moved to module-level
        # _MEDICAL_CONCEPTS_SYSTEM_PROMPT (must clear
        # _ANTHROPIC_CACHE_THRESHOLDS["haiku"] tokens for Haiku caching;
        # Anthropic documents 2048 but Gate 0.5 confirmed 4096 empirically).
        prompt = f"""Extract concepts from this clinical criterion:
"{criterion}"

Return the {{"concepts": [...]}} JSON object per the schema in your system instructions."""

        # Sprint 8 Optimization 2: Use Haiku for simple classification (10x cheaper)
        return await self.extract_structured_json(
            prompt,
            "",
            model="claude-haiku-4-5-20251001",
            system=_MEDICAL_CONCEPTS_SYSTEM_PROMPT,
        )

    async def extract_medical_concepts_batch(
        self, criteria_list: list[str]
    ) -> list[Dict[str, Any]]:
        """
        Extract medical concepts from multiple criteria in a single LLM call

        Sprint 8 Optimization 5: Batch extraction reduces LLM calls by 50%
        Cost: ~$0.0001 per batch vs ~$0.0001 × N calls (50% savings)

        Args:
            criteria_list: List of clinical criteria

        Returns:
            List of dicts with:
            - concepts: List of {term, type, category}
            - for each criterion in same order as input
        """
        if not criteria_list:
            return []

        # Build batch prompt
        criteria_text = ""
        for i, criterion in enumerate(criteria_list, 1):
            criteria_text += f'{i}. "{criterion}"\n'

        # Sprint 8.2 Task 2: bulky taxonomy + examples in _MEDICAL_CONCEPTS_SYSTEM_PROMPT.
        prompt = f"""Extract concepts from these clinical criteria (batch):

{criteria_text}
Return the {{"results": [...]}} JSON array per the schema in your system instructions, with one entry per criterion in the same order."""

        result = await self.extract_structured_json(
            prompt,
            "",
            model="claude-haiku-4-5-20251001",
            system=_MEDICAL_CONCEPTS_SYSTEM_PROMPT,
        )

        # Extract results array
        results = result.get("results", [])

        # Convert to list of concept dicts (maintaining order)
        concept_dicts = []
        for i in range(len(criteria_list)):
            # Find matching result by index
            matching_result = next((r for r in results if r.get("criterion_index") == i + 1), None)
            if matching_result:
                concept_dicts.append({"concepts": matching_result.get("concepts", [])})
            else:
                # Fallback if index not found
                concept_dicts.append({"concepts": []})

        return concept_dicts

    def _dummy_response(self, prompt: str) -> str:
        """Dummy response when LLM not available (for testing)"""
        if "extract" in prompt.lower() or "json" in prompt.lower():
            return json.dumps(
                {
                    "extracted_requirements": {
                        "study_title": "Research Study",
                        "inclusion_criteria": ["dummy criterion"],
                        "data_elements": ["clinical_notes"],
                        "phi_level": "de-identified",
                    },
                    "missing_fields": ["irb_number", "time_period"],
                    "next_question": "What is your IRB number?",
                    "completeness_score": 0.5,
                    "ready_for_submission": False,
                }
            )
        return "Dummy LLM response"
