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

from langsmith import traceable

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
    group_by: List[str]  # NEW: Dimensions to group by (e.g., ["gender"], ["gender", "age_group"])
    aggregation_type: str  # NEW: Type of aggregation ("count", "avg", "sum", "min", "max")


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
            "columns": [
                "id",
                "gender",
                "birth_date",
                "family_name",
                "given_name",
                "full_name",
                "phone",
                "email",
                "address",
                "city",
                "state",
                "postal_code",
            ],
        },
        "observation_labs": {
            "resource": "Observation",
            "description": "Laboratory test results with LOINC codes, values, units",
            "columns": [
                "patient_id",
                "code",
                "code_display",
                "value_quantity",
                "value_unit",
                "effective_datetime",
                "interpretation",
                "ref_range_low",
                "ref_range_high",
            ],
        },
        "condition_simple": {
            "resource": "Condition",
            "description": "Patient conditions with ICD-10 and SNOMED codes (materialized view with dual columns)",
            "columns": [
                "id",
                "patient_ref",
                "patient_id",
                "icd10_code",
                "icd10_display",
                "snomed_code",
                "snomed_display",
                "code_text",
                "clinical_status",
            ],
        },
        "medication_requests": {
            "resource": "MedicationRequest",
            "description": "Medication orders and prescriptions with RxNorm codes",
            "columns": [
                "patient_id",
                "status",
                "medication_code",
                "medication_display",
                "dosage_text",
                "authored_on",
            ],
        },
        "procedure_history": {
            "resource": "Procedure",
            "description": "Patient procedures with CPT and SNOMED codes",
            "columns": [
                "patient_id",
                "status",
                "cpt_code",
                "cpt_display",
                "snomed_code",
                "snomed_display",
                "performed_datetime",
            ],
        },
    }

    # Common medical condition mappings
    CONDITION_MAPPINGS = {
        "type 2 diabetes": {
            "snomed": "44054006",
            "icd10": "E11.9",
            "icd10_pattern": "E11%",
            "name": "Type 2 diabetes mellitus",
        },
        "diabetes": {
            "snomed": "73211009",
            "icd10": "E11.9",
            "icd10_pattern": "E1%",
            "name": "Diabetes mellitus (all types)",
        },
        "hypertension": {
            "snomed": "38341003",
            "icd10": "I10",
            "icd10_pattern": "I10%",
            "name": "Hypertension",
        },
        "high blood pressure": {
            "snomed": "38341003",
            "icd10": "I10",
            "icd10_pattern": "I10%",
            "name": "Hypertension",
        },
        "hyperlipidemia": {
            "snomed": "13645005",
            "icd10": "E78.5",
            "icd10_pattern": "E78%",
            "name": "Hyperlipidemia",
        },
        "asthma": {
            "snomed": "195967001",
            "icd10": "J45.909",
            "icd10_pattern": "J45%",
            "name": "Asthma",
        },
    }

    def __init__(self):
        self.llm_client = LLMClient()

    @traceable(tags=["query-interpreter", "portal:exploratory"])
    async def interpret_query(self, natural_language_query: str) -> QueryIntent:
        """
        Interpret natural language query and return structured intent

        Sprint 8 Optimization 8: Hybrid Haiku/Sonnet strategy (90% cost savings)
        - Try Haiku first (10x cheaper) for simple queries
        - Fallback to Sonnet if parsing fails or validation doesn't pass
        - Expected: 90% Haiku success rate, 10% Sonnet fallback

        Args:
            natural_language_query: User's question in natural language

        Returns:
            QueryIntent with parsed information
        """
        logger.info(f"Interpreting query: {natural_language_query}")

        # Build prompts
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(natural_language_query)
        schema_description = """
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
                """

        # Sprint 8 Optimization 8: Try Haiku first (90% of queries)
        try:
            logger.info("Attempting query interpretation with Haiku (10x cheaper)")
            response = await self.llm_client.extract_structured_json(
                prompt=user_prompt,
                schema_description=schema_description,
                system=system_prompt,
                model="claude-3-5-haiku-20241022",  # Use Haiku first
            )

            # Validate response structure
            if self._is_valid_query_response(response):
                query_data = response
                intent = self._build_query_intent(query_data, natural_language_query)
                logger.info(
                    f"✅ Haiku successfully parsed query (cost: ~$0.0007): {intent.explanation}"
                )
                return intent
            else:
                logger.warning("⚠️ Haiku response validation failed, falling back to Sonnet")
                raise ValueError("Invalid query structure from Haiku")

        except Exception as e:
            logger.info(f"🔄 Haiku failed ({str(e)}), falling back to Sonnet for complex query")

            # Fallback to Sonnet (10% of queries - complex)
            try:
                response = await self.llm_client.extract_structured_json(
                    prompt=user_prompt,
                    schema_description=schema_description,
                    system=system_prompt,
                    # Use default Sonnet model
                )

                query_data = response
                intent = self._build_query_intent(query_data, natural_language_query)
                logger.info(
                    f"✅ Sonnet successfully parsed complex query (cost: ~$0.007): {intent.explanation}"
                )
                return intent

            except Exception as sonnet_error:
                logger.error(f"Error interpreting query with Sonnet: {sonnet_error}")
                # Final fallback to simple parsing
                return self._fallback_interpretation(natural_language_query)

    def _is_valid_query_response(self, response: Dict[str, Any]) -> bool:
        """
        Validate query response structure

        Sprint 8 Optimization 8: Validates Haiku output before acceptance

        Args:
            response: Parsed JSON from LLM

        Returns:
            True if response has required fields and valid structure
        """
        required_fields = ["query_type", "resources", "view_definitions"]

        # Check required fields exist
        if not all(field in response for field in required_fields):
            logger.warning(f"Missing required fields. Got: {list(response.keys())}")
            return False

        # Check query_type is valid
        valid_query_types = ["count", "list", "filter", "aggregate"]
        if response.get("query_type") not in valid_query_types:
            logger.warning(f"Invalid query_type: {response.get('query_type')}")
            return False

        # Check resources is non-empty list
        if not isinstance(response.get("resources"), list) or len(response["resources"]) == 0:
            logger.warning(f"Invalid resources: {response.get('resources')}")
            return False

        # Check view_definitions is non-empty list
        if (
            not isinstance(response.get("view_definitions"), list)
            or len(response["view_definitions"]) == 0
        ):
            logger.warning(f"Invalid view_definitions: {response.get('view_definitions')}")
            return False

        return True

    def _build_system_prompt(self) -> str:
        """
        Build system prompt for Claude

        Sprint 8 Optimization 7: Condensed from 1200 → 700 tokens (42% reduction)
        Reduces verbose pattern examples while maintaining clarity.
        """
        view_defs_desc = "\n".join(
            [
                f"- {name}: {info['description']}"
                for name, info in self.AVAILABLE_VIEW_DEFINITIONS.items()
            ]
        )

        # Sprint 8 Optimization 7: Condensed system prompt (42% token reduction)
        # Removed verbose pattern examples, kept essential information
        return f"""Translate clinical research queries into structured SQL-on-FHIR ViewDefinition executions.

ViewDefinitions:
{view_defs_desc}

Common Conditions:
{json.dumps(self.CONDITION_MAPPINGS, indent=2)}

Guidelines:
1. Identify needed ViewDefinitions
2. Extract demographic filters (gender, age)
3. Map medical terms to SNOMED/ICD-10 codes
4. Determine query type: count, list, filter, or aggregate
5. Age calculation: current_year - birth_year; "under age X" → birthdate > (current_year - X)
6. Aggregation patterns → group_by: ["dimension"]
   - Keywords: "breakdown/split/group/categorize by X", "by X" (end), "broken down by"
   - Multiple: "by X and Y" → ["X", "Y"]
   - Common: gender, age_group, condition_type, medication_type
7. Count distinct patterns → aggregation_type: "count_distinct", group_by: []
   - Keywords: "distinct/unique/different X"
   - Examples: "distinct conditions", "unique medications"
   - Note: counts resources, not patients; no group_by"""

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
- group_by: list of dimensions to group by (e.g., ["gender"], ["gender", "age_group"]) - extract from patterns like "breakdown by", "broken down by", "break down by", "split by", "grouped by", "by X"
- aggregation_type: type of aggregation (default: "count")

