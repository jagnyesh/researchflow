"""
Data Extraction Agent

Executes data extraction from clinical data warehouse using multi-source orchestration.
"""

from datetime import date, timedelta
from typing import Dict, Any, Optional
import hashlib
import hmac
import logging
import numbers
import os
import re
from app.schemas._errors import log_internal_error
import pandas as pd
from langsmith import traceable
from .base_agent import BaseAgent
from ..adapters.sql_on_fhir import SQLonFHIRAdapter
from ..services.file_storage import FileStorageService
from .qa_agent import (
    DIRECT_IDENTIFIER_COLUMNS,
    DEIDENTIFIED_ID_COLUMNS,
    DEIDENTIFIED_PASSTHROUGH_COLUMNS,
    DEIDENTIFIED_YEAR_COLUMNS,
)

DEIDENTIFICATION_KEY_ENV = "DEIDENTIFICATION_HMAC_KEY"
_MIN_KEY_LENGTH = 32
_MIN_KEY_DISTINCT_CHARS = 10
_TIME = r"(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?"
# A whole value that is a full date, as the views emit them.
_FULL_DATE = re.compile(r"(\d{4})-\d{2}-\d{2}" + _TIME)
# A date column may hold FHIR partial dates (YYYY, YYYY-MM), full dates or YYYYMMDD.
_DATE_COLUMN_VALUE = re.compile(r"(\d{4})(?:-\d{2}(?:-\d{2}" + _TIME + r")?|\d{4})?")

logger = logging.getLogger(__name__)

# Data elements dispatch on a canonical ID, never on the display string: the
# requirements LLM rewrites form labels ("Demographics (age, gender, race)" →
# "Demographics"), and an exact-label match silently extracted nothing (#205).
# id -> (sqlonfhir view, selected columns, date expression for a time-period filter)
DATA_ELEMENT_SOURCES = {
    "demographics": (
        "patient_demographics",
        "patient_id, family_name, given_name, gender, birth_date",
        None,
    ),
    "diagnoses": (
        "condition_diagnoses",
        "patient_id, condition_id, clinical_status, icd10_code, icd10_display, "
        "snomed_code, snomed_display, code_text, onset_datetime, recorded_date",
        "onset_datetime",
    ),
    "procedures": (
        "procedure_history",
        "patient_id, procedure_id, status, cpt_code, cpt_display, snomed_code, "
        "snomed_display, code_text, performed_datetime, performed_period_start",
        # Synthea records procedures as performedPeriod; performed_datetime is
        # almost always NULL, so filtering on it alone returned nothing.
        "COALESCE(performed_datetime, performed_period_start)",
    ),
    "lab_results": (
        "observation_labs",
        "patient_id, observation_id, status, code, code_display, code_text, "
        "value_quantity, value_unit, value_string, effective_datetime",
        "effective_datetime",
    ),
    # Single demographic fields the requirements agent may ask for.
    "family_name": ("patient_demographics", "patient_id, family_name", None),
    "given_name": ("patient_demographics", "patient_id, given_name", None),
    "birth_date": ("patient_demographics", "patient_id, birth_date", None),
}

_DATA_ELEMENT_ALIASES = {
    "demographics": "demographics",
    "demographic": "demographics",
    "demographic data": "demographics",
    "patient demographics": "demographics",
    "age": "demographics",
    "gender": "demographics",
    "diagnoses": "diagnoses",
    "diagnosis": "diagnoses",
    "conditions": "diagnoses",
    "conditions diagnoses": "diagnoses",
    "diagnoses conditions": "diagnoses",
    "condition": "diagnoses",
    "procedures": "procedures",
    "lab results": "lab_results",
    "labs": "lab_results",
    "lab": "lab_results",
    "laboratory results": "lab_results",
    "family name": "family_name",
    "given name": "given_name",
    "date of birth": "birth_date",
}

# The formal portal offers only elements that dispatch. Medications are left
# out until medication_requests has populated codes (#111); vitals, notes,
# imaging and encounters have no sqlonfhir view.
FORM_DATA_ELEMENTS = [
    "Demographics (age, gender, race)",
    "Diagnoses (ICD codes)",
    "Procedures (CPT/HCPCS codes)",
    "Lab Results (LOINC codes)",
]


