"""
Data Extraction Agent

Executes data extraction from clinical data warehouse using multi-source orchestration.
"""

from typing import Dict, Any
import logging
import pandas as pd
from langsmith import traceable
from .base_agent import BaseAgent
from ..adapters.sql_on_fhir import SQLonFHIRAdapter
from ..services.file_storage import FileStorageService

logger = logging.getLogger(__name__)


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
                logger.error(f"[{self.agent_id}] Failed to extract {data_element}: {str(e)}")
                extraction_results[data_element] = []

        # Sprint 6.5 honesty patch (2026-05-17, REQ-20260517-A097C5F6): surface
        # silent-failure pattern as warnings instead of shipping incomplete
        # deliveries with status=success. extraction_agent's per-element
        # _extract_data_element catches SQL failures internally and returns []
        # (e.g., the `FROM observation` catch-all queries a non-existent table).
        # Without this hook, a missing Procedures.csv looks indistinguishable
        # from a genuine zero-cohort. The dispatch fix (procedures + lab_results
        # + clinical_notes proper queries) is #71's scope; this hook just makes
        # the silent failures visible to the researcher in the meantime.
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
                logger.error(f"[{self.agent_id}] Failed to extract {data_element}: {str(e)}")
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
        for feasibility_service's same shape problem. Stays direct in
        Sprint 6.5; picks up in Sprint 6.5b alongside feasibility_service.
        """
        try:
            result = await self.sql_adapter.execute_sql(phenotype_sql, parameters)
            return result if result else []
        except Exception as e:
            logger.error(f"[{self.agent_id}] Phenotype query failed: {str(e)}")
            return []

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

        # Build parameterized IN clause with individual placeholders
        # SQLAlchemy uses :param_name format for named parameters
        patient_id_params = {f"pid_{i}": str(pid) for i, pid in enumerate(limited_patient_ids)}
        patient_id_placeholders = ", ".join(
            f":{param_name}" for param_name in patient_id_params.keys()
        )

        # Initialize query parameters dict
        params = patient_id_params.copy()

        # Generate extraction query based on data element type
        # Note: f-strings used only for structure, all data in params dict

        # Handle demographic data elements from patient_demographics materialized view
        # Bug fix: Case-insensitive matching for data elements
        data_element_lower = data_element.lower()
        if data_element_lower in [
            "family name",
            "given name",
            "date of birth",
            "address",
            "demographics (age, gender, race)",
        ]:
            # Extract demographics from patient_demographics materialized view
            # nosec B608 - SQL structure is safe, all values parameterized

            # Field mapping for available columns
            # NOTE: patient_demographics has: patient_id, gender, birth_date, given_name, family_name
            # It does NOT have: race, address (not in FHIR synthetic data)
            field_mapping = {
                "family name": "family_name",
                "given name": "given_name",
                "date of birth": "birth_date",
                "address": None,  # Not available in patient_demographics
            }

            # Build SELECT clause based on requested demographic field
            if data_element_lower == "demographics (age, gender, race)":
                # Select all available demographic fields (race not available)
                select_fields = "patient_id, family_name, given_name, gender, birth_date"
            elif data_element_lower == "address":
                # Address not available in patient_demographics - return empty
                logger.warning(
                    f"[{self.agent_id}] Address data not available in patient_demographics table"
                )
                return []
            else:
                db_field = field_mapping.get(data_element_lower)
                if db_field is None:
                    logger.warning(
                        f"[{self.agent_id}] Data element '{data_element}' not available in patient_demographics"
                    )
                    return []
                select_fields = f"patient_id, {db_field}"

            # nosec B608 - SQL structure is safe, all values parameterized
            # Sprint 6.5b cleanup (2026-05-18, #79): this query is LIVE and works
            # today against the Sprint 6.2 patient_demographics MV. Future
            # HybridRunner wiring follows #71's `execute_sql_with_view_hints`
            # API extension when a driving requirement activates that issue.
            sql = f"""
                SELECT {select_fields}
                FROM sqlonfhir.patient_demographics
                WHERE patient_id IN ({patient_id_placeholders})
            """

            try:
                result = await self.sql_adapter.execute_sql(sql, params)
                return result if result else []
            except Exception as e:
                logger.warning(f"[{self.agent_id}] Demographic extraction failed: {str(e)}")
                return []

        # Sprint 6.5b cleanup (2026-05-18, #79): non-demographic data elements
        # (clinical_notes, lab_results, medications, procedures, etc.) have no
        # dispatch implementation yet. Sprint 6.5's `extraction_warnings`
        # honesty patch in `_extract_data` surfaces the empty result to the
        # researcher. Proper dispatch (wiring to sqlonfhir.observation_labs,
        # sqlonfhir.medication_requests, sqlonfhir.condition_diagnoses,
        # sqlonfhir.procedure_history) is #71's scope.
        logger.warning(
            f"[{self.agent_id}] Data element '{data_element}' has no extraction "
            f"dispatch. Only demographic data elements are currently supported; "
            f"others require #71's dispatch fix."
        )
        return []

    async def _extract_data_element_preview(
        self, data_element: str, patient_ids: list, time_period: Dict, limit: int = 10
    ) -> list:
        """
        Extract preview (limited rows) for a specific data element

        Similar to _extract_data_element but with LIMIT clause for preview

        Args:
            data_element: Data element type (clinical_notes, lab_results, etc.)
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

        # Build parameterized IN clause
        patient_id_params = {f"pid_{i}": str(pid) for i, pid in enumerate(limited_patient_ids)}
        patient_id_placeholders = ", ".join(
            f":{param_name}" for param_name in patient_id_params.keys()
        )

        # Initialize query parameters dict
        params = patient_id_params.copy()
        params["preview_limit"] = limit  # Add limit parameter

        # Generate extraction query based on data element type
        # Note: f-strings used only for structure, all data in params dict
        data_element_lower = data_element.lower()

        if data_element_lower not in [
            "family name",
            "given name",
            "date of birth",
            "address",
            "demographics (age, gender, race)",
        ]:
            # Sprint 6.5b cleanup (2026-05-18, #79): non-demographic data
            # elements have no preview extraction dispatch. Sprint 6.5's
            # `extraction_warnings` honesty patch in `_extract_preview`
            # surfaces the empty result to the QA reviewer. Proper dispatch
            # (lab_results, medications, clinical_notes, procedures) is #71's
            # scope and arrives when that issue's design pass activates.
            logger.warning(
                f"[{self.agent_id}] Data element '{data_element}' has no preview "
                f"extraction dispatch. Only demographic data elements are currently "
                f"supported; others require #71's dispatch fix."
            )
            return []

        # Demographics-only dispatch. The patient_demographics MV has:
        # patient_id, gender, birth_date, given_name, family_name.
        # It does NOT have: race, address (not in FHIR synthetic data).
        field_mapping = {
            "family name": "family_name",
            "given name": "given_name",
            "date of birth": "birth_date",
            "address": None,  # Not available in patient_demographics
        }

        if data_element_lower == "demographics (age, gender, race)":
            # Select all available demographic fields (race not available)
            select_fields = "patient_id, family_name, given_name, gender, birth_date"
        elif data_element_lower == "address":
            logger.warning(
                f"[{self.agent_id}] Address data not available in patient_demographics table"
            )
            return []
        else:
            db_field = field_mapping.get(data_element_lower)
            if db_field is None:
                logger.warning(
                    f"[{self.agent_id}] Data element '{data_element}' not available in patient_demographics"
                )
                return []
            select_fields = f"patient_id, {db_field}"

        # nosec B608 - SQL structure is safe, all values parameterized
        sql = f"""
            SELECT {select_fields}
            FROM sqlonfhir.patient_demographics
            WHERE patient_id IN ({patient_id_placeholders})
            LIMIT :preview_limit
        """

        # Add time period filter if specified (parameterized)
        # Note: LIMIT must come AFTER WHERE but we already have LIMIT above
        # So we need to insert time filter before LIMIT
        if time_period.get("start") and time_period.get("end"):
            sql = sql.replace(
                "LIMIT :preview_limit",
                "AND date BETWEEN :date_start AND :date_end LIMIT :preview_limit",
            )
            params["date_start"] = time_period["start"]
            params["date_end"] = time_period["end"]

        try:
            result = await self.sql_adapter.execute_sql(sql, params)
            return result if result else []
        except Exception as e:
            logger.warning(f"[{self.agent_id}] Preview extraction query failed: {str(e)}")
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

        # Simplified de-identification: remove/mask sensitive fields
        if phi_level == "de-identified":
            # Remove all PHI
            for element_name, records in data.items():
                for record in records:
                    # Remove direct identifiers
                    record.pop("patient_name", None)
                    record.pop("mrn", None)
                    record.pop("ssn", None)
                    # Mask patient_id
                    if "patient_id" in record:
                        record["patient_id"] = f"DEIDENTIFIED_{hash(record['patient_id']) % 100000}"

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
                                                patient_record["birth_date"] = value
                                            elif key in [
                                                "gender",
                                                "birth_date",
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
                logger.error(f"[{self.agent_id}] CSV generation failed: {str(e)}")
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
