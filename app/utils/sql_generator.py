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

    def __init__(self):
        """Initialize SQL generator with parameter counter"""
        self._param_counter = 0

    def _get_param_name(self, prefix: str = "p") -> str:
        """Generate unique parameter name"""
        self._param_counter += 1
        return f"{prefix}_{self._param_counter}"

    def _reset_param_counter(self):
        """Reset parameter counter for new query"""
        self._param_counter = 0

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

        # Build base patient query
        if count_only:
            select_clause = "SELECT COUNT(DISTINCT p.id) as patient_count"
        else:
            select_clause = """SELECT DISTINCT
    p.id as patient_id,
    p.birthDate,
    p.gender"""

        from_clause = "FROM patient p"
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

        for criterion in criteria:
            concepts = criterion.get("concepts", [])

            for concept in concepts:
                concept_type = concept.get("type")
                term = concept.get("term")

                if concept_type == "condition":
                    # Build condition query
                    condition, condition_params = self._build_condition_clause(term, include)
                    if condition:
                        conditions.append(condition)
                        params.update(condition_params)

                elif concept_type == "demographic":
                    # Build demographic query
                    condition, demo_params = self._build_demographic_clause(
                        term, concept.get("details", "")
                    )
                    if condition:
                        conditions.append(condition)
                        params.update(demo_params)

                elif concept_type == "lab":
                    # Build lab value query
                    condition, lab_params = self._build_lab_clause(term, include)
                    if condition:
                        conditions.append(condition)
                        params.update(lab_params)

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

        sql = f"""{operator} (  # nosec B608
        SELECT 1 FROM condition c
        WHERE c.patient_id = p.id
        AND LOWER(c.code_display) LIKE LOWER(:{param_name})
    )"""

        return sql, params

    def _build_demographic_clause(self, term: str, details: str) -> Tuple[str, Dict[str, Any]]:
        """
        Build SQL for demographic criterion

        Returns:
            Tuple of (SQL condition string, parameters dict)
        """
        # Parse age criteria
        if "age" in term.lower():
            if ">" in details:
                age = details.split(">")[1].strip()
                param_name = self._get_param_name("age")
                try:
                    age_value = int(age)
                    params = {param_name: age_value}
                    sql = f"EXTRACT(YEAR FROM AGE(CURRENT_DATE, p.birthDate)) > :{param_name}"
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
                    sql = f"EXTRACT(YEAR FROM AGE(CURRENT_DATE, p.birthDate)) < :{param_name}"
                    return sql, params
                except ValueError:
                    logger.warning(f"Invalid age value: {age}")
                    return "", {}

        # Parse gender
        if "gender" in term.lower() or term.lower() in ["male", "female"]:
            gender = term.lower()
            if gender in ["male", "female"]:
                param_name = self._get_param_name("gender")
                params = {param_name: gender}
                sql = f"p.gender = :{param_name}"
                return sql, params

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

        sql = f"""{operator} (  # nosec B608
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
        sql = f"""  # nosec B608
SELECT
    COUNT(DISTINCT patient_id) as patients_with_data,
    (SELECT COUNT(DISTINCT id) FROM patient) as total_patients,
    COUNT(*) as total_records
FROM {table}
WHERE 1=1{time_filter}"""

        return sql, params
