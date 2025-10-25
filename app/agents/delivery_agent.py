"""
Delivery Agent

Packages and delivers data to researcher with documentation.
Uses MultiLLMClient for generating personalized notifications and documentation.
"""

from typing import Dict, Any
import logging
from datetime import datetime
from .base_agent import BaseAgent
from ..utils.multi_llm_client import MultiLLMClient

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
        self.llm_client = MultiLLMClient()  # Use multi-provider client for non-critical tasks

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
        request_id = context.get('request_id')
        requirements = context.get('requirements')
        data_package = context.get('data_package')
        qa_report = context.get('qa_report')

        logger.info(f"[{self.agent_id}] Preparing delivery for {request_id}")

        # Step 1: Create comprehensive data package with metadata
        final_package = {
            "data": data_package.get('formatted_data'),
            "metadata": {
                "request_id": request_id,
                "extraction_date": datetime.now().isoformat(),
                "cohort_size": len(data_package.get('cohort', [])),
                "data_elements": list(data_package.get('data_elements', {}).keys()),
                "phi_level": requirements.get('phi_level'),
                "delivery_format": requirements.get('delivery_format'),
                "qa_status": qa_report.get('overall_status')
            },
            "documentation": {
                "data_dictionary": await self._generate_data_dictionary(data_package),
                "extraction_methods": await self._document_extraction_methods(requirements),
                "citation_info": await self._generate_citation_info(requirements),
                "qa_summary": self._summarize_qa_report(qa_report)
            }
        }

        # Step 2: Upload to secure location
        delivery_location = await self._upload_to_secure_storage(
            final_package,
            request_id
        )

        # Step 3: Notify researcher
        await self._send_notification(
            recipient=requirements.get('principal_investigator'),
            email=context.get('researcher_info', {}).get('email'),
            delivery_info={
                "request_id": request_id,
                "location": delivery_location,
                "cohort_size": final_package['metadata']['cohort_size'],
                "data_elements": final_package['metadata']['data_elements']
            }
        )

        # Step 4: Log delivery for audit trail
        await self._log_delivery(request_id, delivery_location, final_package)

        logger.info(
            f"[{self.agent_id}] Delivery complete: {request_id} -> {delivery_location}"
        )

        return {
            "delivered": True,
            "delivery_location": delivery_location,
            "delivery_package": final_package,
            "next_agent": None,  # Workflow complete
            "next_task": None
        }

    async def _generate_data_dictionary(self, data_package: Dict) -> Dict:
        """
        Generate data dictionary describing all fields

        Returns:
            Dict mapping data element -> field descriptions
        """
        data_dictionary = {}
        data_elements = data_package.get('data_elements', {})

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
                    "required": False  # Could analyze to determine
                }

            data_dictionary[element_name] = {
                "description": self._get_element_description(element_name),
                "record_count": len(records),
                "fields": field_descriptions
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
            "effectiveDateTime": "Date/time of observation"
        }
        return descriptions.get(field_name, f"{field_name} (no description available)")

    def _get_element_description(self, element_name: str) -> str:
        """Get description for data element"""
        descriptions = {
            "clinical_notes": "Clinical documentation including progress notes, discharge summaries, etc.",
            "lab_results": "Laboratory test results and measurements",
            "medications": "Medication orders and prescriptions",
            "diagnoses": "Diagnosis codes and conditions",
            "procedures": "Procedures and interventions performed"
        }
        return descriptions.get(element_name, f"{element_name} data")

    async def _document_extraction_methods(self, requirements: Dict) -> Dict:
        """Document how data was extracted"""
        return {
            "cohort_definition": {
                "inclusion_criteria": requirements.get('inclusion_criteria', []),
                "exclusion_criteria": requirements.get('exclusion_criteria', []),
                "time_period": requirements.get('time_period')
            },
            "data_sources": [
                "Clinical Data Warehouse (SQL-on-FHIR)"
            ],
            "extraction_date": datetime.now().isoformat(),
            "deidentification_method": requirements.get('phi_level')
        }

    async def _generate_citation_info(self, requirements: Dict) -> str:
        """
        Generate citation information for publications

        Uses LLM to create professional citation text.
        This is a non-critical task that uses the secondary provider.
        """
        prompt = f"""Generate professional citation information for a clinical research data extract.

Study Information:
- Title: {requirements.get('study_title', 'Untitled Study')}
- Principal Investigator: {requirements.get('principal_investigator', 'Unknown')}
- IRB Number: {requirements.get('irb_number', 'Unknown')}
- Extraction Date: {datetime.now().strftime('%Y-%m-%d')}

Create a professional citation block that includes:
1. Data source acknowledgment
2. Study details
3. Proper citation format
4. Any necessary disclaimers

Keep it concise and professional."""

        system_prompt = "You are a research librarian creating citation information for clinical data extracts."

        try:
            # Use secondary provider for this non-critical task
            citation = await self.llm_client.complete(
                prompt=prompt,
                task_type="delivery",  # Non-critical task
                temperature=0.5,
                system=system_prompt
            )
            return citation.strip()
        except Exception as e:
            logger.warning(f"[{self.agent_id}] Failed to generate LLM citation: {str(e)}, using template")
            # Fallback to template
            citation = f"""
Data extracted from Clinical Data Warehouse on {datetime.now().strftime('%Y-%m-%d')}
for research study: {requirements.get('study_title', 'Untitled Study')}
Principal Investigator: {requirements.get('principal_investigator', 'Unknown')}
IRB Protocol: {requirements.get('irb_number', 'Unknown')}

Please cite as:
[Institution] Clinical Data Warehouse. Data extracted {datetime.now().strftime('%B %Y')}.
"""
            return citation.strip()

    def _summarize_qa_report(self, qa_report: Dict) -> Dict:
        """Summarize QA report for researcher"""
        return {
            "status": qa_report.get('overall_status'),
            "checks_performed": len(qa_report.get('checks', [])),
            "checks_passed": len([c for c in qa_report.get('checks', []) if c.get('passed')]),
            "warnings": [
                check['message']
                for check in qa_report.get('checks', [])
                if check.get('severity') == 'warning' and not check.get('passed')
            ]
        }

    async def _upload_to_secure_storage(
        self,
        package: Dict,
        request_id: str
    ) -> str:
        """
        Upload data package to secure storage

        In production: Upload to S3, Azure Blob, or secure file share
        For now: Return simulated location
        """
        # TODO: Implement actual file upload
        # storage_client = self._get_storage_client()
        # location = await storage_client.upload(package, request_id)

        # Simulated location
        location = f"s3://research-data-bucket/{request_id}/data_package.zip"

        logger.info(f"[{self.agent_id}] Package uploaded to {location}")

        return location

    async def _send_notification(
        self,
        recipient: str,
        email: str,
        delivery_info: Dict
    ):
        """
        Send notification email to researcher

        Uses LLM to generate personalized notification email.
        This is a non-critical task that uses the secondary provider.

        In production: Use MCP email server
        For now: Log the notification
        """
        # Generate personalized notification message
        prompt = f"""Generate a professional email notification to a researcher that their data request is ready.

Recipient: {recipient}
Request ID: {delivery_info['request_id']}
Cohort Size: {delivery_info['cohort_size']} patients
Data Elements: {', '.join(delivery_info['data_elements'])}
Download Location: {delivery_info['location']}

The email should:
1. Be professional and friendly
2. Inform them their data is ready
3. Provide key statistics
4. Include download location
5. Remind them to review the data dictionary and QA report
6. Include appropriate sign-off

Keep it concise and professional."""

        system_prompt = "You are a clinical research data coordinator sending delivery notifications to researchers."

        try:
            # Use secondary provider for this non-critical task
            message = await self.llm_client.complete(
                prompt=prompt,
                task_type="delivery",  # Non-critical task
                temperature=0.7,
                system=system_prompt
            )
        except Exception as e:
            logger.warning(f"[{self.agent_id}] Failed to generate LLM notification: {str(e)}, using template")
            # Fallback to template
            message = f"""
Dear {recipient},

Your data request ({delivery_info['request_id']}) is ready for download.

Cohort Size: {delivery_info['cohort_size']} patients
Data Elements: {', '.join(delivery_info['data_elements'])}

Download Location: {delivery_info['location']}

Please review the included data dictionary and QA report.

Best regards,
Research Data Services
"""

        # TODO: Implement MCP email server integration
        # email_server = self.mcp_registry.get_server('email')
        # await email_server.send_email(...)

        logger.info(
            f"[{self.agent_id}] Notification sent to {email}: "
            f"{delivery_info['request_id']}"
        )
        logger.debug(f"Email content:\n{message}")

    async def _log_delivery(
        self,
        request_id: str,
        location: str,
        package: Dict
    ):
        """Log delivery for audit trail"""
        # TODO: Implement database logging using DataDelivery model
        logger.info(
            f"[{self.agent_id}] Delivery logged: {request_id} -> {location}"
        )
        logger.debug(
            f"Delivered {package['metadata']['cohort_size']} patients, "
            f"{len(package['metadata']['data_elements'])} data elements"
        )
