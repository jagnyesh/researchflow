"""
Delivery Agent

Packages and delivers data to researcher with documentation.
Citation and notification text come from templates; no LLM call.
"""

from typing import Dict, Any
import logging
from app.schemas._errors import log_internal_error
import json
from datetime import datetime
from langsmith import traceable
from .base_agent import BaseAgent
from ..services.file_storage import FileStorageService
from ..database import get_db_session, DataDelivery

logger = logging.getLogger(__name__)


class DeliveryAgent(BaseAgent):
    """
    Agent for final data packaging and delivery

    Responsibilities:
    - Package data with metadata
    - Generate data dictionary
    - Create documentation
    - Upload to secure location
    - Notify researcher
    - Log delivery for audit trail
    """

    def __init__(self, orchestrator=None):
        super().__init__(agent_id="delivery_agent", orchestrator=orchestrator)
        self.file_storage = FileStorageService()

    @traceable(tags=["delivery-agent", "agent-execution", "portal:formal"])
    async def execute_task(self, task: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute delivery task"""
        if task == "deliver_data":
            return await self._deliver_data(context)
        else:
            raise ValueError(f"Unknown task: {task}")

    async def _deliver_data(self, context: Dict) -> Dict[str, Any]:
        """
        Package and deliver data to researcher

        Args:
            context: Contains request_id, requirements, data_package, qa_report

        Returns:
            Dict with delivery confirmation
        """
        request_id = context.get("request_id")
        # Accept both 'requirements' and 'structured_requirements' (from orchestrator)
        requirements = context.get("requirements") or context.get("structured_requirements")
        data_package = context.get("data_package")
        qa_report = context.get("qa_report")

        logger.info(f"[{self.agent_id}] Preparing delivery for {request_id}")

        # DEFENSIVE: Validate required context
        if not data_package:
            error_msg = (
                f"Missing 'data_package' in context for {request_id}. "
                f"Available keys: {list(context.keys())}. "
                f"QA agent should provide data_package in approval_data."
            )
            logger.error(f"[{self.agent_id}] {error_msg}")
            raise ValueError(error_msg)

        if not requirements:
            error_msg = (
                f"Missing 'requirements'/'structured_requirements' in context for {request_id}. "
                f"Available keys: {list(context.keys())}. "
                f"Orchestrator should enrich context with requirements."
            )
            logger.error(f"[{self.agent_id}] {error_msg}")
            raise ValueError(error_msg)

        # Step 1: Create comprehensive data package with metadata
        final_package = {
            "data": data_package.get("formatted_data"),
            "metadata": {
                "request_id": request_id,
                "extraction_date": datetime.now().isoformat(),
                "cohort_size": len(data_package.get("cohort", [])),
                "data_elements": list(data_package.get("data_elements", {}).keys()),
                "phi_level": requirements.get("phi_level"),
                "delivery_format": requirements.get("delivery_format"),
                "qa_status": qa_report.get("overall_status"),
            },
            "documentation": {
                "data_dictionary": await self._generate_data_dictionary(data_package),
                "extraction_methods": await self._document_extraction_methods(requirements),
                "citation_info": await self._generate_citation_info(requirements),
                "qa_summary": self._summarize_qa_report(qa_report),
                # Sprint 6.5 honesty patch (2026-05-17): thread extraction
                # warnings through so the README surfaces silent-failure
                # patterns to the researcher. Without this, missing CSVs
                # ship without explanation. See #71 for the dispatch fix
                # that prevents the silent failures in the first place.
                "extraction_warnings": data_package.get("extraction_warnings", []),
            },
        }

        # Step 2: Upload to secure location
        delivery_location, csv_filenames = await self._upload_to_secure_storage(
            final_package, request_id
        )

        # Step 3: Notify researcher
        await self._send_notification(
            recipient=requirements.get("principal_investigator"),
            email=context.get("researcher_info", {}).get("email"),
            delivery_info={
                "request_id": request_id,
                "location": delivery_location,
                "cohort_size": final_package["metadata"]["cohort_size"],
                "data_elements": final_package["metadata"]["data_elements"],
            },
        )

        # Step 4: Log delivery for audit trail
        await self._log_delivery(request_id, delivery_location, final_package, csv_filenames)

        logger.info(f"[{self.agent_id}] Delivery complete: {request_id} -> {delivery_location}")

        return {
            "delivered": True,
            "delivered_at": datetime.now().isoformat(),  # Workflow expects this key
            "delivery_location": delivery_location,
            "delivery_info": final_package,  # Workflow expects "delivery_info", not "delivery_package"
            "next_agent": None,  # Workflow complete
            "next_task": None,
        }

    async def _generate_data_dictionary(self, data_package: Dict) -> Dict:
        """
        Generate data dictionary describing all fields

        Returns:
            Dict mapping data element -> field descriptions
        """
        data_dictionary = {}
        data_elements = data_package.get("data_elements", {})

        for element_name, records in data_elements.items():
            if not records:
                continue

            # Sample first record to get field names
            sample_record = records[0]

            field_descriptions = {}
            for field_name in sample_record.keys():
                field_descriptions[field_name] = {
                    "description": self._get_field_description(element_name, field_name),
                    "type": type(sample_record[field_name]).__name__,
                    "required": False,  # Could analyze to determine
                }

            data_dictionary[element_name] = {
                "description": self._get_element_description(element_name),
                "record_count": len(records),
                "fields": field_descriptions,
            }

        return data_dictionary

    def _get_field_description(self, element_name: str, field_name: str) -> str:
        """Get human-readable description for a field"""
        # Simplified descriptions - in production would use metadata catalog
        descriptions = {
            "patient_id": "Unique patient identifier",
            "birthDate": "Patient date of birth",
            "gender": "Patient gender",
            "note_date": "Date the clinical note was created",
            "note_type": "Type of clinical note",
            "note_text": "Clinical note text content",
            "code": "Standard medical code",
            "code_display": "Human-readable code description",
            "value": "Observation or measurement value",
            "unit": "Unit of measurement",
            "effectiveDateTime": "Date/time of observation",
        }
        return descriptions.get(field_name, f"{field_name} (no description available)")

    def _get_element_description(self, element_name: str) -> str:
        """Get description for data element"""
        descriptions = {
            "clinical_notes": "Clinical documentation including progress notes, discharge summaries, etc.",
            "lab_results": "Laboratory test results and measurements",
            "medications": "Medication orders and prescriptions",
            "diagnoses": "Diagnosis codes and conditions",
            "procedures": "Procedures and interventions performed",
        }
        return descriptions.get(element_name, f"{element_name} data")

    async def _document_extraction_methods(self, requirements: Dict) -> Dict:
        """Document how data was extracted"""
        return {
            "cohort_definition": {
                "inclusion_criteria": requirements.get("inclusion_criteria", []),
                "exclusion_criteria": requirements.get("exclusion_criteria", []),
                "time_period": requirements.get("time_period"),
            },
            "data_sources": ["Clinical Data Warehouse (SQL-on-FHIR)"],
            "extraction_date": datetime.now().isoformat(),
            "deidentification_method": requirements.get("phi_level"),
        }

    async def _generate_citation_info(self, requirements: Dict) -> str:
        """Generate citation information for publications"""
        return self._generate_citation_template(requirements)

    def _generate_citation_template(self, requirements: Dict) -> str:
        """Generate citation using Jinja2 template (instant, $0 cost)"""
        # Extract study info
        study_title = requirements.get("study_title", "Untitled Study")
        pi_name = requirements.get("principal_investigator", "Not specified")
        irb_number = requirements.get("irb_number", "Not specified")
        extraction_date = datetime.now().strftime("%Y-%m-%d")
        extraction_month_year = datetime.now().strftime("%B %Y")

        # Template-based citation (Sprint 8 optimization)
        citation = f"""**Data Source Acknowledgment:**
This dataset was extracted from Clinical Data Warehouse, a clinical research
database maintained by [Institution]. The extraction date was {extraction_date}.

**Study Details:**
- Title: {study_title}
- Principal Investigator: {pi_name}
- IRB Number: {irb_number}

**Citation Format:**
Clinical Data Warehouse, {extraction_month_year}. {study_title}.
Retrieved from [Institution] Clinical Data Repository.

**Disclaimer:**
This dataset was extracted for research purposes only and is intended
to provide data for the approved research protocol. The data has been
de-identified according to the specified PHI level."""

        logger.info(f"[{self.agent_id}] Generated citation using template (instant, $0)")
        return citation.strip()

    def _summarize_qa_report(self, qa_report: Dict) -> Dict:
        """Summarize QA report for researcher"""
        return {
            "status": qa_report.get("overall_status"),
            "checks_performed": len(qa_report.get("checks", [])),
            "checks_passed": len([c for c in qa_report.get("checks", []) if c.get("passed")]),
            "warnings": [
                check["message"]
                for check in qa_report.get("checks", [])
                if check.get("severity") == "warning" and not check.get("passed")
            ],
        }

    async def _upload_to_secure_storage(
        self, package: Dict, request_id: str
    ) -> tuple[str, list[str]]:
        """
        Save data package files (CSV + metadata) to local storage

        Saves:
        - CSV data files: Patient data extracted by ExtractionAgent
        - data_dictionary.txt: Field descriptions
        - qa_report.txt: Quality assurance summary
        - README.txt: Package documentation
        - extraction_metadata.json: Full metadata

        Args:
            package: Data package with documentation and data
            request_id: Research request ID

        Returns:
            Tuple of (local_storage_path, csv_filenames_list)
        """
        try:
            # STEP 1: Copy CSV files from extraction to delivery location
            import shutil
            from pathlib import Path

            formatted_data = package.get("data", {})
            csv_file_paths = formatted_data.get("file_paths", [])
            csv_filenames = []  # Track successfully copied CSV files

            if csv_file_paths:
                logger.info(
                    f"[{self.agent_id}] Copying {len(csv_file_paths)} CSV file(s) to delivery location"
                )
                for csv_path in csv_file_paths:
                    source = Path(csv_path)
                    if source.exists():
                        dest_dir = self.file_storage._get_request_directory(request_id)
                        dest = dest_dir / source.name
                        shutil.copy2(source, dest)
                        csv_filenames.append(source.name)  # Track filename
                        logger.info(f"[{self.agent_id}] ✓ Copied {source.name} to {dest}")
                    else:
                        logger.warning(
                            f"[{self.agent_id}] ⚠️ CSV file not found at {csv_path}, skipping"
                        )
            else:
                logger.warning(
                    f"[{self.agent_id}] No CSV file paths found in package data, "
                    "only metadata will be saved"
                )

            # STEP 2: Prepare metadata files
            metadata_files = {}

            # 1. Data Dictionary (human-readable)
            data_dict_content = self._format_data_dictionary_text(
                package["documentation"]["data_dictionary"]
            )
            metadata_files["data_dictionary.txt"] = data_dict_content

            # 2. QA Report (human-readable summary)
            qa_content = self._format_qa_report_text(
                package["documentation"]["qa_summary"], package["documentation"]
            )
            metadata_files["qa_report.txt"] = qa_content

            # 3. README with citation and extraction methods
            readme_content = self._format_readme_text(package["documentation"])
            metadata_files["README.txt"] = readme_content

            # 4. Full metadata as JSON
            metadata_json = json.dumps(package["metadata"], indent=2)
            metadata_files["extraction_metadata.json"] = metadata_json

            # Save all metadata files
            for filename, content in metadata_files.items():
                self.file_storage.save_text_file(request_id, filename, content)

            # Return local storage location and CSV filenames
            location = self.file_storage._get_request_directory(request_id)

            logger.info(
                f"[{self.agent_id}] Package saved to {location}: "
                f"{len(csv_filenames)} CSV file(s) + {len(metadata_files)} metadata file(s)"
            )

            return (str(location), csv_filenames)

        except Exception as e:
            log_internal_error(logger, f"[{self.agent_id}] Failed to save package metadata", e)
            # Return fallback location with empty CSV list
            return (f"/data/deliveries/{request_id}", [])

    def _format_data_dictionary_text(self, data_dict: Dict) -> str:
        """Format data dictionary as human-readable text"""
        lines = ["=" * 80, "DATA DICTIONARY", "=" * 80, ""]

        for element_name, element_info in data_dict.items():
            lines.append(f"\n{element_name.upper().replace('_', ' ')}")
            lines.append("-" * 40)
            lines.append(f"Description: {element_info.get('description', 'N/A')}")
            lines.append(f"Record Count: {element_info.get('record_count', 0)}")
            lines.append("\nFields:")

            fields = element_info.get("fields", {})
            for field_name, field_info in fields.items():
                lines.append(f"  • {field_name}")
                lines.append(f"    - Type: {field_info.get('type', 'unknown')}")
                lines.append(f"    - Description: {field_info.get('description', 'N/A')}")
                lines.append("")

        return "\n".join(lines)

    def _format_qa_report_text(self, qa_summary: Dict, documentation: Dict) -> str:
        """Format QA report as human-readable text"""
        lines = ["=" * 80, "QUALITY ASSURANCE REPORT", "=" * 80, ""]

        lines.append(f"Overall Status: {qa_summary.get('status', 'Unknown')}")
        lines.append(f"Checks Performed: {qa_summary.get('checks_performed', 0)}")
        lines.append(f"Checks Passed: {qa_summary.get('checks_passed', 0)}")
        lines.append("")

        warnings = qa_summary.get("warnings", [])
        if warnings:
            lines.append("WARNINGS:")
            for warning in warnings:
                lines.append(f"  • {warning}")
        else:
            lines.append("No warnings detected.")

        lines.append("")
        lines.extend(self._extraction_warning_lines(documentation))
        lines.append("=" * 80)

        return "\n".join(lines)

    def _format_readme_text(self, documentation: Dict) -> str:
        """Format README with citation and extraction info"""
        lines = ["=" * 80, "DATA PACKAGE README", "=" * 80, ""]

        # Citation
        lines.append("CITATION INFORMATION:")
        lines.append("-" * 40)
        lines.append(documentation.get("citation_info", "N/A"))
        lines.append("")

        # Extraction Methods
        lines.append("EXTRACTION METHODS:")
        lines.append("-" * 40)
        methods = documentation.get("extraction_methods", {})

        cohort_def = methods.get("cohort_definition", {})
        lines.append("Cohort Definition:")
        lines.append(f"  Inclusion Criteria: {cohort_def.get('inclusion_criteria', 'N/A')}")
        lines.append(f"  Exclusion Criteria: {cohort_def.get('exclusion_criteria', 'N/A')}")
        lines.append(f"  Time Period: {cohort_def.get('time_period', 'N/A')}")
        lines.append("")

        lines.append(f"Data Sources: {', '.join(methods.get('data_sources', []))}")
        lines.append(f"Extraction Date: {methods.get('extraction_date', 'N/A')}")
        lines.append(f"De-identification: {methods.get('deidentification_method', 'N/A')}")
        lines.append("")

        lines.append("FILES IN THIS PACKAGE:")
        lines.append("-" * 40)
        lines.append("  • data_dictionary.txt - Field descriptions")
        lines.append("  • qa_report.txt - Quality assurance summary")
        lines.append("  • extraction_metadata.json - Full metadata")
        lines.append("  • *.csv - Data files")
        lines.append("")

        # Sprint 6.5 honesty patch (2026-05-17): surface extraction_warnings
        # so the researcher knows when a requested data element returned no
        # records (silent failure vs genuine zero-cohort).
        lines.extend(self._extraction_warning_lines(documentation))
        lines.append("=" * 80)

        return "\n".join(lines)

    def _extraction_warning_lines(self, documentation: Dict) -> list:
        # README.txt and qa_report.txt list the same warnings (#205).
        warnings = documentation.get("extraction_warnings", []) or []
        if not warnings:
            return []
        lines = ["⚠ EXTRACTION WARNINGS:", "-" * 40]
        lines.extend(f"  • {warning}" for warning in warnings)
        lines.append("")
        return lines

    async def _send_notification(self, recipient: str, email: str, delivery_info: Dict):
        """
        Send notification email to researcher

        In production: Use MCP email server
        For now: Log the notification
        """
        email_content = self._generate_notification_template(recipient, delivery_info)

        # TODO: Implement MCP email server integration
        # email_server = self.mcp_registry.get_server('email')
        # await email_server.send_email(...)

        logger.info(f"[{self.agent_id}] Notification sent for {delivery_info['request_id']}")
        return email_content

    def _generate_notification_template(self, recipient: str, delivery_info: Dict) -> str:
        """Generate notification using template (instant, $0 cost)"""
        request_id = delivery_info.get("request_id", "Unknown")
        cohort_size = delivery_info.get("cohort_size", 0)
        data_elements = delivery_info.get("data_elements", [])
        location = delivery_info.get("location", "Unknown")

        # Template-based notification (Sprint 8 optimization)
        message = f"""Dear {recipient},

Your data request ({request_id}) is ready for download.

📊 **Request Summary:**
- Cohort Size: {cohort_size} patients
- Data Elements: {', '.join(data_elements)}
- PHI Level: {delivery_info.get('phi_level', 'Not specified')}

📁 **Download Location:**
{location}

📝 **Next Steps:**
1. Review the included data dictionary for field definitions
2. Check the QA report for data quality metrics
3. Contact us if you have any questions

Best regards,
Research Data Services
[Institution Name]"""

        logger.info(f"[{self.agent_id}] Generated notification using template (instant, $0)")
        return message.strip()

    async def _log_delivery(
        self, request_id: str, location: str, package: Dict, csv_filenames: list[str] = None
    ):
        """
        Log delivery to database for audit trail

        Saves DataDelivery record with:
        - File list (CSV files + metadata files)
        - Cohort size
        - Data elements
        - QA report
        - Data dictionary

        Args:
            request_id: Research request ID
            location: Delivery location path
            package: Data package with metadata and documentation
            csv_filenames: List of CSV filenames that were copied
        """
        try:
            # Build complete file list: CSV files + metadata files
            file_list = []

            # Add CSV files (actual data files)
            if csv_filenames:
                file_list.extend(csv_filenames)
                logger.info(f"[{self.agent_id}] Tracking {len(csv_filenames)} CSV data file(s)")

            # Add metadata files
            metadata_files = self.file_storage.list_files(request_id)
            metadata_filenames = [f["filename"] for f in metadata_files]
            file_list.extend(metadata_filenames)
            logger.info(f"[{self.agent_id}] Tracking {len(metadata_filenames)} metadata file(s)")

            async with get_db_session() as session:
                # Create DataDelivery record
                delivery = DataDelivery(
                    request_id=request_id,
                    delivery_location=location,
                    delivery_format=package["metadata"].get("delivery_format", "CSV"),
                    cohort_size=package["metadata"].get("cohort_size", 0),
                    data_elements=package["metadata"].get("data_elements", []),
                    file_list=file_list,
                    delivery_metadata=package["metadata"],
                    data_dictionary=package["documentation"].get("data_dictionary", {}),
                    qa_report=package["documentation"].get("qa_summary", {}),
                    notification_sent=True,
                )

                session.add(delivery)
                await session.commit()

                logger.info(
                    f"[{self.agent_id}] Delivery logged to database: {request_id} -> {location}"
                )
                logger.info(
                    f"[{self.agent_id}] Delivered {len(file_list)} files, "
                    f"{package['metadata']['cohort_size']} patients, "
                    f"{len(package['metadata']['data_elements'])} data elements"
                )

        except Exception as e:
            log_internal_error(logger, f"[{self.agent_id}] Failed to log delivery to database", e)
            # Don't fail the delivery if logging fails
            logger.debug(
                f"Delivered {package['metadata']['cohort_size']} patients, "
                f"{len(package['metadata']['data_elements'])} data elements"
            )