def canonical_data_element(name: str) -> Optional[str]:
    """Map a form label or an LLM-normalized name to a DATA_ELEMENT_SOURCES id."""
    key = re.sub(r"\(.*?\)", "", name).lower()
    key = re.sub(r"[^a-z]+", " ", key).strip()
    return _DATA_ELEMENT_ALIASES.get(key)


def _deidentification_key() -> bytes:
    # Checked at the call site, not at startup, so the API, the Streamlit
    # portals and scripts all fail the same way. No default: a guessable key
    # lets anyone re-derive pseudonyms from sequential FHIR ids.
    key = os.getenv(DEIDENTIFICATION_KEY_ENV, "").strip()
    if len(key) < _MIN_KEY_LENGTH or len(set(key)) < _MIN_KEY_DISTINCT_CHARS:
        message = (
            f"{DEIDENTIFICATION_KEY_ENV} must be a random secret of at least "
            f"{_MIN_KEY_LENGTH} characters to deliver a de-identified extract. "
            "Generate one with: python -c 'import secrets; print(secrets.token_hex(32))'"
        )
        # The workflow's PHI-safe failure log drops exception text; say it here.
        logger.error(message)
        raise RuntimeError(message)
    return key.encode()


def _pseudonym(key: bytes, column: str, value) -> str:
    digest = hmac.new(key, f"{column}:{value}".encode(), hashlib.sha256).hexdigest()
    return f"DEID-{digest[:32]}"


def _date_column_year(column: str, value) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, date):
        return value.year
    match = _DATE_COLUMN_VALUE.fullmatch(value.strip()) if isinstance(value, str) else None
    if match:
        return int(match.group(1))
    # Dropping the value is safe; say so, since the researcher loses it.
    logger.warning(f"De-identification dropped an unparseable {column} value")
    return None


def _passthrough_value(value):
    if isinstance(value, date):
        return value.year
    if isinstance(value, str):
        match = _FULL_DATE.fullmatch(value.strip())
        return int(match.group(1)) if match else value
    if value is None or (isinstance(value, numbers.Number) and not isinstance(value, bool)):
        return value
    return None


def _deidentify_record(record: Dict, key: bytes, dropped: set) -> Dict:
    """HIPAA Safe Harbor floor (#306), as an allowlist: dates become the year,
    ids become keyed pseudonyms, listed clinical columns pass, the rest is dropped."""
    out = {}
    for column, value in record.items():
        if column in DEIDENTIFIED_YEAR_COLUMNS:
            out[DEIDENTIFIED_YEAR_COLUMNS[column]] = _date_column_year(column, value)
        elif column in DEIDENTIFIED_ID_COLUMNS:
            out[column] = None if value is None else _pseudonym(key, column, value)
        elif column in DEIDENTIFIED_PASSTHROUGH_COLUMNS:
            out[column] = _passthrough_value(value)
        elif column not in DIRECT_IDENTIFIER_COLUMNS:
            dropped.add(column)
    return out


