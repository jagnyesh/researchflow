"""
Query Interpreter Service

Translates natural language queries to SQL-on-FHIR ViewDefinition executions
using Claude API for intelligent query parsing and mapping.
"""

import logging
import json
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass

from ..utils.llm_client import LLMClient

logger = logging.getLogger(__name__)


@dataclass
class QueryIntent:
    """Parsed query intent"""
    query_type: str  # "count", "list", "filter", "aggregate"
    resources: List[str]  # ["Patient", "Condition", "Observation"]
    filters: Dict[str, Any]  # Extracted filters
    view_definitions: List[str]  # ViewDefinitions to use
    search_params: Dict[str, Any]  # FHIR search parameters
    post_filters: List[Dict]  # Additional filtering after results
    aggregations: List[str]  # Summary stats to calculate
    explanation: str  # Human-readable query explanation


class QueryInterpreter:
    """
    Interprets natural language queries and translates to SQL-on-FHIR executions

    Examples:
        "give me all male patients under the age of 30 with type 2 diabetes"
        → ViewDefs: patient_demographics + condition_diagnoses
        → Filters: gender=male, age<30, condition=T2D

        "how many patients are available?"
        → ViewDef: patient_demographics
        → Type: count
    """

    # Available ViewDefinitions and their resource types
    AVAILABLE_VIEW_DEFINITIONS = {
        "patient_demographics": {
            "resource": "Patient",
            "description": "Core patient demographics (gender, birth date, name, contact)",
            "columns": ["id", "gender", "birth_date", "family_name", "given_name", "full_name",
                       "phone", "email", "address", "city", "state", "postal_code"]
        },
        "observation_labs": {
            "resource": "Observation",
            "description": "Laboratory test results with LOINC codes, values, units",
            "columns": ["patient_id", "code", "code_display", "value_quantity", "value_unit",
                       "effective_datetime", "interpretation", "ref_range_low", "ref_range_high"]
        },
        "condition_simple": {
            "resource": "Condition",
            "description": "Patient conditions with ICD-10 and SNOMED codes (materialized view with dual columns)",
            "columns": ["id", "patient_ref", "patient_id", "icd10_code", "icd10_display",
                       "snomed_code", "snomed_display", "code_text", "clinical_status"]
        },
        "medication_requests": {
            "resource": "MedicationRequest",
            "description": "Medication orders and prescriptions with RxNorm codes",
            "columns": ["patient_id", "status", "medication_code", "medication_display",
                       "dosage_text", "authored_on"]
        },
        "procedure_history": {
            "resource": "Procedure",
            "description": "Patient procedures with CPT and SNOMED codes",
            "columns": ["patient_id", "status", "cpt_code", "cpt_display", "snomed_code",
                       "snomed_display", "performed_datetime"]
        }
    }

    # Common medical condition mappings
    CONDITION_MAPPINGS = {
        "type 2 diabetes": {"snomed": "44054006", "icd10": "E11.9", "icd10_pattern": "E11%", "name": "Type 2 diabetes mellitus"},
        "diabetes": {"snomed": "73211009", "icd10": "E11.9", "icd10_pattern": "E1%", "name": "Diabetes mellitus (all types)"},
        "hypertension": {"snomed": "38341003", "icd10": "I10", "icd10_pattern": "I10%", "name": "Hypertension"},
        "high blood pressure": {"snomed": "38341003", "icd10": "I10", "icd10_pattern": "I10%", "name": "Hypertension"},
        "hyperlipidemia": {"snomed": "13645005", "icd10": "E78.5", "icd10_pattern": "E78%", "name": "Hyperlipidemia"},
        "asthma": {"snomed": "195967001", "icd10": "J45.909", "icd10_pattern": "J45%", "name": "Asthma"},
    }

    def __init__(self):
        self.llm_client = LLMClient()

    async def interpret_query(self, natural_language_query: str) -> QueryIntent:
        """
        Interpret natural language query and return structured intent

        Args:
            natural_language_query: User's question in natural language

        Returns:
            QueryIntent with parsed information
        """
        logger.info(f"Interpreting query: {natural_language_query}")

        # Build prompt for Claude
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(natural_language_query)

        try:
            # Get structured response from Claude
            response = await self.llm_client.extract_structured_json(
                prompt=user_prompt,
                schema_description="""
                {
                    "query_type": "count | list | filter | aggregate",
                    "resources": ["Patient", "Condition", etc],
                    "filters": {
                        "gender": "male|female",
                        "age_min": number,
                        "age_max": number,
                        "conditions": [{"name": str, "snomed": str, "icd10": str}],
                        "date_range": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}
                    },
                    "view_definitions": ["patient_demographics", etc],
                    "explanation": "Human-readable explanation of what the query will do"
                }
                """,
                system=system_prompt
            )

            # Response is already a Dict from extract_structured_json()
            query_data = response

            # Build QueryIntent
            intent = self._build_query_intent(query_data, natural_language_query)

            logger.info(f"Query interpreted: {intent.explanation}")
            return intent

        except Exception as e:
            logger.error(f"Error interpreting query: {e}")
            # Fall back to simple parsing
            return self._fallback_interpretation(natural_language_query)

    def _build_system_prompt(self) -> str:
        """Build system prompt for Claude"""
        view_defs_desc = "\n".join([
            f"- {name}: {info['description']}"
            for name, info in self.AVAILABLE_VIEW_DEFINITIONS.items()
        ])

        return f"""You are a clinical research data query interpreter. Your job is to translate natural language queries about patient data into structured SQL-on-FHIR ViewDefinition executions.

Available ViewDefinitions:
{view_defs_desc}

Common Conditions:
{json.dumps(self.CONDITION_MAPPINGS, indent=2)}

Guidelines:
1. Identify which ViewDefinitions are needed
2. Extract demographic filters (gender, age range)
3. Map medical terms to standard codes (SNOMED, ICD-10)
4. Determine if it's a count, list, filter, or aggregate query
5. Calculate age from birthdate (current year - birth year)
6. For "under age X", use birthdate > (current_year - X)
7. Be precise and use exact medical terminology"""

    def _build_user_prompt(self, query: str) -> str:
        """Build user prompt"""
        current_year = datetime.now().year
        return f"""Parse this clinical research query and return structured JSON:

Query: "{query}"

Current year: {current_year}

Return JSON with:
- query_type: count/list/filter/aggregate
- resources: which FHIR resources needed
- filters: all extracted filters
- view_definitions: which ViewDefinitions to execute
- explanation: what the query will do

Focus on:
1. Demographics (gender, age)
2. Conditions/diagnoses
3. Time periods
4. Data elements requested"""

    def _build_query_intent(self, query_data: Dict, original_query: str) -> QueryIntent:
        """Build QueryIntent from parsed data"""
        filters = query_data.get("filters", {})

        # Build FHIR search parameters
        search_params = {}

        # Gender filter
        if "gender" in filters:
            search_params["gender"] = filters["gender"]

        # Age range to birthdate filter
        if "age_min" in filters or "age_max" in filters:
            current_year = datetime.now().year
            # Use separate parameters for min and max to avoid overwriting
            if "age_max" in filters:
                # age < X means birthdate > (current_year - X)
                min_birth_year = current_year - filters["age_max"]
                search_params["birthdate_min"] = f"ge{min_birth_year}-01-01"
            if "age_min" in filters:
                # age > X means birthdate < (current_year - X)
                max_birth_year = current_year - filters["age_min"]
                search_params["birthdate_max"] = f"le{max_birth_year}-12-31"

        # Post-filters for conditions (applied after results)
        post_filters = []
        if "conditions" in filters:
            for condition in filters["conditions"]:
                post_filters.append({
                    "field": "snomed_code",
                    "value": condition.get("snomed"),
                    "condition_name": condition.get("name")
                })

        # Aggregations
        aggregations = []
        if query_data.get("query_type") == "count":
            aggregations.append("count")
        if query_data.get("query_type") == "aggregate":
            aggregations.extend(["count", "age_stats", "gender_dist"])

        return QueryIntent(
            query_type=query_data.get("query_type", "list"),
            resources=query_data.get("resources", ["Patient"]),
            filters=filters,
            view_definitions=query_data.get("view_definitions", ["patient_demographics"]),
            search_params=search_params,
            post_filters=post_filters,
            aggregations=aggregations,
            explanation=query_data.get("explanation", f"Execute query: {original_query}")
        )

    def _fallback_interpretation(self, query: str) -> QueryIntent:
        """Fallback simple interpretation if LLM fails"""
        logger.warning("Using fallback interpretation")

        query_lower = query.lower()

        # Simple keyword matching
        view_definitions = ["patient_demographics"]
        search_params = {}
        post_filters = []
        query_type = "list"

        # Gender
        if "male" in query_lower and "female" not in query_lower:
            search_params["gender"] = "male"
        elif "female" in query_lower:
            search_params["gender"] = "female"

        # Count query
        if any(word in query_lower for word in ["how many", "count", "number of"]):
            query_type = "count"

        # Age filter
        import re
        age_match = re.search(r"under\s+(?:age\s+)?(\d+)", query_lower)
        if age_match:
            age = int(age_match.group(1))
            current_year = datetime.now().year
            min_birth_year = current_year - age
            search_params["birthdate"] = f"ge{min_birth_year}-01-01"

        # Conditions
        if any(cond in query_lower for cond in self.CONDITION_MAPPINGS.keys()):
            view_definitions.append("condition_simple")
            for cond_name, codes in self.CONDITION_MAPPINGS.items():
                if cond_name in query_lower:
                    # Use ICD-10 pattern for better matching
                    post_filters.append({
                        "field": "icd10_code",
                        "value": codes.get("icd10_pattern", codes["icd10"]),
                        "condition_name": codes["name"],
                        "use_like": True  # Use LIKE matching for patterns
                    })

        return QueryIntent(
            query_type=query_type,
            resources=["Patient"],
            filters={},
            view_definitions=view_definitions,
            search_params=search_params,
            post_filters=post_filters,
            aggregations=["count"] if query_type == "count" else [],
            explanation=f"Simple interpretation of: {query}"
        )
