"""
Data Extraction Agent

Executes data extraction from clinical data warehouse using multi-source orchestration.
"""

from typing import Dict, Any
import logging
from .base_agent import BaseAgent
from ..adapters.sql_on_fhir import SQLonFHIRAdapter

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
        request_id = context.get('request_id')
        requirements = context.get('requirements')
        phenotype_sql = context.get('phenotype_sql')

        logger.info(f"[{self.agent_id}] Starting extraction for {request_id}")

        # Step 1: Execute phenotype query to get patient cohort
        cohort = await self._execute_phenotype_query(phenotype_sql)

        logger.info(
            f"[{self.agent_id}] Cohort identified: {len(cohort)} patients"
        )

        # Step 2: Extract requested data elements
        extraction_results = {}
        data_elements = requirements.get('data_elements', [])

        for data_element in data_elements:
            logger.debug(f"[{self.agent_id}] Extracting {data_element}")
            try:
                element_data = await self._extract_data_element(
                    data_element=data_element,
                    patient_ids=[p['patient_id'] for p in cohort],
                    time_period=requirements.get('time_period', {})
                )
                extraction_results[data_element] = element_data
                logger.info(
                    f"[{self.agent_id}] Extracted {len(element_data)} "
                    f"{data_element} records"
                )
            except Exception as e:
                logger.error(
                    f"[{self.agent_id}] Failed to extract {data_element}: {str(e)}"
                )
                extraction_results[data_element] = []

        # Step 3: Apply de-identification if needed
        phi_level = requirements.get('phi_level', 'de-identified')
        if phi_level != 'identified':
            extraction_results = await self._deidentify_data(
                extraction_results,
                phi_level
            )

        # Step 4: Format data according to preferences
        delivery_format = requirements.get('delivery_format', 'CSV')
        formatted_data = await self._format_data(
            extraction_results,
            delivery_format
        )

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
                "delivery_format": delivery_format
            }
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
            "additional_context": {
                "data_package": data_package
            }
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
        self,
        data_element: str,
        patient_ids: list,
        time_period: Dict
    ) -> list:
        """
        Extract specific data element for patient cohort

        In production: Use MCP servers for different sources
        For now: Use SQL adapter
        """
        if not patient_ids:
            return []

        # Build patient ID list for SQL
        patient_id_list = "'" + "','".join(str(pid) for pid in patient_ids[:1000]) + "'"

        # Generate extraction query based on data element type
        if data_element == "clinical_notes":
            sql = f"""
                SELECT
                    patient_id,
                    note_id,
                    note_date,
                    note_type,
                    note_text
                FROM document_reference
                WHERE patient_id IN ({patient_id_list})
            """
        elif data_element == "lab_results":
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
                WHERE patient_id IN ({patient_id_list})
                AND category = 'laboratory'
            """
        elif data_element == "medications":
            sql = f"""
                SELECT
                    patient_id,
                    medication_id,
                    code_display,
                    authoredOn,
                    status
                FROM medication_request
                WHERE patient_id IN ({patient_id_list})
            """
        else:
            # Generic query
            sql = f"""
                SELECT *
                FROM observation
                WHERE patient_id IN ({patient_id_list})
                LIMIT 1000
            """

        # Add time period filter if specified
        if time_period.get('start') and time_period.get('end'):
            # Note: This is simplified - in production would handle different date fields
            sql += f" AND date BETWEEN '{time_period['start']}' AND '{time_period['end']}'"

        try:
            result = await self.sql_adapter.execute_sql(sql)
            return result if result else []
        except Exception as e:
            logger.warning(f"[{self.agent_id}] Extraction query failed: {str(e)}")
            return []

    async def _deidentify_data(
        self,
        data: Dict,
        phi_level: str
    ) -> Dict:
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
        if phi_level == 'de-identified':
            # Remove all PHI
            for element_name, records in data.items():
                for record in records:
                    # Remove direct identifiers
                    record.pop('patient_name', None)
                    record.pop('mrn', None)
                    record.pop('ssn', None)
                    # Mask patient_id
                    if 'patient_id' in record:
                        record['patient_id'] = f"DEIDENTIFIED_{hash(record['patient_id']) % 100000}"

        elif phi_level == 'limited_dataset':
            # Remove some PHI, keep dates
            for element_name, records in data.items():
                for record in records:
                    record.pop('patient_name', None)
                    record.pop('ssn', None)

        return data

    async def _format_data(
        self,
        data: Dict,
        format_type: str
    ) -> Dict:
        """
        Format data according to delivery preference

        Args:
            data: Extraction results dict
            format_type: CSV, FHIR, or REDCap

        Returns:
            Formatted data dict
        """
        # TODO: Implement formatters for different types
        # For now, return as-is with format metadata

        formatted = {
            "format": format_type,
            "data": data,
            "files": []
        }

        if format_type == "CSV":
            # In production: Convert to CSV files
            for element_name, records in data.items():
                formatted["files"].append({
                    "filename": f"{element_name}.csv",
                    "record_count": len(records)
                })

        elif format_type == "FHIR":
            # In production: Convert to FHIR Bundle
            formatted["files"].append({
                "filename": "fhir_bundle.json",
                "resource_type": "Bundle"
            })

        elif format_type == "REDCap":
            # In production: Format for REDCap import
            formatted["files"].append({
                "filename": "redcap_import.csv",
                "record_count": sum(len(records) for records in data.values())
            })

        return formatted

    def _get_timestamp(self) -> str:
        """Get current timestamp as ISO string"""
        from datetime import datetime
        return datetime.now().isoformat()
