"""
Data Context Provider

Provides contextual information about available data sources, ViewDefinitions,
and FHIR resources to support conversational AI responses.

Used by conversational agents to answer informational questions like:
- "What data do you have?"
- "What conditions can I query?"
- "Do you have medication data?"

Without needing to execute SQL queries.
"""

import logging
from typing import Dict, List, Any
from pathlib import Path

logger = logging.getLogger(__name__)


class DataContextProvider:
    """
    Provides contextual information about available FHIR data
    for conversational AI agents.
    """

    def __init__(self):
        """Initialize data context with available ViewDefinitions and resources"""
        self.available_view_definitions = {
            "patient_demographics": {
                "title": "Patient Demographics",
                "description": "Core demographic information including name, contact, birth date, gender, address",
                "data_elements": [
                    "Patient ID",
                    "Name (first, last, full)",
                    "Birth date",
                    "Gender",
                    "Contact (phone, email)",
                    "Address (street, city, state, postal code, country)",
                    "Active/deceased status"
                ],
                "resource_type": "Patient"
            },
            "condition_diagnoses": {
                "title": "Patient Conditions and Diagnoses",
                "description": "Patient conditions, diagnoses, and problems with clinical status and coding",
                "data_elements": [
                    "Condition ID",
                    "Patient ID",
                    "Clinical status (active, resolved, etc.)",
                    "ICD-10-CM diagnosis codes",
                    "SNOMED CT codes",
                    "Condition description",
                    "Onset date/age",
                    "Resolution date",
                    "Severity (mild, moderate, severe)",
                    "Recording date",
                    "Associated encounter"
                ],
                "resource_type": "Condition",
                "common_examples": [
                    "Diabetes (Type 1, Type 2)",
                    "Hypertension",
                    "Heart failure",
                    "COPD",
                    "Cancer diagnoses"
                ]
            },
            "medication_requests": {
                "title": "Medication Requests",
                "description": "Patient medication orders and prescriptions",
                "data_elements": [
                    "Medication ID",
                    "Patient ID",
                    "Medication name",
                    "RxNorm codes",
                    "Dosage and instructions",
                    "Prescription date",
                    "Status (active, completed, stopped)",
                    "Prescriber information",
                    "Refills"
                ],
                "resource_type": "MedicationRequest",
                "common_examples": [
                    "Metformin (diabetes)",
                    "Lisinopril (blood pressure)",
                    "Atorvastatin (cholesterol)",
                    "Insulin",
                    "Antibiotics"
                ]
            },
            "observation_labs": {
                "title": "Laboratory Results and Observations",
                "description": "Lab test results, vital signs, and clinical observations",
                "data_elements": [
                    "Observation ID",
                    "Patient ID",
                    "Test/observation name",
                    "LOINC codes",
                    "Result value and units",
                    "Reference ranges",
                    "Test date",
                    "Status (final, preliminary)",
                    "Interpretation (normal, abnormal)"
                ],
                "resource_type": "Observation",
                "common_examples": [
                    "HbA1c (diabetes control)",
                    "Blood pressure",
                    "Cholesterol panels",
                    "Creatinine (kidney function)",
                    "Complete blood count (CBC)",
                    "Glucose levels"
                ]
            },
            "procedure_history": {
                "title": "Procedure History",
                "description": "Medical procedures and interventions performed on patients",
                "data_elements": [
                    "Procedure ID",
                    "Patient ID",
                    "Procedure name",
                    "CPT/SNOMED codes",
                    "Procedure date",
                    "Status (completed, in-progress)",
                    "Performer information",
                    "Associated encounter",
                    "Body site",
                    "Outcome"
                ],
                "resource_type": "Procedure",
                "common_examples": [
                    "Surgeries",
                    "Diagnostic procedures",
                    "Therapeutic procedures",
                    "Dialysis",
                    "Imaging studies"
                ]
            }
        }

        logger.info(f"Initialized DataContextProvider with {len(self.available_view_definitions)} ViewDefinitions")

    def get_available_data_summary(self) -> str:
        """
        Get human-readable summary of available data

        Returns:
            Formatted string describing available data types
        """
        summary_parts = [
            "I have access to the following types of patient data:",
            ""
        ]

        for view_name, view_info in self.available_view_definitions.items():
            summary_parts.append(f"**{view_info['title']}** ({view_info['resource_type']})")
            summary_parts.append(f"- {view_info['description']}")

            # Add examples if available
            if "common_examples" in view_info:
                examples = ", ".join(view_info['common_examples'][:3])
                summary_parts.append(f"- Examples: {examples}")

            summary_parts.append("")

        summary_parts.extend([
            "**Key Capabilities:**",
            "- Query by medical conditions (ICD-10, SNOMED)",
            "- Filter by medications (RxNorm)",
            "- Analyze lab results (LOINC)",
            "- Track procedures (CPT, SNOMED)",
            "- Demographics and vital statistics",
            ""
        ])

        return "\n".join(summary_parts)

    def get_detailed_context_for_llm(self) -> str:
        """
        Get detailed context for LLM prompts

        Returns:
            Comprehensive data context for LLM system prompts
        """
        context_parts = [
            "=== AVAILABLE DATA CONTEXT ===",
            "",
            "You have access to the following FHIR data resources:",
            ""
        ]

        for view_name, view_info in self.available_view_definitions.items():
            context_parts.append(f"## {view_info['title']}")
            context_parts.append(f"Resource Type: {view_info['resource_type']}")
            context_parts.append(f"Description: {view_info['description']}")
            context_parts.append("")
            context_parts.append("Data Elements:")
            for element in view_info['data_elements']:
                context_parts.append(f"  - {element}")

            if "common_examples" in view_info:
                context_parts.append("")
                context_parts.append("Common Examples:")
                for example in view_info['common_examples']:
                    context_parts.append(f"  - {example}")

            context_parts.append("")
            context_parts.append("---")
            context_parts.append("")

        context_parts.extend([
            "## Coding Standards Supported:",
            "- ICD-10-CM: Diagnosis codes",
            "- SNOMED CT: Clinical terms",
            "- LOINC: Laboratory observations",
            "- RxNorm: Medications",
            "- CPT: Procedures",
            "",
            "## Query Capabilities:",
            "- Filter by demographics (age, gender, etc.)",
            "- Filter by conditions (with date ranges)",
            "- Filter by medications (active, historical)",
            "- Filter by lab results (with value ranges)",
            "- Filter by procedures (with dates)",
            "- Calculate cohort sizes (feasibility)",
            "- Extract full data sets (with appropriate approvals)",
            ""
        ])

        return "\n".join(context_parts)

    def get_data_elements_list(self) -> List[str]:
        """
        Get flat list of all available data elements

        Returns:
            List of data element names
        """
        elements = []
        for view_info in self.available_view_definitions.values():
            elements.extend(view_info['data_elements'])
        return elements

    def get_resource_types(self) -> List[str]:
        """
        Get list of available FHIR resource types

        Returns:
            List of resource type names
        """
        return [view_info['resource_type'] for view_info in self.available_view_definitions.values()]

    def can_query_condition(self, condition_name: str) -> bool:
        """
        Check if a specific condition can be queried

        Args:
            condition_name: Name of the condition (e.g., "diabetes", "hypertension")

        Returns:
            True if condition can be queried
        """
        # All conditions can be queried via condition_diagnoses ViewDefinition
        return "condition_diagnoses" in self.available_view_definitions

    def can_query_medication(self, medication_name: str) -> bool:
        """
        Check if medications can be queried

        Args:
            medication_name: Name of medication

        Returns:
            True if medications can be queried
        """
        return "medication_requests" in self.available_view_definitions

    def can_query_lab(self, lab_name: str) -> bool:
        """
        Check if lab results can be queried

        Args:
            lab_name: Name of lab test

        Returns:
            True if labs can be queried
        """
        return "observation_labs" in self.available_view_definitions

    def get_view_definition_info(self, view_name: str) -> Dict[str, Any]:
        """
        Get information about a specific ViewDefinition

        Args:
            view_name: Name of the ViewDefinition

        Returns:
            ViewDefinition metadata and capabilities

        Raises:
            KeyError: If ViewDefinition not found
        """
        if view_name not in self.available_view_definitions:
            raise KeyError(f"ViewDefinition '{view_name}' not found. Available: {list(self.available_view_definitions.keys())}")

        return self.available_view_definitions[view_name]

    def answer_capability_question(self, question: str) -> str:
        """
        Answer common questions about data capabilities

        Args:
            question: User's question (lowercase)

        Returns:
            Human-readable answer
        """
        question_lower = question.lower()

        # Condition/diagnosis questions
        if any(keyword in question_lower for keyword in ["condition", "diagnosis", "disease", "diabetes", "hypertension"]):
            return (
                "Yes, I have access to patient conditions and diagnoses. "
                "This includes ICD-10-CM and SNOMED CT coded diagnoses, clinical status, "
                "onset dates, severity, and resolution information. "
                "Examples: diabetes, hypertension, heart failure, COPD, cancer."
            )

        # Medication questions
        if any(keyword in question_lower for keyword in ["medication", "drug", "prescription", "metformin"]):
            return (
                "Yes, I have access to patient medication data. "
                "This includes medication requests/prescriptions, RxNorm codes, dosages, "
                "prescription dates, status (active/completed), and prescriber information. "
                "Examples: metformin, lisinopril, insulin, atorvastatin."
            )

        # Lab/observation questions
        if any(keyword in question_lower for keyword in ["lab", "test", "observation", "hba1c", "glucose", "cholesterol"]):
            return (
                "Yes, I have access to laboratory results and clinical observations. "
                "This includes lab test results, vital signs, LOINC codes, values with units, "
                "reference ranges, and interpretation (normal/abnormal). "
                "Examples: HbA1c, blood pressure, cholesterol panels, creatinine, CBC."
            )

        # Procedure questions
        if any(keyword in question_lower for keyword in ["procedure", "surgery", "operation", "dialysis"]):
            return (
                "Yes, I have access to patient procedure history. "
                "This includes surgical and diagnostic procedures, CPT/SNOMED codes, "
                "procedure dates, performers, and outcomes. "
                "Examples: surgeries, diagnostic procedures, dialysis, imaging studies."
            )

        # Demographics questions
        if any(keyword in question_lower for keyword in ["demographic", "age", "gender", "address", "contact"]):
            return (
                "Yes, I have access to patient demographics. "
                "This includes name, birth date, gender, contact information (phone, email), "
                "address, and active/deceased status."
            )

        # General "what data" questions
        if any(keyword in question_lower for keyword in ["what data", "what kind", "what type", "available"]):
            return self.get_available_data_summary()

        # Default response
        return (
            "I have access to comprehensive patient data including: "
            "demographics, conditions/diagnoses, medications, lab results, and procedures. "
            "Would you like more details about any of these data types?"
        )
