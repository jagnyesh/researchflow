"""
SQL Generator for Phenotype Definitions

Converts structured requirements to SQL-on-FHIR queries.

Security: Uses parameterized queries to prevent SQL injection
"""

from typing import Dict, Any, List, Tuple
import logging

logger = logging.getLogger(__name__)


class SQLGenerator:
    """
    Generate SQL queries from structured phenotype requirements

    Security: All methods return parameterized SQL with bound parameters
    to prevent SQL injection vulnerabilities.
    """

    def __init__(self, use_materialized_views: bool = True):
        """
        Initialize SQL generator with schema configuration

        Args:
            use_materialized_views: If True, generates SQL for sqlonfhir materialized views.
                                   If False, generates SQL for legacy HAPI FHIR schema.
        """
        self._param_counter = 0
        self.use_materialized_views = use_materialized_views

        # Configure schema and table names based on mode
        if use_materialized_views:
            # Materialized views schema (production)
            self.schema = "sqlonfhir"
            self.patient_table = "patient_demographics"
            self.condition_table = "condition_simple"
            self.observation_table = "observation_labs"
            # Column mappings for materialized views
            self.patient_id_column = "patient_id"  # Not "id"
            # condition_simple stores the same diagnosis under three columns
            # depending on the source coding system. Match against all three:
            # ICD-10-coded data populates icd10_display, SNOMED-coded data
            # (Synthea) populates snomed_display, code_text is the canonical
            # free-text from FHIR code.text and is populated regardless. A
            # prior change to a single column (icd10_display) silently zeroed
            # the cohort on SNOMED-source datasets.
            self.condition_code_columns = ("code_text", "icd10_display", "snomed_display")
            self.observation_code_column = "code"
        else:
            # Legacy HAPI FHIR schema (deprecated)
            self.schema = None
            self.patient_table = "patient"
            self.condition_table = "condition"
            self.observation_table = "observation"
            # Column mappings for legacy schema
            self.patient_id_column = "id"
            self.condition_code_columns = ("code_display",)
            self.observation_code_column = "code_display"

        # Back-compat alias for callers that still read condition_code_column.
        # Keep the most semantically informative single column for any code
        # path that still expects a single string.
        self.condition_code_column = self.condition_code_columns[0]

    def _get_param_name(self, prefix: str = "p") -> str:
        """Generate unique parameter name"""
        self._param_counter += 1
        return f"{prefix}_{self._param_counter}"

    def _reset_param_counter(self):
        """Reset parameter counter for new query"""
        self._param_counter = 0

    def _build_table_name(self, table: str) -> str:
        """
        Build fully-qualified table name with schema prefix if configured

        Args:
            table: Base table name (patient_table, condition_table, etc.)

        Returns:
            Fully-qualified table name (e.g., "sqlonfhir.patient_demographics" or "patient")
        """
        if self.schema:
            return f"{self.schema}.{table}"
        return table

    def _build_select_fields(self, data_elements: List[str]) -> List[str]:
        """
        Build SELECT field list from requested data elements

        Maps user-requested data elements to actual database columns.
        Gracefully handles unavailable fields by logging warnings.

        Args:
            data_elements: List of requested data element names (e.g., ["demographics", "address"])

        Returns:
            List of column names to include in SELECT clause
        """
        # Hardcoded mapping of data elements to actual database columns
        # Based on sqlonfhir.patient_demographics ViewDefinition columns:
        # id, patient_id, active, birth_date, gender, deceased, deceased_date,
        # family_name, given_name, full_name, phone, email, address_line, city,
        # state, postal_code, country
        field_mapping = {
            "demographics": ["family_name", "given_name", "birth_date", "gender"],
            "family name": ["family_name"],
            "given name": ["given_name"],
            "date of birth": ["birth_date"],
            "birth_date": ["birth_date"],
            "birthdate": ["birth_date"],
            "dob": ["birth_date"],
            "gender": ["gender"],
            "address": ["address_line", "city", "state", "postal_code", "country"],
            "phone": ["phone"],
            "email": ["email"],
        }

        # Always include patient_id
        patient_id_col = self.patient_id_column
        fields = [f"p.{patient_id_col} as patient_id"]

        if not data_elements:
            # Default to basic demographics if no elements specified
            logger.info("No data_elements specified, defaulting to basic demographics")
            fields.extend(["p.family_name", "p.given_name", "p.birth_date", "p.gender"])
            return fields

        # Track which elements we successfully map
        mapped_elements = set()
        unavailable_elements = []

        for element in data_elements:
            element_lower = element.lower().strip()

            if element_lower in field_mapping:
                columns = field_mapping[element_lower]
                if not columns:
                    # Empty list means field not available in schema yet
                    unavailable_elements.append(element)
                    logger.warning(
                        f"✗ Data element '{element}' not yet available in materialized views, skipping"
                    )
                else:
                    for col in columns:
                        field_str = f"p.{col}"
                        if field_str not in fields:
                            fields.append(field_str)
                    mapped_elements.add(element)
                    logger.debug(f"✓ Mapped data element '{element}' → {columns}")
            else:
                unavailable_elements.append(element)
                logger.warning(f"✗ Data element '{element}' not available in schema, skipping")

        # Log summary
        if unavailable_elements:
            logger.info(
                f"Skipped {len(unavailable_elements)} unavailable data elements: {unavailable_elements}"
            )
        if mapped_elements:
            logger.info(
                f"Successfully mapped {len(mapped_elements)} data elements: {list(mapped_elements)}"
            )

        return fields

    def generate_phenotype_sql(
        self, requirements: Dict[str, Any], count_only: bool = False
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Generate SQL-on-FHIR query from requirements

        Args:
            requirements: Structured requirements dict
            count_only: If True, generate COUNT query for estimation

        Returns:
            Tuple of (SQL query string, parameters dict)

        Security:
            Uses parameterized queries to prevent SQL injection
        """
        # Reset parameter counter for new query
        self._reset_param_counter()
        params = {}

        inclusion = requirements.get("inclusion_criteria", [])
        exclusion = requirements.get("exclusion_criteria", [])
        time_period = requirements.get("time_period", {})
        data_elements = requirements.get("data_elements", [])

        # Build base patient query
        patient_id_col = self.patient_id_column
        if count_only:
            select_clause = f"SELECT COUNT(DISTINCT p.{patient_id_col}) as patient_count"
        else:
            # Use dynamic field selection based on requested data elements
            fields = self._build_select_fields(data_elements)
            select_clause = "SELECT DISTINCT\n    " + ",\n    ".join(fields)

        from_clause = f"FROM {self._build_table_name(self.patient_table)} p"
        where_clauses = []

        # Add inclusion criteria
        if inclusion:
            inclusion_conditions, inclusion_params = self._build_criteria_conditions(
                inclusion, include=True
            )
            if inclusion_conditions:
                where_clauses.extend(inclusion_conditions)
                params.update(inclusion_params)

        # Add exclusion criteria
        if exclusion:
            exclusion_conditions, exclusion_params = self._build_criteria_conditions(
                exclusion, include=False
            )
            if exclusion_conditions:
                where_clauses.extend(exclusion_conditions)
                params.update(exclusion_params)

        # Add time period filter if specified
        if time_period.get("start") or time_period.get("end"):
            time_conditions, time_params = self._build_time_conditions(time_period)
            if time_conditions:
                where_clauses.extend(time_conditions)
                params.update(time_params)

        # Construct final query
        where_clause = ""
        if where_clauses:
            where_clause = "WHERE " + " AND ".join(where_clauses)

        sql = f"{select_clause}\n{from_clause}\n{where_clause}"

        logger.debug(f"Generated SQL:\n{sql}")
        logger.debug(f"Parameters: {params}")
        return sql, params

    def _normalize_criterion(self, criterion: Dict) -> Dict:
        """
        Normalize criterion to ensure it has 'concepts' structure.

        Handles both formats:
        1. Nested (expected): {"description": "...", "concepts": [{...}]}
        2. Flat (legacy): {"type": "...", "code": "...", "description": "..."}

        Args:
            criterion: Raw criterion dict

        Returns:
            Normalized criterion with "concepts" key
        """
        # If already has concepts, return as-is
        if "concepts" in criterion and criterion["concepts"]:
            return criterion

        # Convert flat structure to nested format
        logger.debug(f"Converting flat criterion to nested format: {criterion}")

        # Check if this is a flat criterion
        if "type" in criterion:
            # Flat structure: {"type": "condition", "code": "diabetes", ...}
            concept = {
                "type": criterion.get("type"),
                "term": criterion.get("code") or criterion.get("value") or criterion.get("term"),
                "details": criterion.get("description", ""),
            }

            normalized = {"description": criterion.get("description", ""), "concepts": [concept]}

            logger.debug(f"Normalized to: {normalized}")
            return normalized

        # If no recognizable structure, return as-is (will result in empty concepts)
        logger.warning(f"Criterion has unrecognized structure: {criterion}")
        return criterion

    def _build_criteria_conditions(
        self, criteria: List[Dict], include: bool = True
    ) -> Tuple[List[str], Dict[str, Any]]:
        """
        Build SQL conditions from criteria

        Args:
            criteria: List of criterion dicts
            include: True for inclusion, False for exclusion

        Returns:
            Tuple of (List of SQL condition strings, parameters dict)
        """
        conditions = []
        params = {}

        logger.info(
            f"[SQLGenerator] Building criteria conditions for {len(criteria)} criteria (include={include})"
        )
        logger.debug(f"[SQLGenerator] Input criteria structure: {criteria}")

        for i, criterion in enumerate(criteria):
            # Normalize criterion to ensure it has "concepts" structure
            criterion = self._normalize_criterion(criterion)

            concepts = criterion.get("concepts", [])
            criterion_desc = criterion.get("description", criterion.get("text", "N/A"))

            logger.debug(f"Processing criterion: '{criterion_desc}' with {len(concepts)} concepts")
            logger.debug(f"Concepts: {concepts}")

            for concept in concepts:
                concept_type = concept.get("type")
                term = concept.get("term")

                logger.debug(f"Processing concept: type={concept_type}, term='{term}'")

                if concept_type == "condition":
                    # Build condition query
                    condition, condition_params = self._build_condition_clause(term, include)
                    if condition:
                        logger.debug(f"Added condition clause: {condition}")
                        conditions.append(condition)
                        params.update(condition_params)

                elif concept_type in ("demographic", "demographics"):
                    # Accept both singular ("demographic" — what the LLM
                    # extractor and RequirementsBuilder produce) and plural.
                    condition, demo_params = self._build_demographic_clause(
                        term, concept.get("details", "")
                    )
                    logger.debug(
                        f"Demographic clause result: condition='{condition}', params={demo_params}"
                    )
                    if condition:
                        logger.info(
                            f"✓ Added demographic filter: {condition} with params {demo_params}"
                        )
                        conditions.append(condition)
                        params.update(demo_params)
                    else:
                        logger.warning(f"✗ No demographic clause generated for term='{term}'")

                elif concept_type == "lab":
                    # Build lab value query
                    condition, lab_params = self._build_lab_clause(term, include)
                    if condition:
                        logger.debug(f"Added lab clause: {condition}")
                        conditions.append(condition)
                        params.update(lab_params)

        logger.info(
            f"[SQLGenerator] Generated {len(conditions)} WHERE conditions from {len(criteria)} criteria"
        )
        logger.info(f"[SQLGenerator] Parameters: {params}")

        if len(conditions) == 0 and len(criteria) > 0:
            logger.error(
                f"[SQLGenerator] ⚠️ PROBLEM: {len(criteria)} criteria provided but 0 WHERE conditions generated! "
                f"This will result in unfiltered query. Check criteria structure."
            )

        logger.debug(f"Final conditions: {conditions}")
        return conditions, params

    def _build_condition_clause(
        self, condition_term: str, include: bool
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Build SQL for condition/diagnosis criterion

        IMPORTANT: Uses LOWER() for case-insensitive matching to avoid missing patients
        due to capitalization variations (e.g., "Diabetes" vs "diabetes").

        Example: Without LOWER(), the query "diabetes" would miss patients with
        "Diabetes mellitus type 2" (capital D), leading to incorrect cohort counts.

        Returns:
            Tuple of (SQL condition string, parameters dict)
        """
        operator = "EXISTS" if include else "NOT EXISTS"
        param_name = self._get_param_name("condition")
        params = {param_name: f"%{condition_term}%"}

        condition_table = self._build_table_name(self.condition_table)
        patient_id_col = self.patient_id_column

        # OR across every diagnosis-text column the MV exposes so SNOMED-
        # only, ICD-10-only, and mixed deployments all match. Mirrors the
        # text-matching pattern in app/agents/phenotype_agent.py.
        col_match = " OR ".join(
            f"LOWER(c.{col}) LIKE LOWER(:{param_name})" for col in self.condition_code_columns
        )

        # nosec B608 - Table/column names from validated configuration, parameters are bound
        # CRITICAL: LOWER() is required for case-insensitive matching (see docstring)
        sql = f"""{operator} (
        SELECT 1 FROM {condition_table} c
        WHERE c.patient_id = p.{patient_id_col}
        AND ({col_match})
    )"""

        return sql, params

    @staticmethod
    def _parse_age_details(details: str) -> Tuple[Any, Any]:
        """
        Parse an age comparison from free-form details.

        Issue #51 (Sprint 6.5c, 2026-05-18): the LLM's medical-concept prompt
        documents `details: 'between 18 and 40'` as a canonical age-range
        format. The pre-fix parser only handled comparison ops (>/<) and
        silently dropped any range-shaped input. Sprint 6.5c stress test
        showed 28% (7/25) of demographic inputs hit this path. Now returns
        ('BETWEEN', (lo, hi)) for range syntax so _build_demographic_clause
        can emit a BETWEEN SQL predicate.

        Return shapes:
          - (">", int_age) for greater-than comparisons
          - ("<", int_age) for less-than comparisons
          - ("BETWEEN", (lo, hi)) for inclusive ranges
          - (None, None) when no parseable age constraint is present
        """
        import re

        if not details:
            return None, None
        text = details.lower().strip()

        # Try range syntax first ("between X and Y"). Matches the LLM's
        # canonical age-range format per _MEDICAL_CONCEPTS_SYSTEM_PROMPT.
        # Trailing comments (e.g., "between 20 and 29 (in their 20s)") are
        # ignored by the partial-match regex.
        range_match = re.search(r"between\s+(\d+)\s+and\s+(\d+)", text)
        if range_match:
            lo, hi = int(range_match.group(1)), int(range_match.group(2))
            return "BETWEEN", (lo, hi)

        gt_words = ("greater than", "more than", "older than", "above", "over")
        lt_words = ("less than", "fewer than", "younger than", "below", "under")
        op = None
        if ">" in text or any(w in text for w in gt_words):
            op = ">"
        elif "<" in text or any(w in text for w in lt_words):
            op = "<"
        if op is None:
            return None, None
        m = re.search(r"(\d+)", text)
        if not m:
            return None, None
        return op, int(m.group(1))

    def _build_demographic_clause(self, term: str, details: str) -> Tuple[str, Dict[str, Any]]:
        """
        Build SQL for demographic criterion

        Returns:
            Tuple of (SQL condition string, parameters dict)
        """
        # Normalize inputs for matching
        term_lower = term.lower().strip() if term else ""
        details_lower = details.lower().strip() if details else ""

        logger.debug(
            f"_build_demographic_clause: term='{term}' (normalized: '{term_lower}'), details='{details}'"
        )
        # [ISSUE-51-PROBE-C-ENTRY] Layer 2 input. Shows what shape the dispatcher
        # delivers to the demographic clause builder.
        logger.info(
            f"[ISSUE-51-PROBE-C-ENTRY] term={term!r} details={details!r} "
            f"term_lower={term_lower!r} details_lower={details_lower!r}"
        )

        # Parse age criteria. The LLM extractor emits details in mixed
        # forms — symbolic ("> 18"), natural-language ("greater than 18
        # years", "above 18", "over 65"), or range ("between 40 and 65").
        # Normalize all to a comparison op + integer age, or BETWEEN + (lo, hi).
        if "age" in term_lower:
            op, age_value = self._parse_age_details(details)
            if op is None:
                logger.warning(f"Could not parse age details: {details!r}")
                logger.info(
                    f"[ISSUE-51-PROBE-C-EXIT] branch=age_parse_fail "
                    f"term={term!r} details={details!r} sql='' params={{}}"
                )
                return "", {}
            # birth_date is materialized as text (FHIR transpiler default);
            # cast to date so AGE() accepts it.
            if op == "BETWEEN":
                # Issue #51 fix: range-shaped age criteria. The LLM emits
                # 'between X and Y' per the medical-concepts prompt; emit
                # an inclusive SQL BETWEEN predicate.
                lo, hi = age_value
                lo_param = self._get_param_name("age_lo")
                hi_param = self._get_param_name("age_hi")
                params = {lo_param: lo, hi_param: hi}
                sql = (
                    f"EXTRACT(YEAR FROM AGE(CURRENT_DATE, p.birth_date::date)) "
                    f"BETWEEN :{lo_param} AND :{hi_param}"
                )
                logger.info(
                    f"[ISSUE-51-PROBE-C-EXIT] branch=age_success_between term={term!r} sql={sql!r}"
                )
                return sql, params
            param_name = self._get_param_name("age")
            params = {param_name: age_value}
            sql = f"EXTRACT(YEAR FROM AGE(CURRENT_DATE, p.birth_date::date)) {op} :{param_name}"
            logger.info(f"[ISSUE-51-PROBE-C-EXIT] branch=age_success term={term!r} sql={sql!r}")
            return sql, params

        # Parse gender - MORE ROBUST MATCHING
        gender_value = None

        # Check if term contains gender keywords
        # IMPORTANT: Check "female" before "male" to avoid substring collision
        # ("male" is a substring of "female", so order matters)
        if "female" in term_lower:
            gender_value = "female"
        elif "male" in term_lower:
            gender_value = "male"
        elif "gender" in term_lower:
            # Check details for gender value
            if "male" in details_lower and "female" not in details_lower:
                gender_value = "male"
            elif "female" in details_lower:
                gender_value = "female"

        if gender_value:
            param_name = self._get_param_name("gender")
            params = {param_name: gender_value}
            sql = f"p.gender = :{param_name}"
            logger.info(f"✓ Generated gender filter: {sql} with {param_name}='{gender_value}'")
            logger.info(f"[ISSUE-51-PROBE-C-EXIT] branch=gender_success term={term!r} sql={sql!r}")
            return sql, params

        # If no match, log warning
        logger.warning(f"Could not build demographic clause for term='{term}', details='{details}'")
        logger.info(
            f"[ISSUE-51-PROBE-C-EXIT] branch=no_match term={term!r} details={details!r} sql='' params={{}}"
        )
        return "", {}

    def _build_lab_clause(self, lab_term: str, include: bool) -> Tuple[str, Dict[str, Any]]:
        """
        Build SQL for lab value criterion

        Returns:
            Tuple of (SQL condition string, parameters dict)
        """
        operator = "EXISTS" if include else "NOT EXISTS"
        param_name = self._get_param_name("lab")
        params = {param_name: f"%{lab_term}%"}

        # nosec B608 - Table/column names from validated configuration, parameters are bound
        sql = f"""{operator} (
        SELECT 1 FROM observation o
        WHERE o.patient_id = p.id
        AND LOWER(o.code_display) LIKE LOWER(:{param_name})
    )"""

        return sql, params

    def _build_time_conditions(self, time_period: Dict) -> Tuple[List[str], Dict[str, Any]]:
        """
        Build time period filter conditions

        Returns:
            Tuple of (List of conditions, parameters dict)
        """
        conditions = []
        params = {}

        if time_period.get("start"):
            param_name = self._get_param_name("start_date")
            params[param_name] = time_period["start"]
            conditions.append(f"p.lastUpdated >= :{param_name}")

        if time_period.get("end"):
            param_name = self._get_param_name("end_date")
            params[param_name] = time_period["end"]
            conditions.append(f"p.lastUpdated <= :{param_name}")

        return conditions, params

    def generate_data_availability_query(
        self, data_element: str, time_period: Dict
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Generate query to check data availability

        Args:
            data_element: Type of data (e.g., 'clinical_notes', 'lab_results')
            time_period: Time period dict

        Returns:
            Tuple of (SQL query string, parameters dict)

        Security:
            Uses parameterized queries. Note: table/column names validated by hard-coded mapping.
        """
        # Reset parameter counter
        self._reset_param_counter()
        params = {}

        # Map data element to table/column (validated whitelist - no user input)
        table_mapping = {
            "clinical_notes": ("document_reference", "date"),
            "lab_results": ("observation", "effectiveDateTime"),
            "medications": ("medication_request", "authoredOn"),
        }

        table, date_field = table_mapping.get(data_element, ("observation", "effectiveDateTime"))

        time_filter = ""
        if time_period.get("start") and time_period.get("end"):
            start_param = self._get_param_name("start")
            end_param = self._get_param_name("end")
            params[start_param] = time_period["start"]
            params[end_param] = time_period["end"]
            time_filter = f"""
            AND {date_field} BETWEEN :{start_param}
                AND :{end_param}"""

        # Table and column names are from validated whitelist above
        # nosec B608 - Table/column names from validated whitelist, parameters are bound
        sql = f"""
SELECT
    COUNT(DISTINCT patient_id) as patients_with_data,
    (SELECT COUNT(DISTINCT id) FROM patient) as total_patients,
    COUNT(*) as total_records
FROM {table}
WHERE 1=1{time_filter}"""

        return sql, params