Focus on:
1. Demographics (gender, age)
2. Conditions/diagnoses
3. Time periods
4. Data elements requested
5. Aggregation dimensions (breakdown by gender, split by age group, etc.)
"""

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
                snomed_code = condition.get("snomed")
                icd10_code = condition.get("icd10")
                condition_name = condition.get("name")

                # Check if we have a valid SNOMED or ICD-10 code
                if snomed_code or icd10_code:
                    # Standard code lookup (preferred)
                    post_filters.append(
                        {
                            "field": "snomed_code" if snomed_code else "icd10_code",
                            "value": snomed_code or icd10_code,
                            "condition_name": condition_name,
                        }
                    )
                else:
                    # FALLBACK: Use text search for unmapped conditions
                    # This handles cases where condition is not in CONDITION_MAPPINGS
                    logger.warning(
                        f"Condition '{condition_name}' not mapped to SNOMED/ICD-10 codes. "
                        f"Using text search fallback. Consider adding to CONDITION_MAPPINGS for accuracy."
                    )
                    post_filters.append(
                        {
                            "field": "code_text",
                            "value": None,  # Special flag indicating text search
                            "condition_name": condition_name,
                            "use_text_search": True,
                            "text_pattern": f"%{condition_name}%",
                        }
                    )

        # Aggregations
        aggregations = []
        if query_data.get("query_type") == "count":
            aggregations.append("count")
        if query_data.get("query_type") == "aggregate":
            aggregations.extend(["count", "age_stats", "gender_dist"])

        # NEW: Extract group_by and aggregation_type from LLM response
        group_by = query_data.get("group_by", [])
        aggregation_type = query_data.get("aggregation_type", "count")

        # DEFENSIVE FALLBACK: If LLM failed to detect breakdown pattern, use regex
        if not group_by:
            import re

            query_lower = original_query.lower()

            # Regex patterns for breakdown detection
            # Pattern captures: "breakdown by X", "broken down by X and Y", "split by X", etc.
            breakdown_patterns = [
                r"break\s*down\s+by\s+([a-z_,\s]+)",
                r"broken\s+down\s+by\s+([a-z_,\s]+)",
                r"breakdown\s+by\s+([a-z_,\s]+)",
                r"split\s+by\s+([a-z_,\s]+)",
                r"grouped?\s+by\s+([a-z_,\s]+)",
                r"group\s+by\s+([a-z_,\s]+)",
            ]

            for pattern in breakdown_patterns:
                match = re.search(pattern, query_lower)
                if match:
                    # Extract dimension string (e.g., "gender", "age and gender", "gender, age")
                    dimension_str = match.group(1).strip()

                    # Parse multiple dimensions (split by "and" or ",")
                    dimensions = re.split(r"\s+and\s+|,\s*", dimension_str)

                    # Map common terms to standard dimension names
                    dimension_mapping = {
                        "gender": "gender",
                        "sex": "gender",
                        "age": "age_group",
                        "age group": "age_group",
                        "age groups": "age_group",
                    }

                    group_by = []
                    for dim in dimensions:
                        dim = dim.strip()
                        if dim in dimension_mapping:
                            group_by.append(dimension_mapping[dim])
                        else:
                            # Keep original if not in mapping
                            group_by.append(dim)

                    logger.info(f"Regex fallback detected breakdown query: group_by={group_by}")
                    break

        # Log breakdown detection
        if group_by:
            logger.info(
                f"Detected breakdown query: group_by={group_by}, aggregation_type={aggregation_type}"
            )

        return QueryIntent(
            query_type=query_data.get("query_type", "list"),
            resources=query_data.get("resources", ["Patient"]),
            filters=filters,
            view_definitions=query_data.get("view_definitions", ["patient_demographics"]),
            search_params=search_params,
            post_filters=post_filters,
            aggregations=aggregations,
            explanation=query_data.get("explanation", f"Execute query: {original_query}"),
            group_by=group_by,
            aggregation_type=aggregation_type,
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
                    post_filters.append(
                        {
                            "field": "icd10_code",
                            "value": codes.get("icd10_pattern", codes["icd10"]),
                            "condition_name": codes["name"],
                            "use_like": True,  # Use LIKE matching for patterns
                        }
                    )

        # BREAKDOWN DETECTION - Regex fallback
        group_by = []
        aggregation_type = "count"

        # Regex patterns for breakdown detection
        breakdown_patterns = [
            r"break\s*down\s+by\s+([a-z_,\s]+)",
            r"broken\s+down\s+by\s+([a-z_,\s]+)",
            r"breakdown\s+by\s+([a-z_,\s]+)",
            r"split\s+by\s+([a-z_,\s]+)",
            r"grouped?\s+by\s+([a-z_,\s]+)",
            r"group\s+by\s+([a-z_,\s]+)",
        ]

        for pattern in breakdown_patterns:
            match = re.search(pattern, query_lower)
            if match:
                # Extract dimension string (e.g., "gender", "age and gender")
                dimension_str = match.group(1).strip()

                # Parse multiple dimensions (split by "and" or ",")
                dimensions = re.split(r"\s+and\s+|,\s*", dimension_str)

                # Map common terms to standard dimension names
                dimension_mapping = {
                    "gender": "gender",
                    "sex": "gender",
                    "age": "age_group",
                    "age group": "age_group",
                    "age groups": "age_group",
                }

                for dim in dimensions:
                    dim = dim.strip()
                    if dim in dimension_mapping:
                        group_by.append(dimension_mapping[dim])
                    else:
                        # Keep original if not in mapping
                        group_by.append(dim)

                logger.info(f"Fallback regex detected breakdown query: group_by={group_by}")
                break

        return QueryIntent(
            query_type=query_type,
            resources=["Patient"],
            filters={},
            view_definitions=view_definitions,
            search_params=search_params,
            post_filters=post_filters,
            aggregations=["count"] if query_type == "count" else [],
            explanation=f"Simple interpretation of: {query}",
            group_by=group_by,
            aggregation_type=aggregation_type,
        )