class DataExtractionAgent(BaseAgent):
    """
    Agent for executing data extraction across multiple sources

    Responsibilities:
    - Create extraction plan for multi-source data
    - Execute phenotype query to get patient cohort
    - Extract requested data elements for cohort
    - Apply de-identification if needed
    - Format data according to preferences
    - Route to QA agent when complete
    """

    def __init__(self, orchestrator=None, database_url: str = None):
        super().__init__(agent_id="extraction_agent", orchestrator=orchestrator)
        self.sql_adapter = SQLonFHIRAdapter(database_url)
        self.file_storage = FileStorageService()

    @traceable(tags=["extraction-agent", "agent-execution", "portal:formal"])
    async def execute_task(self, task: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute data extraction task"""
        if task == "extract_data":
            return await self._extract_data(context)
        elif task == "extract_preview":
            return await self._extract_preview(context)
        else:
            raise ValueError(f"Unknown task: {task}")

    async def _extract_data(self, context: Dict) -> Dict[str, Any]:
        """
        Execute data extraction across multiple sources

        Args:
            context: Contains request_id, structured_requirements, sql_query, parameters

        Returns:
            Dict with extraction results and next routing
        """
        request_id = context.get("request_id")

        # Get requirements from approval context
        # Note: approval_data has 'structured_requirements' not 'requirements'
        requirements = context.get("structured_requirements") or context.get("requirements")

        # Get SQL query and parameters from approval context
        # Note: approval_data has 'sql_query' not 'phenotype_sql'
        sql_query = context.get("sql_query") or context.get("phenotype_sql")
        parameters = context.get("parameters", {})

        # DEFENSIVE CHECKS: Validate required context is present
        if not requirements:
            error_msg = (
                f"Missing 'structured_requirements' in context for {request_id}. "
                f"Available context keys: {list(context.keys())}. "
                f"This indicates the orchestrator did not properly enrich the context."
            )
            logger.error(f"[{self.agent_id}] {error_msg}")
            raise ValueError(error_msg)

        if not sql_query:
            error_msg = (
                f"Missing 'sql_query'/'phenotype_sql' in context for {request_id}. "
                f"Available context keys: {list(context.keys())}. "
                f"This indicates the orchestrator did not properly enrich the context."
            )
            logger.error(f"[{self.agent_id}] {error_msg}")
            raise ValueError(error_msg)

        logger.info(f"[{self.agent_id}] Starting extraction for {request_id}")

        # Step 1: Execute phenotype query to get patient cohort
        cohort = await self._execute_phenotype_query(sql_query, parameters)

        logger.info(f"[{self.agent_id}] Cohort identified: {len(cohort)} patients")

        # Step 2: Extract requested data elements
        extraction_results = {}
        data_elements = requirements.get("data_elements", [])

        for data_element in data_elements:
            logger.debug(f"[{self.agent_id}] Extracting {data_element}")
            try:
                element_data = await self._extract_data_element(
                    data_element=data_element,
                    patient_ids=[p["patient_id"] for p in cohort],
                    time_period=requirements.get("time_period", {}),
                )
                extraction_results[data_element] = element_data
                logger.info(
                    f"[{self.agent_id}] Extracted {len(element_data)} " f"{data_element} records"
                )
            except Exception as e:
                log_internal_error(logger, f"[{self.agent_id}] Failed to extract {data_element}", e)
                extraction_results[data_element] = []

        # Sprint 6.5 honesty patch (2026-05-17, REQ-20260517-A097C5F6): surface
        # silent-failure pattern as warnings instead of shipping incomplete
        # deliveries with status=success. Sprint 6.5b cleanup (#79) deleted
        # the dead `FROM observation` catch-all that originally motivated this
        # patch; non-demographic data elements now take an early-return path
        # with their own warning, so this loop's empty-list detection covers
        # both legitimate-zero-cohort AND no-dispatch-implementation cases.
        # The proper dispatch fix (procedures + lab_results + clinical_notes
        # wired to real sqlonfhir MVs) remains #71's scope; until then this
        # researcher-facing warning is the only signal a data element was
        # requested but not extracted.
        extraction_warnings = [
            (
                f"No records extracted for '{el}'. Either the cohort genuinely has "
                f"zero records for this data element, OR the extraction query "
                f"failed silently (see logs for SQL errors). Compare against the "
                f"requested cohort to determine which case applies."
            )
            for el, recs in extraction_results.items()
            if not recs
        ]
        if extraction_warnings:
            logger.warning(
                f"[{self.agent_id}] Extraction completed with {len(extraction_warnings)} "
                f"empty-result warning(s); delivery_agent will surface to researcher."
            )

        # Step 3: Apply de-identification if needed
        phi_level = requirements.get("phi_level", "de-identified")
        if phi_level != "identified":
            extraction_results = await self._deidentify_data(extraction_results, phi_level)

        # Step 4: Format data according to preferences (generate CSV files)
        delivery_format = requirements.get("delivery_format", "CSV")
        formatted_data = await self._format_data(extraction_results, delivery_format, request_id)

        # Step 5: Package data with metadata
        data_package = {
            "cohort": cohort,
            "data_elements": extraction_results,
            "formatted_data": formatted_data,
            "extraction_warnings": extraction_warnings,
            "metadata": {
                "request_id": request_id,
                "extraction_date": self._get_timestamp(),
                "cohort_size": len(cohort),
                "data_elements_extracted": list(extraction_results.keys()),
                "data_elements_empty": [el for el, recs in extraction_results.items() if not recs],
                "phi_level": phi_level,
                "delivery_format": delivery_format,
            },
        }

        logger.info(
            f"[{self.agent_id}] Extraction complete: {len(cohort)} patients, "
            f"{len(extraction_results)} data elements"
        )

        return {
            "extraction_complete": True,
            "data_package": data_package,
            "next_agent": "qa_agent",
            "next_task": "validate_extracted_data",
            "additional_context": {"data_package": data_package},
        }

    async def _extract_preview(self, context: Dict) -> Dict[str, Any]:
        """
        Extract preview data (10 rows per data element) for validation

        This is a lightweight extraction to validate SQL and data structure
        before committing to full extraction.

        Args:
            context: Contains request_id, structured_requirements, sql_query, parameters

        Returns:
            Dict with preview data and routing to QA agent
        """
        request_id = context.get("request_id")

        # Get requirements from approval context
        # Note: approval_data has 'structured_requirements' not 'requirements'
        requirements = context.get("structured_requirements") or context.get("requirements")

        # Get SQL query and parameters from approval context
        # Note: approval_data has 'sql_query' not 'phenotype_sql'
        sql_query = context.get("sql_query") or context.get("phenotype_sql")
        parameters = context.get("parameters", {})

        # DEFENSIVE CHECKS: Validate required context is present
        if not requirements:
            error_msg = (
                f"Missing 'structured_requirements' in context for {request_id}. "
                f"Available context keys: {list(context.keys())}. "
                f"This indicates the orchestrator did not properly enrich the context."
            )
            logger.error(f"[{self.agent_id}] {error_msg}")
            raise ValueError(error_msg)

        if not sql_query:
            error_msg = (
                f"Missing 'sql_query'/'phenotype_sql' in context for {request_id}. "
                f"Available context keys: {list(context.keys())}. "
                f"This indicates the orchestrator did not properly enrich the context."
            )
            logger.error(f"[{self.agent_id}] {error_msg}")
            raise ValueError(error_msg)

        logger.info(
            f"[{self.agent_id}] Starting PREVIEW extraction for {request_id}"
            f"\n  SQL Query: {sql_query[:150]}..."
            f"\n  Parameters: {parameters}"
            f"\n  Parameter count: {len(parameters) if parameters else 0}"
            f"\n  Has parameters: {bool(parameters)}"
        )

        # Step 1: Execute phenotype query to get patient cohort
        cohort = await self._execute_phenotype_query(sql_query, parameters)

        logger.info(
            f"[{self.agent_id}] Cohort identified: {len(cohort)} patients"
            f"\n  SQL: {sql_query[:100]}..."
            f"\n  Parameters used: {parameters}"
            f"\n  Result count: {len(cohort)}"
        )

        # Step 2: Extract PREVIEW (first 10 rows) for each data element
        preview_results = {}
        data_elements = requirements.get("data_elements", [])

        for data_element in data_elements:
            logger.debug(f"[{self.agent_id}] Extracting PREVIEW for {data_element}")
            try:
                # Extract with limit=10
                element_data = await self._extract_data_element_preview(
                    data_element=data_element,
                    patient_ids=[p["patient_id"] for p in cohort],
                    time_period=requirements.get("time_period", {}),
                    limit=10,  # Preview: only 10 rows
                )
                preview_results[data_element] = element_data
                logger.info(
                    f"[{self.agent_id}] Extracted {len(element_data)} preview rows for {data_element}"
                )
            except Exception as e:
                log_internal_error(logger, f"[{self.agent_id}] Failed to extract {data_element}", e)
                preview_results[data_element] = []

        # Step 3: NO de-identification for preview (informatician needs to see real data)
        # Preview is internal review only, not for delivery

        # Step 4: Create preview data package
        preview_package = {
            "cohort": cohort[:10],  # Also limit cohort to 10 for preview
            "preview_data": preview_results,
            "metadata": {
                "request_id": request_id,
                "extraction_date": self._get_timestamp(),
                "cohort_size": len(cohort),
                "data_elements_extracted": list(preview_results.keys()),
                "is_preview": True,
                "preview_rows_per_element": 10,
            },
        }

        logger.info(
            f"[{self.agent_id}] Preview extraction complete: {len(cohort)} patients total, "
            f"{len(preview_results)} data elements (10 rows each)"
        )

        return {
            "preview_extracted": True,
            "preview_package": preview_package,
            "next_agent": "qa_agent",
            "next_task": "validate_preview",
            "additional_context": {"preview_package": preview_package},
        }

    async def _execute_phenotype_query(self, phenotype_sql: str, parameters: dict = None) -> list:
        """
        Execute phenotype SQL to get patient cohort

        Args:
            phenotype_sql: Parameterized SQL query
            parameters: SQL parameters for binding (e.g., {"gender_1": "male"})

        Returns:
            List of patient dicts with id, birthDate, etc.

        Sprint 6.5 Phase 2B-2 audit (2026-05-17) — DEFERRED to #71.
        phenotype_sql is the multi-view JOIN built by SQLGenerator
        (patient_demographics + condition_simple). HybridRunner's merge
        logic at hybrid_runner.py:347-400 only row-merges ONE view at a
        time; wiring requires execute_sql_with_view_hints designed in #71
        for feasibility_service's same shape problem. Stays direct until
        #71 activates with the HybridRunner API extension. Sprint 6.5b
        (#79) was cleanup-only; this site is not dead code, just waiting
        for the API extension.
        """
        try:
            result = await self.sql_adapter.execute_sql(phenotype_sql, parameters)
            return result if result else []
        except Exception as e:
            log_internal_error(logger, f"[{self.agent_id}] Phenotype query failed", e)
            return []

    def _element_query(
        self, data_element: str, n_patients: int, time_period: Dict, limit: Optional[int]
    ):
        """SQL and extra params for one data element, or None if it doesn't dispatch.

        Patient IDs bind as :pid_0..:pid_{n-1}; every value is a bound parameter.
        """
        element = canonical_data_element(data_element)
        if element is None:
            logger.warning(
                f"[{self.agent_id}] Data element '{data_element}' has no extraction dispatch"
            )
            return None
        view, columns, date_column = DATA_ELEMENT_SOURCES[element]
        placeholders = ", ".join(f":pid_{i}" for i in range(n_patients))
        params = {}

        # nosec B608 - view/columns come from DATA_ELEMENT_SOURCES; values are bound
        sql = f"SELECT {columns} FROM sqlonfhir.{view} WHERE patient_id IN ({placeholders})"
        if date_column and time_period.get("start") and time_period.get("end"):
            # The date columns are ISO-8601 text with a time; a half-open range
            # keeps the whole end day ('2024-12-31T10:00' > '2024-12-31').
            sql += f" AND {date_column} >= :date_start AND {date_column} < :date_end_exclusive"
            params.update(
                date_start=str(time_period["start"])[:10],
                date_end_exclusive=(
                    date.fromisoformat(str(time_period["end"])[:10]) + timedelta(days=1)
                ).isoformat(),
            )
        if limit is not None:
            sql += " LIMIT :preview_limit"
            params["preview_limit"] = limit
        return sql, params

    async def _extract_data_element(
        self, data_element: str, patient_ids: list, time_period: Dict
    ) -> list:
        """
        Extract specific data element for patient cohort

        In production: Use MCP servers for different sources
        For now: Use SQL adapter
        """
        if not patient_ids:
            return []

        # Limit to 1000 patient IDs for performance
        limited_patient_ids = patient_ids[:1000]
        query = self._element_query(data_element, len(limited_patient_ids), time_period, None)
        if query is None:
            return []
        sql, params = query
        params.update({f"pid_{i}": str(pid) for i, pid in enumerate(limited_patient_ids)})

        try:
            result = await self.sql_adapter.execute_sql(sql, params)
            return result if result else []
        except Exception as e:
            log_internal_error(
                logger,
                f"[{self.agent_id}] Extraction of '{data_element}' failed",
                e,
                level=logging.WARNING,
            )
            return []

    async def _extract_data_element_preview(
        self, data_element: str, patient_ids: list, time_period: Dict, limit: int = 10
    ) -> list:
        """
        Extract preview (limited rows) for a specific data element

        Same dispatch as _extract_data_element, with a row limit.

        Args:
            data_element: Data element name (form label or normalized name)
            patient_ids: List of patient IDs
            time_period: Time period filter dict
            limit: Number of rows to extract (default 10)

        Returns:
            List of records (limited to 'limit' rows)
        """
        if not patient_ids:
            return []

        # Limit to 100 patient IDs for preview (even more restrictive)
        limited_patient_ids = patient_ids[:100]
        query = self._element_query(data_element, len(limited_patient_ids), time_period, limit)
        if query is None:
            return []
        sql, params = query
        params.update({f"pid_{i}": str(pid) for i, pid in enumerate(limited_patient_ids)})

        try:
            result = await self.sql_adapter.execute_sql(sql, params)
            return result if result else []
        except Exception as e:
            log_internal_error(
                logger,
                f"[{self.agent_id}] Preview extraction query failed",
                e,
                level=logging.WARNING,
            )
            return []

    async def _deidentify_data(self, data: Dict, phi_level: str) -> Dict:
        """
        Apply de-identification transformations

        In production: Use MCP de-identification server
        For now: Basic field removal
        """
        # TODO: Implement proper de-identification using MCP server
        # deidentification_server = self.mcp_registry.get_server('deidentification')
        # return await deidentification_server.deidentify(data, phi_level)

        logger.info(f"[{self.agent_id}] Applying {phi_level} de-identification")

        if phi_level == "de-identified":
            key = _deidentification_key()
            dropped = set()
            for element_name, records in data.items():
                data[element_name] = [_deidentify_record(r, key, dropped) for r in records]
            if dropped:
                logger.warning(
                    f"[{self.agent_id}] De-identification dropped unclassified columns: "
                    f"{sorted(dropped)}"
                )

        elif phi_level == "limited_dataset":
            # Remove some PHI, keep dates
            for element_name, records in data.items():
                for record in records:
                    record.pop("patient_name", None)
                    record.pop("ssn", None)

        return data

    async def _format_data(self, data: Dict, format_type: str, request_id: str = None) -> Dict:
        """
        Format data according to delivery preference and generate actual files

        Args:
            data: Extraction results dict
            format_type: CSV, FHIR, or REDCap
            request_id: Research request ID for file storage

        Returns:
            Formatted data dict with file_paths
        """
        formatted = {"format": format_type, "data": data, "files": [], "file_paths": []}

        if format_type == "CSV" and request_id:
            # Generate actual CSV files
            logger.info(f"[{self.agent_id}] Generating CSV files for request {request_id}")

            try:
                # Define demographic data elements that should be consolidated
                # Bug fix: Use lowercase keys for case-insensitive matching
                demographic_elements = {
                    "family name": "family_name",
                    "given name": "given_name",
                    "date of birth": "birth_date",
                    "demographics (age, gender, race)": "demographics_full",
                }

                # Separate demographic and non-demographic data
                demographic_data = {}
                non_demographic_data = {}

                for element_name, records in data.items():
                    # Bug fix: Case-insensitive comparison
                    if element_name.lower() in demographic_elements:
                        demographic_data[element_name] = records
                    else:
                        non_demographic_data[element_name] = records

                # If we have demographic data, consolidate into single Demographics.csv
                if demographic_data:
                    logger.info(
                        f"[{self.agent_id}] Consolidating demographic data elements into Demographics.csv"
                    )

                    # Build consolidated demographic DataFrame
                    consolidated_records = []
                    patient_ids = set()

                    # Collect all unique patient IDs from all demographic data elements
                    for records in demographic_data.values():
                        for record in records:
                            if "patient_id" in record:
                                patient_ids.add(record["patient_id"])

                    # For each patient, merge data from all demographic elements
                    for patient_id in patient_ids:
                        patient_record = {"patient_id": patient_id}

                        for element_name, records in demographic_data.items():
                            # Find this patient's record in this data element
                            for record in records:
                                if record.get("patient_id") == patient_id:
                                    # Add all fields from this record except patient_id
                                    for key, value in record.items():
                                        if key != "patient_id":
                                            # Use friendly column names (case-insensitive comparison)
                                            element_name_lower = element_name.lower()
                                            if element_name_lower == "family name":
                                                patient_record["family_name"] = value
                                            elif element_name_lower == "given name":
                                                patient_record["given_name"] = value
                                            elif element_name_lower == "date of birth":
                                                # birth_year after de-identification (#306)
                                                patient_record[key] = value
                                            elif key in [
                                                "gender",
                                                "birth_date",
                                                "birth_year",
                                                "family_name",
                                                "given_name",
                                            ]:
                                                # For Demographics (age, gender, race) element
                                                patient_record[key] = value
                                    break

                        consolidated_records.append(patient_record)

                    if consolidated_records:
                        # Create consolidated Demographics.csv
                        demographics_df = pd.DataFrame(consolidated_records)

                        # Ensure consistent column order
                        desired_columns = [
                            "patient_id",
                            "family_name",
                            "given_name",
                            "gender",
                            "birth_date",
                            "birth_year",
                        ]
                        actual_columns = [
                            col for col in desired_columns if col in demographics_df.columns
                        ]
                        other_columns = [
                            col for col in demographics_df.columns if col not in desired_columns
                        ]
                        demographics_df = demographics_df[actual_columns + other_columns]

                        filename = "Demographics.csv"
                        file_path = self.file_storage.save_csv(
                            request_id=request_id, filename=filename, dataframe=demographics_df
                        )

                        formatted["files"].append(
                            {
                                "filename": filename,
                                "record_count": len(consolidated_records),
                                "column_count": len(demographics_df.columns),
                            }
                        )
                        formatted["file_paths"].append(file_path)

                        logger.info(
                            f"[{self.agent_id}] Generated consolidated {filename}: "
                            f"{len(consolidated_records)} rows, {len(demographics_df.columns)} columns"
                        )

                # Create individual CSVs for non-demographic data elements
                for element_name, records in non_demographic_data.items():
                    if not records:
                        logger.warning(f"[{self.agent_id}] No records for {element_name}, skipping")
                        continue

                    # Convert to DataFrame
                    df = pd.DataFrame(records)

                    # Save CSV
                    filename = f"{element_name}.csv"
                    file_path = self.file_storage.save_csv(
                        request_id=request_id, filename=filename, dataframe=df
                    )

                    formatted["files"].append(
                        {
                            "filename": filename,
                            "record_count": len(records),
                            "column_count": len(df.columns),
                        }
                    )
                    formatted["file_paths"].append(file_path)

                    logger.info(
                        f"[{self.agent_id}] Generated {filename}: "
                        f"{len(records)} rows, {len(df.columns)} columns"
                    )

                # Create combined master CSV with all data
                all_records = []
                for element_name, records in data.items():
                    # Add data_element column to identify source
                    for record in records:
                        record_copy = record.copy()
                        record_copy["data_element"] = element_name
                        all_records.append(record_copy)

                if all_records:
                    master_df = pd.DataFrame(all_records)
                    master_filename = "all_data_combined.csv"
                    master_path = self.file_storage.save_csv(
                        request_id=request_id, filename=master_filename, dataframe=master_df
                    )
                    formatted["files"].append(
                        {
                            "filename": master_filename,
                            "record_count": len(all_records),
                            "column_count": len(master_df.columns),
                        }
                    )
                    formatted["file_paths"].append(master_path)

                logger.info(
                    f"[{self.agent_id}] CSV generation complete: "
                    f"{len(formatted['files'])} files created"
                )

            except Exception as e:
                log_internal_error(logger, f"[{self.agent_id}] CSV generation failed", e)
                # Return metadata even if file generation fails
                for element_name, records in data.items():
                    formatted["files"].append(
                        {"filename": f"{element_name}.csv", "record_count": len(records)}
                    )

        elif format_type == "FHIR":
            # TODO: In production, convert to FHIR Bundle
            formatted["files"].append({"filename": "fhir_bundle.json", "resource_type": "Bundle"})
            logger.warning(f"[{self.agent_id}] FHIR format not yet implemented")

        elif format_type == "REDCap":
            # TODO: In production, format for REDCap import
            formatted["files"].append(
                {
                    "filename": "redcap_import.csv",
                    "record_count": sum(len(records) for records in data.values()),
                }
            )
            logger.warning(f"[{self.agent_id}] REDCap format not yet implemented")

        else:
            # Default: just return metadata
            for element_name, records in data.items():
                formatted["files"].append(
                    {"filename": f"{element_name}.csv", "record_count": len(records)}
                )

        return formatted

    def _get_timestamp(self) -> str:
        """Get current timestamp as ISO string"""
        from datetime import datetime

        return datetime.now().isoformat()
