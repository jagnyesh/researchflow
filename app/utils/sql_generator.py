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
            self.condition_code_column = "code_text"  # Not "code_display"
            self.observation_code_column = "code"
        else:
            # Legacy HAPI FHIR schema (deprecated)
            self.schema = None
            self.patient_table = "patient"
            self.condition_table = "condition"
            self.observation_table = "observation"
            # Column mappings for legacy schema
            self.patient_id_column = "id"
            self.condition_code_column = "code_display"
            self.observation_code_column = "code_display"

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
        # Based on sqlonfhir.patient_demographics schema:
        # Columns: id, patient_id, gender, dob, name_given, name_family
        field_mapping = {
            "demographics": ["name_family", "name_given", "dob", "gender"],
            "family name": ["name_family"],
            "given name": ["name_given"],
            "date of birth": ["dob"],
            "birth_date": ["dob"],
            "birthdate": ["dob"],
            "dob": ["dob"],
            "gender": ["gender"],
            # Address fields don't exist in materialized views yet
            "address": [],
            "phone": [],
            "email": [],
        }

        # Always include patient_id
        patient_id_col = self.patient_id_column
        fields = [f"p.{patient_id_col} as patient_id"]

        if not data_elements:
            # Default to basic demographics if no elements specified
            logger.info("No data_elements specified, defaulting to basic demographics")
            fields.extend(["p.name_family", "p.name_given", "p.dob", "p.gender"])
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

        logger.debug(
            f"Building criteria conditions for {len(criteria)} criteria (include={include})"
        )

        for criterion in criteria:
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

                elif concept_type == "demographics":
                    # Build demographic query
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

        logger.debug(f"Final conditions ({len(conditions)}): {conditions}")
        logger.debug(f"Final params: {params}")
        return conditions, params

    def _build_condition_clause(
        self, condition_term: str, include: bool
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Build SQL for condition/diagnosis criterion

        Returns:
            Tuple of (SQL condition string, parameters dict)
        """
        # Simplified: In production, would use ICD-10/SNOMED codes
        operator = "EXISTS" if include else "NOT EXISTS"
        param_name = self._get_param_name("condition")
        params = {param_name: f"%{condition_term}%"}

        condition_table = self._build_table_name(self.condition_table)
        condition_col = self.condition_code_column
        patient_id_col = self.patient_id_column

        # nosec B608 - Table/column names from validated configuration, parameters are bound
        sql = f"""{operator} (
        SELECT 1 FROM {condition_table} c
        WHERE c.patient_id = p.{patient_id_col}
        AND LOWER(c.{condition_col}) LIKE LOWER(:{param_name})
    )"""

        return sql, params

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

        # Parse age criteria
        if "age" in term_lower:
            if ">" in details:
                age = details.split(">")[1].strip()
                param_name = self._get_param_name("age")
                try:
                    age_value = int(age)
                    params = {param_name: age_value}
                    sql = f"EXTRACT(YEAR FROM AGE(CURRENT_DATE, p.birthdate)) > :{param_name}"
                    return sql, params
                except ValueError:
                    logger.warning(f"Invalid age value: {age}")
                    return "", {}
            elif "<" in details:
                age = details.split("<")[1].strip()
                param_name = self._get_param_name("age")
                try:
                    age_value = int(age)
                    params = {param_name: age_value}
                    sql = f"EXTRACT(YEAR FROM AGE(CURRENT_DATE, p.birthdate)) < :{param_name}"
                    return sql, params
                except ValueError:
                    logger.warning(f"Invalid age value: {age}")
                    return "", {}

        # Parse gender - MORE ROBUST MATCHING
        gender_value = None

        # Check if term contains gender keywords
        if "male" in term_lower:
            gender_value = "male"
        elif "female" in term_lower:
            gender_value = "female"
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
            return sql, params

        # If no match, log warning
        logger.warning(f"Could not build demographic clause for term='{term}', details='{details}'")
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
