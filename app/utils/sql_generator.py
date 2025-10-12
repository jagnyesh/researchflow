"""
SQL Generator for Phenotype Definitions

Converts structured requirements to SQL-on-FHIR queries.
"""

from typing import Dict, Any, List
import logging

logger = logging.getLogger(__name__)


class SQLGenerator:
    """
    Generate SQL queries from structured phenotype requirements
    """

    def generate_phenotype_sql(
        self,
        requirements: Dict[str, Any],
        count_only: bool = False
    ) -> str:
        """
        Generate SQL-on-FHIR query from requirements

        Args:
            requirements: Structured requirements dict
            count_only: If True, generate COUNT query for estimation

        Returns:
            SQL query string
        """
        inclusion = requirements.get('inclusion_criteria', [])
        exclusion = requirements.get('exclusion_criteria', [])
        time_period = requirements.get('time_period', {})

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
            inclusion_conditions = self._build_criteria_conditions(
                inclusion,
                include=True
            )
            if inclusion_conditions:
                where_clauses.extend(inclusion_conditions)

        # Add exclusion criteria
        if exclusion:
            exclusion_conditions = self._build_criteria_conditions(
                exclusion,
                include=False
            )
            if exclusion_conditions:
                where_clauses.extend(exclusion_conditions)

        # Add time period filter if specified
        if time_period.get('start') or time_period.get('end'):
            time_conditions = self._build_time_conditions(time_period)
            if time_conditions:
                where_clauses.extend(time_conditions)

        # Construct final query
        where_clause = ""
        if where_clauses:
            where_clause = "WHERE " + " AND ".join(where_clauses)

        sql = f"{select_clause}\n{from_clause}\n{where_clause}"

        logger.debug(f"Generated SQL:\n{sql}")
        return sql

    def _build_criteria_conditions(
        self,
        criteria: List[Dict],
        include: bool = True
    ) -> List[str]:
        """
        Build SQL conditions from criteria

        Args:
            criteria: List of criterion dicts
            include: True for inclusion, False for exclusion

        Returns:
            List of SQL condition strings
        """
        conditions = []

        for criterion in criteria:
            concepts = criterion.get('concepts', [])

            for concept in concepts:
                concept_type = concept.get('type')
                term = concept.get('term')

                if concept_type == 'condition':
                    # Build condition query
                    condition = self._build_condition_clause(
                        term,
                        include
                    )
                    if condition:
                        conditions.append(condition)

                elif concept_type == 'demographic':
                    # Build demographic query
                    condition = self._build_demographic_clause(
                        term,
                        concept.get('details', '')
                    )
                    if condition:
                        conditions.append(condition)

                elif concept_type == 'lab':
                    # Build lab value query
                    condition = self._build_lab_clause(term, include)
                    if condition:
                        conditions.append(condition)

        return conditions

    def _build_condition_clause(
        self,
        condition_term: str,
        include: bool
    ) -> str:
        """Build SQL for condition/diagnosis criterion"""
        # Simplified: In production, would use ICD-10/SNOMED codes
        operator = "EXISTS" if include else "NOT EXISTS"

        return f"""{operator} (
        SELECT 1 FROM condition c
        WHERE c.patient_id = p.id
        AND LOWER(c.code_display) LIKE LOWER('%{condition_term}%')
    )"""

    def _build_demographic_clause(
        self,
        term: str,
        details: str
    ) -> str:
        """Build SQL for demographic criterion"""
        # Parse age criteria
        if 'age' in term.lower():
            if '>' in details:
                age = details.split('>')[1].strip()
                return f"EXTRACT(YEAR FROM AGE(CURRENT_DATE, p.birthDate)) > {age}"
            elif '<' in details:
                age = details.split('<')[1].strip()
                return f"EXTRACT(YEAR FROM AGE(CURRENT_DATE, p.birthDate)) < {age}"

        # Parse gender
        if 'gender' in term.lower() or term.lower() in ['male', 'female']:
            gender = term.lower()
            if gender in ['male', 'female']:
                return f"p.gender = '{gender}'"

        return ""

    def _build_lab_clause(self, lab_term: str, include: bool) -> str:
        """Build SQL for lab value criterion"""
        operator = "EXISTS" if include else "NOT EXISTS"

        return f"""{operator} (
        SELECT 1 FROM observation o
        WHERE o.patient_id = p.id
        AND LOWER(o.code_display) LIKE LOWER('%{lab_term}%')
    )"""

    def _build_time_conditions(self, time_period: Dict) -> List[str]:
        """Build time period filter conditions"""
        conditions = []

        if time_period.get('start'):
            conditions.append(
                f"p.lastUpdated >= '{time_period['start']}'"
            )

        if time_period.get('end'):
            conditions.append(
                f"p.lastUpdated <= '{time_period['end']}'"
            )

        return conditions

    def generate_data_availability_query(
        self,
        data_element: str,
        time_period: Dict
    ) -> str:
        """
        Generate query to check data availability

        Args:
            data_element: Type of data (e.g., 'clinical_notes', 'lab_results')
            time_period: Time period dict

        Returns:
            SQL query to check availability
        """
        if data_element == 'clinical_notes':
            table = 'document_reference'
            date_field = 'date'
        elif data_element == 'lab_results':
            table = 'observation'
            date_field = 'effectiveDateTime'
        elif data_element == 'medications':
            table = 'medication_request'
            date_field = 'authoredOn'
        else:
            table = 'observation'
            date_field = 'effectiveDateTime'

        time_filter = ""
        if time_period.get('start') and time_period.get('end'):
            time_filter = f"""
            AND {date_field} BETWEEN '{time_period['start']}'
                AND '{time_period['end']}'"""

        sql = f"""
SELECT
    COUNT(DISTINCT patient_id) as patients_with_data,
    (SELECT COUNT(DISTINCT id) FROM patient) as total_patients,
    COUNT(*) as total_records
FROM {table}
WHERE 1=1{time_filter}"""

        return sql
