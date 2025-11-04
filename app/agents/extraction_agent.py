"""
Data Extraction Agent

Executes data extraction from clinical data warehouse using multi-source orchestration.
"""

from typing import Dict, Any
import logging
import pandas as pd
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

    async def execute_task(self, task: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute data extraction task"""
        if task == "extract_data":
            return await self._extract_data(context)
        else:
            raise ValueError(f"Unknown task: {task}")

    async def _extract_data(self, context: Dict) -> Dict[str, Any]:
        """
        Execute data extraction across multiple sources

        Args:
            context: Contains request_id, requirements, phenotype_sql

        Returns:
            Dict with extraction results and next routing
        """
        request_id = context.get("request_id")
        requirements = context.get("requirements")
        phenotype_sql = context.get("phenotype_sql")

        logger.info(f"[{self.agent_id}] Starting extraction for {request_id}")

        # Step 1: Execute phenotype query to get patient cohort
        cohort = await self._execute_phenotype_query(phenotype_sql)

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
            "metadata": {
                "request_id": request_id,
                "extraction_date": self._get_timestamp(),
                "cohort_size": len(cohort),
                "data_elements_extracted": list(extraction_results.keys()),
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

    async def _execute_phenotype_query(self, phenotype_sql: str) -> list:
        """
        Execute phenotype SQL to get patient cohort

        Returns:
            List of patient dicts with id, birthDate, etc.
        """
        try:
            result = await self.sql_adapter.execute_sql(phenotype_sql)
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
        if data_element == "clinical_notes":
            # nosec B608 - SQL structure is safe, all values parameterized
            sql = f"""
                SELECT
                    patient_id,
                    note_id,
                    note_date,
                    note_type,
                    note_text
                FROM document_reference
                WHERE patient_id IN ({patient_id_placeholders})
            """
        elif data_element == "lab_results":
            # nosec B608 - SQL structure is safe, all values parameterized
            sql = f"""
                SELECT
                    patient_id,
                    observation_id,
                    code,
                    code_display,
                    value,
                    unit,
                    effectiveDateTime
                FROM observation
                WHERE patient_id IN ({patient_id_placeholders})
                AND category = 'laboratory'
            """
        elif data_element == "medications":
            # nosec B608 - SQL structure is safe, all values parameterized
            sql = f"""
                SELECT
                    patient_id,
                    medication_id,
                    code_display,
                    authoredOn,
                    status
                FROM medication_request
                WHERE patient_id IN ({patient_id_placeholders})
            """
        else:
            # Generic query
            # nosec B608 - SQL structure is safe, all values parameterized
            sql = f"""
                SELECT *
                FROM observation
                WHERE patient_id IN ({patient_id_placeholders})
                LIMIT 1000
            """

        # Add time period filter if specified (parameterized)
        if time_period.get("start") and time_period.get("end"):
            # Note: This is simplified - in production would handle different date fields
            sql += " AND date BETWEEN :date_start AND :date_end"
            params["date_start"] = time_period["start"]
            params["date_end"] = time_period["end"]

        try:
            result = await self.sql_adapter.execute_sql(sql, params)
            return result if result else []
        except Exception as e:
            logger.warning(f"[{self.agent_id}] Extraction query failed: {str(e)}")
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
                # Create individual CSVs for each data element
                for element_name, records in data.items():
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
