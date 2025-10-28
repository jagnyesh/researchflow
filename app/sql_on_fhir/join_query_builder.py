"""
JOIN Query Builder for Multi-View Queries

Builds SQL queries that JOIN multiple materialized views
to support complex filters like "male patients with diabetes".

Examples:
  - Demographics + Conditions: patient_demographics JOIN condition_simple
  - Demographics + Medications: patient_demographics JOIN medication_requests
  - Demographics + Labs: patient_demographics JOIN observation_labs

Architecture:
- Uses dual column architecture (patient_id for JOINs)
- Applies filters to appropriate views
- Returns DISTINCT patient counts
- Includes SQL visibility for debugging
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class JoinQueryBuilder:
    """
    Builds SQL queries with JOINs across multiple materialized views

    Supports queries like:
    - "male patients with diabetes" → demographics JOIN conditions
    - "female patients on metformin" → demographics JOIN medications
    - "patients with HbA1c > 7" → demographics JOIN labs
    """

    SCHEMA_NAME = "sqlonfhir"

    # Map view names to their primary table aliases
    VIEW_ALIASES = {
        "patient_demographics": "p",
        "patient_simple": "ps",
        "condition_simple": "c",
        "observation_labs": "o",
        "medication_requests": "m",
        "procedure_history": "pr"
    }

    # Demographic views (don't need JOIN)
    DEMOGRAPHIC_VIEWS = ["patient_demographics", "patient_simple"]

    def __init__(self):
        """Initialize JOIN query builder"""
        pass

    def build_multi_view_count_query(
        self,
        view_definitions: List[str],
        search_params: Dict[str, Any],
        post_filters: List[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Build COUNT query that JOINs multiple views

        Args:
            view_definitions: List of view names to JOIN
            search_params: Demographic search params (gender, age, etc.)
            post_filters: Condition/medication/lab filters to apply

        Returns:
            Dict with:
            - sql: Generated SQL query
            - parameters: Parameters for query (if using parameterized queries)
            - primary_view: Base view for JOIN
            - joined_views: List of views being joined
            - filter_summary: Human-readable filter description
        """
        logger.info(f"Building JOIN query for views: {view_definitions}")

        # Determine if this is a single-view or multi-view query
        if len(view_definitions) == 1:
            # Single view - no JOIN needed
            return self._build_single_view_query(
                view_definitions[0],
                search_params
            )

        # Multi-view query - build JOIN
        return self._build_join_query(
            view_definitions,
            search_params,
            post_filters or []
        )

    def _build_single_view_query(
        self,
        view_name: str,
        search_params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Build simple COUNT query for single view"""
        alias = self.VIEW_ALIASES.get(view_name, "v")

        # Base query
        sql = f"SELECT COUNT(DISTINCT {alias}.patient_id)\n"
        sql += f"  FROM {self.SCHEMA_NAME}.{view_name} {alias}"

        # Add WHERE clauses
        where_clauses = self._build_where_clauses(alias, search_params, [])
        if where_clauses:
            sql += "\n WHERE " + "\n   AND ".join(where_clauses)

        return {
            "sql": sql,
            "parameters": {},
            "primary_view": view_name,
            "joined_views": [],
            "filter_summary": self._summarize_filters(search_params, [])
        }

    def _build_join_query(
        self,
        view_definitions: List[str],
        search_params: Dict[str, Any],
        post_filters: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Build JOIN query across multiple views"""

        # Determine primary view (demographics) and joined views
        primary_view = None
        joined_views = []

        for view_name in view_definitions:
            if view_name in self.DEMOGRAPHIC_VIEWS:
                primary_view = view_name
            else:
                joined_views.append(view_name)

        # Default to patient_demographics if no demographic view specified
        if not primary_view:
            primary_view = "patient_demographics"

        # Get aliases
        primary_alias = self.VIEW_ALIASES[primary_view]

        # Build SQL
        sql = f"SELECT COUNT(DISTINCT {primary_alias}.patient_id)\n"
        sql += f"  FROM {self.SCHEMA_NAME}.{primary_view} {primary_alias}"

        # Add JOINs
        for view_name in joined_views:
            alias = self.VIEW_ALIASES.get(view_name, view_name[0])
            sql += f"\n  JOIN {self.SCHEMA_NAME}.{view_name} {alias}"
            sql += f"\n    ON {primary_alias}.patient_id = {alias}.patient_id"

        # Build WHERE clauses
        where_clauses = self._build_where_clauses(
            primary_alias,
            search_params,
            post_filters
        )

        # Add WHERE clauses for joined views
        for view_name in joined_views:
            alias = self.VIEW_ALIASES.get(view_name, view_name[0])
            for post_filter in post_filters:
                where_clauses.extend(
                    self._build_post_filter_clauses(alias, post_filter)
                )

        if where_clauses:
            sql += "\n WHERE " + "\n   AND ".join(where_clauses)

        return {
            "sql": sql,
            "parameters": {},
            "primary_view": primary_view,
            "joined_views": joined_views,
            "filter_summary": self._summarize_filters(search_params, post_filters)
        }

    def _build_where_clauses(
        self,
        alias: str,
        search_params: Dict[str, Any],
        post_filters: List[Dict[str, Any]]
    ) -> List[str]:
        """Build WHERE clause conditions for demographic filters"""
        clauses = []

        # Gender filter
        if "gender" in search_params:
            gender = search_params["gender"]
            clauses.append(f"LOWER({alias}.gender) = '{gender.lower()}'")

        # Age/birthdate filters
        if "birthdate_min" in search_params:
            # birthdate >= YYYY-MM-DD
            date_val = search_params["birthdate_min"].replace("ge", "")
            clauses.append(f"{alias}.dob >= '{date_val}'")

        if "birthdate_max" in search_params:
            # birthdate <= YYYY-MM-DD
            date_val = search_params["birthdate_max"].replace("le", "")
            clauses.append(f"{alias}.dob <= '{date_val}'")

        return clauses

    def _build_post_filter_clauses(
        self,
        alias: str,
        post_filter: Dict[str, Any]
    ) -> List[str]:
        """
        Build WHERE clauses for post-filters (conditions, meds, labs)

        Supports flexible field matching to handle incomplete FHIR coding:
        - Tries specified field first (icd10_code, snomed_code)
        - Falls back to code_text for robustness
        - Uses OR clause to match any available coding system
        """
        clauses = []

        field = post_filter.get("field")
        value = post_filter.get("value")
        use_like = post_filter.get("use_like", False)
        condition_name = post_filter.get("condition_name")

        if not field or not value:
            return clauses

        # Build primary filter clause
        if use_like:
            primary_clause = f"{alias}.{field} LIKE '{value}'"
        else:
            primary_clause = f"{alias}.{field} = '{value}'"

        # For condition filters, add fallback to code_text for robustness
        # This handles real-world FHIR data with incomplete ICD-10/SNOMED coding
        if field in ['icd10_code', 'snomed_code'] and condition_name:
            # Extract core medical term for broader matching
            # E.g., "Diabetes mellitus (all types)" → "diabetes"
            # E.g., "Type 2 diabetes mellitus" → "diabetes"
            core_term = self._extract_core_medical_term(condition_name)

            # Try multiple search strategies with OR clause
            fallback_clauses = [
                primary_clause,  # Try coded value first (e.g., SNOMED/ICD-10)
                f"{alias}.code_text ILIKE '%{core_term}%'"  # Then core term (broader)
            ]

            # If core term is different from full name, also try full name
            if core_term.lower() != condition_name.lower():
                fallback_clauses.append(f"{alias}.code_text ILIKE '%{condition_name}%'")

            # Wrap in parentheses for proper OR grouping
            clauses.append(f"({' OR '.join(fallback_clauses)})")
        else:
            # Non-condition filters or no fallback needed
            clauses.append(primary_clause)

        return clauses

    def _extract_core_medical_term(self, condition_name: str) -> str:
        """
        Extract core medical term from verbose condition name

        Handles patterns like:
        - "Diabetes mellitus (all types)" → "diabetes"
        - "Type 2 diabetes mellitus" → "diabetes"
        - "Hypertension (disorder)" → "hypertension"
        - "Chronic kidney disease stage 3" → "kidney disease"

        Args:
            condition_name: Full condition name from LLM

        Returns:
            Core medical term for broader text matching
        """
        import re

        # Remove parenthetical qualifiers: "(all types)", "(disorder)", etc.
        term = re.sub(r'\([^)]*\)', '', condition_name).strip()

        # Extract first significant medical keyword (usually the condition name)
        # Common pattern: "[Type qualifier] [CONDITION] mellitus/disorder"
        words = term.lower().split()

        # Filter out common qualifiers and connecting words
        stop_words = {
            'type', 'stage', 'grade', 'mellitus', 'disorder', 'disease',
            'syndrome', 'condition', '1', '2', '3', 'i', 'ii', 'iii',
            'acute', 'chronic', 'severe', 'mild', 'moderate'
        }
        significant_words = [w for w in words if w not in stop_words and len(w) > 3]

        # Return first significant word, or fall back to first word
        return significant_words[0] if significant_words else (words[0] if words else condition_name.lower())

    def _summarize_filters(
        self,
        search_params: Dict[str, Any],
        post_filters: List[Dict[str, Any]]
    ) -> str:
        """Generate human-readable filter summary"""
        summary_parts = []

        # Gender
        if "gender" in search_params:
            summary_parts.append(f"Gender: {search_params['gender']}")

        # Age range
        if "birthdate_min" in search_params or "birthdate_max" in search_params:
            age_min = search_params.get("birthdate_min", "").replace("ge", "")
            age_max = search_params.get("birthdate_max", "").replace("le", "")
            if age_min and age_max:
                summary_parts.append(f"Birth date: {age_min} to {age_max}")
            elif age_min:
                summary_parts.append(f"Birth date >= {age_min}")
            elif age_max:
                summary_parts.append(f"Birth date <= {age_max}")

        # Conditions/medications/labs
        for post_filter in post_filters:
            condition_name = post_filter.get("condition_name")
            if condition_name:
                summary_parts.append(f"Condition: {condition_name}")

        return ", ".join(summary_parts) if summary_parts else "No filters"
