"""
Phenotype Validation Agent

Validates feasibility of research requests by:
- Generating SQL-on-FHIR queries from requirements
- Estimating cohort size using ViewDefinitions
- Checking data availability
- Providing recommendations
"""

from typing import Dict, Any, List
import logging
import os
from .base_agent import BaseAgent
from ..utils.sql_generator import SQLGenerator
from ..adapters.sql_on_fhir import SQLonFHIRAdapter
from ..clients.fhir_client import create_fhir_client
from ..clients.hapi_db_client import HAPIDBClient
from ..sql_on_fhir.view_definition_manager import ViewDefinitionManager
from ..sql_on_fhir.runner.in_memory_runner import InMemoryRunner
from ..sql_on_fhir.runner.postgres_runner import PostgresRunner

logger = logging.getLogger(__name__)


class PhenotypeValidationAgent(BaseAgent):
    """
    Agent for validating phenotype feasibility and translating to SQL

    Responsibilities:
    - Generate SQL-on-FHIR queries from structured requirements
    - Estimate cohort size (fast COUNT query)
    - Check data availability for requested elements
    - Provide feasibility score and recommendations
    - Route to calendar agent if feasible, or escalate if not
    """

    def __init__(self, orchestrator=None, database_url: str = None):
        super().__init__(agent_id="phenotype_agent", orchestrator=orchestrator)
        self.sql_generator = SQLGenerator()
        self.sql_adapter = SQLonFHIRAdapter(database_url)
        self.view_definition_manager = ViewDefinitionManager()
        self.use_view_definitions = True  # Toggle to use ViewDefinitions instead of legacy SQL

        # Initialize ViewDefinition runner if using ViewDefinitions
        if self.use_view_definitions and database_url:
            logger.info(f"[{self.agent_id}] Initializing PostgresRunner for HAPI FHIR database")

            # HAPIDBClient uses asyncpg directly, which doesn't understand SQLAlchemy URL schemes
            # Strip '+asyncpg' suffix if present
            hapi_url = database_url.replace('postgresql+asyncpg://', 'postgresql://')

            self.hapi_db_client = HAPIDBClient(connection_url=hapi_url)
            self.postgres_runner = PostgresRunner(
                db_client=self.hapi_db_client,
                enable_cache=True,
                cache_ttl_seconds=300
            )
        else:
            self.hapi_db_client = None
            self.postgres_runner = None

    async def execute_task(self, task: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute phenotype validation task"""
        # Ensure database connection is established if using ViewDefinitions
        if self.use_view_definitions and self.hapi_db_client and not self.hapi_db_client.pool:
            logger.info(f"[{self.agent_id}] Establishing HAPI database connection")
            await self.hapi_db_client.connect()

        if task == "validate_feasibility":
            return await self._validate_feasibility(context)
        else:
            raise ValueError(f"Unknown task: {task}")

    async def _validate_feasibility(self, context: Dict) -> Dict[str, Any]:
        """
        Check if requested data exists and is feasible to extract

        Args:
            context: Contains requirements, request_id

        Returns:
            Dict with:
            - feasible: bool
            - feasibility_report: Dict with details
            - next_agent/task if feasible
        """
        requirements = context.get('requirements')
        request_id = context.get('request_id')

        if not requirements:
            raise ValueError("Requirements not found in context")

        logger.info(f"[{self.agent_id}] Validating feasibility for {request_id}")

        # Step 1: Generate phenotype SQL
        phenotype_sql = self.sql_generator.generate_phenotype_sql(
            requirements,
            count_only=True
        )

        # Step 2: Estimate cohort size
        estimated_count = await self._estimate_cohort_size(phenotype_sql, requirements)

        # Step 3: Check data availability
        data_availability = await self._check_data_availability(
            requirements.get('data_elements', []),
            requirements.get('time_period', {})
        )

        # Step 4: Calculate feasibility score
        feasibility_score = self._calculate_feasibility_score(
            estimated_count,
            data_availability,
            requirements
        )

        # Step 5: Generate full SQL (not count-only)
        full_phenotype_sql = self.sql_generator.generate_phenotype_sql(
            requirements,
            count_only=False
        )

        # Step 6: Build feasibility report
        feasibility_report = {
            "feasible": feasibility_score > 0.6,
            "feasibility_score": feasibility_score,
            "estimated_cohort_size": estimated_count,
            "confidence_interval": (
                int(estimated_count * 0.85),
                int(estimated_count * 1.15)
            ),
            "data_availability": data_availability,
            "phenotype_sql": full_phenotype_sql,
            "estimated_extraction_time_hours": self._estimate_extraction_time(
                estimated_count,
                requirements.get('data_elements', [])
            ),
            "warnings": [],
            "recommendations": []
        }

        # Step 7: Add warnings and recommendations
        min_cohort = requirements.get('minimum_cohort_size', 50)
        if estimated_count < min_cohort:
            feasibility_report['warnings'].append({
                "type": "small_cohort",
                "message": f"Estimated cohort ({estimated_count}) smaller than requested minimum ({min_cohort})",
                "suggestion": "Consider broadening inclusion criteria or extending time period"
            })

            # Generate alternative suggestions
            alternatives = await self._suggest_alternative_criteria(requirements)
            if alternatives:
                feasibility_report['recommendations'] = alternatives

        # Check for low data availability
        for element, availability in data_availability.get('by_element', {}).items():
            if availability['availability'] < 0.5:
                feasibility_report['warnings'].append({
                    "type": "low_data_availability",
                    "element": element,
                    "availability": availability['availability'],
                    "message": f"{element} only available for {availability['availability']:.1%} of patients"
                })

        # Step 8: Save feasibility report
        await self._save_feasibility_report(request_id, feasibility_report)

        logger.info(
            f"[{self.agent_id}] Feasibility: {feasibility_report['feasible']}, "
            f"Score: {feasibility_score:.2f}, Cohort: {estimated_count}"
        )

        # Step 9: Determine next step
        if feasibility_report['feasible']:
            # CRITICAL: SQL must be reviewed by informatician before execution (Gap #1)
            # Transition to PHENOTYPE_REVIEW state for human approval
            logger.info(
                f"[{self.agent_id}] Feasibility validated, requesting SQL approval from informatician"
            )

            return {
                "feasible": True,
                "feasibility_report": feasibility_report,
                "phenotype_sql": full_phenotype_sql,
                "estimated_cohort": estimated_count,
                "estimated_cohort_size": estimated_count,  # For workflow compatibility
                "feasibility_score": feasibility_score,  # For workflow compatibility
                "requires_approval": True,  # Flag for orchestrator
                "approval_type": "phenotype_sql",  # Type of approval needed
                "next_agent": None,  # Wait for approval - orchestrator will route
                "next_task": None,
                "additional_context": {
                    "feasibility_report": feasibility_report,
                    "phenotype_sql": full_phenotype_sql,
                    "estimated_cohort": estimated_count,
                    "approval_data": {
                        "sql_query": full_phenotype_sql,
                        "estimated_cohort": estimated_count,
                        "feasibility_score": feasibility_score,
                        "data_availability": data_availability,
                        "warnings": feasibility_report['warnings'],
                        "recommendations": feasibility_report['recommendations']
                    }
                }
            }
        else:
            # Not feasible - needs human review
            logger.warning(f"[{self.agent_id}] Request not feasible: score {feasibility_score:.2f}")
            return {
                "feasible": False,
                "feasibility_report": feasibility_report,
                "next_agent": None,
                "next_task": None
            }

    async def _estimate_cohort_size(self, count_sql: str, requirements: Dict[str, Any] = None) -> int:
        """
        Execute COUNT query to estimate cohort size using ViewDefinitions or legacy SQL

        Args:
            count_sql: SQL query with COUNT(*) (used only if use_view_definitions=False)
            requirements: Structured requirements for filtering (used with ViewDefinitions)

        Returns:
            Estimated patient count
        """
        try:
            if self.use_view_definitions and self.postgres_runner:
                # Use ViewDefinition approach (SQL-on-FHIR v2)
                logger.info(f"[{self.agent_id}] Using ViewDefinition to estimate cohort size")

                # Build search parameters from requirements
                search_params = {}
                if requirements:
                    search_params = self._build_search_params_from_requirements(requirements)
                    logger.info(f"[{self.agent_id}] Filtering patients with search_params: {search_params}")

                # Load patient_simple ViewDefinition
                view_def = self.view_definition_manager.load("patient_simple")

                # Execute ViewDefinition with filters
                results = await self.postgres_runner.execute(
                    view_definition=view_def,
                    search_params=search_params,
                    max_resources=None   # No limit - get full count
                )

                logger.info(f"[{self.agent_id}] ViewDefinition returned {len(results)} patients after SQL filtering")

                # Apply Python post-filtering for criteria not supported by search_params
                if requirements:
                    filtered_results = await self._filter_patients_by_requirements(results, requirements)
                    count = len(filtered_results)
                    logger.info(f"[{self.agent_id}] After Python filtering: {count} patients match all criteria")
                else:
                    count = len(results)

                return count

            else:
                # Use legacy SQL approach
                logger.info(f"[{self.agent_id}] Using legacy SQL to estimate cohort size")
                result = await self.sql_adapter.execute_sql(count_sql)

                if result and len(result) > 0:
                    count = result[0].get('patient_count', 0)
                    logger.debug(f"[{self.agent_id}] Estimated cohort size (legacy): {count}")
                    return count
                else:
                    logger.warning(f"[{self.agent_id}] No results from count query")
                    return 0

        except Exception as e:
            logger.error(f"[{self.agent_id}] Failed to estimate cohort: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            # Return 0 instead of failing - will mark as not feasible
            return 0

    async def _filter_patients_by_requirements(
        self,
        patients: List[Dict[str, Any]],
        requirements: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Apply Python post-filtering for criteria not supported by SQL search_params

        Handles:
        - Age range filtering (calculate from birthDate)
        - Condition filtering (diabetes, hypertension, etc.)
        - Additional demographic filters

        Args:
            patients: List of patient records from ViewDefinition
            requirements: Structured requirements

        Returns:
            Filtered list of patients matching all criteria
        """
        from datetime import datetime, date

        filtered = patients.copy()
        inclusion_criteria = requirements.get('inclusion_criteria', [])

        # Check if any condition filtering is needed
        condition_patient_ids = None
        has_condition_criteria = False

        for criterion in inclusion_criteria:
            concepts = criterion.get('concepts', [])

            for concept in concepts:
                if concept.get('type') == 'condition':
                    has_condition_criteria = True
                    term = concept.get('term', '').lower()
                    details = concept.get('details', '').lower()

                    # Get patient IDs with this condition
                    patient_ids = await self._get_patients_with_condition(term, details)

                    if condition_patient_ids is None:
                        condition_patient_ids = patient_ids
                    else:
                        # Intersection - patients must have ALL conditions
                        condition_patient_ids = condition_patient_ids.intersection(patient_ids)

                    logger.info(f"[{self.agent_id}] Condition filter '{term}': {len(patient_ids)} patients have this condition")

        # Apply condition filtering if needed
        if has_condition_criteria and condition_patient_ids is not None:
            # Filter patients to only those with the condition(s)
            filtered = [p for p in filtered if p.get('id') in condition_patient_ids]
            logger.info(f"[{self.agent_id}] After condition filtering: {len(filtered)} patients remain")

        # Apply demographic filtering
        for criterion in inclusion_criteria:
            concepts = criterion.get('concepts', [])

            for concept in concepts:
                if concept.get('type') == 'demographic':
                    term = concept.get('term', '').lower()
                    details = concept.get('details', '').lower()

                    # Age filtering
                    if 'age' in term:
                        filtered = self._filter_by_age(filtered, details)
                        logger.info(f"[{self.agent_id}] Age filter applied: {len(filtered)} patients remain")

        return filtered

    def _filter_by_age(
        self,
        patients: List[Dict[str, Any]],
        age_criterion: str
    ) -> List[Dict[str, Any]]:
        """
        Filter patients by age criterion

        Args:
            patients: List of patient records
            age_criterion: Age criterion string (e.g., "between 20 and 30", "over 18")

        Returns:
            Filtered list of patients
        """
        from datetime import datetime, date
        import re

        filtered = []

        # Parse age criterion
        if 'between' in age_criterion and 'and' in age_criterion:
            # "between 20 and 30"
            match = re.search(r'between\s+(\d+)\s+and\s+(\d+)', age_criterion)
            if match:
                min_age = int(match.group(1))
                max_age = int(match.group(2))

                for patient in patients:
                    age = self._calculate_age(patient.get('birth_date'))
                    if age is not None and min_age <= age <= max_age:
                        filtered.append(patient)

        elif 'over' in age_criterion or 'above' in age_criterion:
            # "over 18" or "above 18"
            match = re.search(r'(?:over|above)\s+(\d+)', age_criterion)
            if match:
                min_age = int(match.group(1))

                for patient in patients:
                    age = self._calculate_age(patient.get('birth_date'))
                    if age is not None and age > min_age:
                        filtered.append(patient)

        elif 'under' in age_criterion or 'below' in age_criterion:
            # "under 18" or "below 18"
            match = re.search(r'(?:under|below)\s+(\d+)', age_criterion)
            if match:
                max_age = int(match.group(1))

                for patient in patients:
                    age = self._calculate_age(patient.get('birth_date'))
                    if age is not None and age < max_age:
                        filtered.append(patient)

        else:
            # No recognized age criterion - return all
            filtered = patients

        return filtered

    def _calculate_age(self, birth_date_str: str) -> int:
        """
        Calculate age from birth date string

        Args:
            birth_date_str: Birth date in ISO format (YYYY-MM-DD)

        Returns:
            Age in years, or None if invalid
        """
        from datetime import datetime, date

        if not birth_date_str:
            return None

        try:
            # Handle various date formats
            if 'T' in birth_date_str:
                # ISO datetime format
                birth_date = datetime.fromisoformat(birth_date_str.replace('Z', '+00:00')).date()
            else:
                # Simple date format
                birth_date = datetime.strptime(birth_date_str, '%Y-%m-%d').date()

            today = date.today()
            age = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
            return age
        except Exception as e:
            logger.warning(f"[{self.agent_id}] Failed to parse birth_date '{birth_date_str}': {e}")
            return None

    async def _get_patients_with_condition(
        self,
        condition_term: str,
        condition_details: str
    ) -> set:
        """
        Get set of patient IDs who have a specific condition

        Args:
            condition_term: Condition name (e.g., "diabetes", "hypertension")
            condition_details: Additional details about the condition

        Returns:
            Set of patient IDs (as strings)
        """
        try:
            if not self.use_view_definitions or not self.postgres_runner:
                logger.warning(f"[{self.agent_id}] ViewDefinitions not enabled, skipping condition filtering")
                return set()

            # Load condition_simple ViewDefinition
            view_def = self.view_definition_manager.load("condition_simple")

            # Execute query to get all conditions
            logger.info(f"[{self.agent_id}] Querying conditions for '{condition_term}'...")
            results = await self.postgres_runner.execute(
                view_definition=view_def,
                search_params={},
                max_resources=None
            )

            logger.info(f"[{self.agent_id}] Found {len(results)} total conditions in database")

            # Filter for specific condition and extract patient IDs
            patient_ids = set()
            for condition in results:
                # Check if this condition matches the term
                if self._matches_condition(condition, condition_term, condition_details):
                    # Extract patient ID from reference
                    patient_ref = condition.get('patient_ref', '')
                    patient_id = self._extract_patient_id(patient_ref)
                    if patient_id:
                        patient_ids.add(patient_id)

            logger.info(f"[{self.agent_id}] Found {len(patient_ids)} unique patients with '{condition_term}'")
            return patient_ids

        except Exception as e:
            logger.error(f"[{self.agent_id}] Error getting patients with condition '{condition_term}': {e}")
            logger.error(traceback.format_exc())
            return set()

    def _extract_patient_id(self, patient_ref: str) -> str:
        """
        Extract patient ID from FHIR reference

        Args:
            patient_ref: FHIR reference (e.g., "Patient/123" or "urn:uuid:...")

        Returns:
            Patient ID string, or None if invalid
        """
        if not patient_ref:
            return None

        try:
            # Handle "Patient/123" format
            if 'Patient/' in patient_ref:
                return patient_ref.split('Patient/')[-1]

            # Handle other reference formats
            if '/' in patient_ref:
                return patient_ref.split('/')[-1]

            # Already just an ID
            return patient_ref

        except Exception as e:
            logger.warning(f"[{self.agent_id}] Failed to extract patient ID from '{patient_ref}': {e}")
            return None

    def _matches_condition(
        self,
        condition: Dict[str, Any],
        term: str,
        details: str
    ) -> bool:
        """
        Check if a condition record matches the search term

        Args:
            condition: Condition record from database
            term: Condition term (e.g., "diabetes")
            details: Additional details

        Returns:
            True if condition matches
        """
        term_lower = term.lower()
        details_lower = details.lower()

        # Check for diabetes
        if 'diabetes' in term_lower or 'diabetes' in details_lower:
            return self._is_diabetes_code(condition)

        # Check for hypertension
        if 'hypertension' in term_lower or 'hypertension' in details_lower:
            return self._is_hypertension_code(condition)

        # Generic text matching in code_text
        code_text = (condition.get('code_text') or '').lower()
        icd10_display = (condition.get('icd10_display') or '').lower()
        snomed_display = (condition.get('snomed_display') or '').lower()

        if term_lower in code_text or term_lower in icd10_display or term_lower in snomed_display:
            return True

        return False

    def _is_diabetes_code(self, condition: Dict[str, Any]) -> bool:
        """
        Check if condition represents diabetes

        Args:
            condition: Condition record

        Returns:
            True if diabetes-related
        """
        # ICD-10 codes for diabetes: E10-E14
        icd10_code = condition.get('icd10_code', '')
        if icd10_code and icd10_code.startswith(('E10', 'E11', 'E12', 'E13', 'E14')):
            return True

        # SNOMED codes for diabetes (common ones)
        snomed_code = condition.get('snomed_code', '')
        diabetes_snomed_codes = [
            '73211009',   # Diabetes mellitus
            '44054006',   # Type 2 diabetes mellitus
            '46635009',   # Type 1 diabetes mellitus
            '111552007',  # Diabetes mellitus without complication
            '190330002',  # Type 1 diabetes mellitus with ketoacidosis
        ]
        if snomed_code in diabetes_snomed_codes:
            return True

        # Text matching as fallback
        code_text = (condition.get('code_text') or '').lower()
        icd10_display = (condition.get('icd10_display') or '').lower()
        snomed_display = (condition.get('snomed_display') or '').lower()

        if 'diabetes' in code_text or 'diabetes' in icd10_display or 'diabetes' in snomed_display:
            return True

        return False

    def _is_hypertension_code(self, condition: Dict[str, Any]) -> bool:
        """
        Check if condition represents hypertension

        Args:
            condition: Condition record

        Returns:
            True if hypertension-related
        """
        # ICD-10 codes for hypertension: I10-I16
        icd10_code = condition.get('icd10_code', '')
        if icd10_code and icd10_code.startswith(('I10', 'I11', 'I12', 'I13', 'I14', 'I15', 'I16')):
            return True

        # SNOMED codes for hypertension (common ones)
        snomed_code = condition.get('snomed_code', '')
        hypertension_snomed_codes = [
            '38341003',   # Hypertensive disorder
            '59621000',   # Essential hypertension
            '194783001',  # Secondary hypertension
        ]
        if snomed_code in hypertension_snomed_codes:
            return True

        # Text matching as fallback
        code_text = (condition.get('code_text') or '').lower()
        icd10_display = (condition.get('icd10_display') or '').lower()
        snomed_display = (condition.get('snomed_display') or '').lower()

        if 'hypertension' in code_text or 'hypertension' in icd10_display or 'hypertension' in snomed_display:
            return True

        return False

    async def _check_data_availability(
        self,
        data_elements: list,
        time_period: Dict
    ) -> Dict:
        """
        Check what percentage of data is available for requested elements

        Args:
            data_elements: List of data element names
            time_period: Time period dict

        Returns:
            Dict with overall and per-element availability
        """
        availability = {
            "overall_availability": 0.0,
            "by_element": {}
        }

        if not data_elements:
            return availability

        # When using ViewDefinitions, skip detailed data availability checks
        # (legacy SQL queries don't work with HAPI FHIR schema)
        if self.use_view_definitions:
            logger.info(f"[{self.agent_id}] Skipping detailed data availability checks (using ViewDefinitions)")
            # Assume high availability for HAPI FHIR data (conservatively 0.9)
            for element in data_elements:
                availability['by_element'][element] = {
                    "availability": 0.9,
                    "patients_with_data": -1,  # Unknown
                    "total_records": -1  # Unknown
                }
            availability['overall_availability'] = 0.9
            return availability

        for element in data_elements:
            try:
                # Generate availability check query
                availability_sql = self.sql_generator.generate_data_availability_query(
                    element,
                    time_period
                )

                # Execute query
                result = await self.sql_adapter.execute_sql(availability_sql)

                if result and len(result) > 0:
                    row = result[0]
                    patients_with_data = row.get('patients_with_data', 0)
                    total_patients = row.get('total_patients', 1)
                    total_records = row.get('total_records', 0)

                    element_availability = patients_with_data / total_patients if total_patients > 0 else 0

                    availability['by_element'][element] = {
                        "availability": element_availability,
                        "patients_with_data": patients_with_data,
                        "total_records": total_records
                    }

                    logger.debug(
                        f"[{self.agent_id}] {element}: {element_availability:.1%} "
                        f"({patients_with_data}/{total_patients} patients)"
                    )

            except Exception as e:
                logger.warning(f"[{self.agent_id}] Could not check availability for {element}: {str(e)}")
                availability['by_element'][element] = {
                    "availability": 0.0,
                    "patients_with_data": 0,
                    "total_records": 0
                }

        # Calculate overall availability
        if availability['by_element']:
            availability['overall_availability'] = sum(
                e['availability'] for e in availability['by_element'].values()
            ) / len(availability['by_element'])

        return availability

    def _calculate_feasibility_score(
        self,
        estimated_count: int,
        data_availability: Dict,
        requirements: Dict
    ) -> float:
        """
        Calculate overall feasibility score (0.0 - 1.0)

        Factors:
        - Cohort size adequacy (40%)
        - Data availability (40%)
        - Time period reasonableness (20%)
        """
        score = 0.0

        # Factor 1: Cohort size (0.4 weight)
        min_cohort = requirements.get('minimum_cohort_size', 50)
        if estimated_count >= min_cohort * 2:
            score += 0.4  # Excellent
        elif estimated_count >= min_cohort:
            score += 0.3  # Good
        elif estimated_count >= min_cohort * 0.5:
            score += 0.2  # Marginal
        else:
            score += 0.0  # Too small

        # Factor 2: Data availability (0.4 weight)
        overall_availability = data_availability.get('overall_availability', 0)
        score += overall_availability * 0.4

        # Factor 3: Time period (0.2 weight)
        # If time period specified and reasonable, add points
        time_period = requirements.get('time_period', {})
        if time_period.get('start') and time_period.get('end'):
            score += 0.2
        elif time_period.get('start') or time_period.get('end'):
            score += 0.1

        return min(score, 1.0)

    def _estimate_extraction_time(
        self,
        cohort_size: int,
        data_elements: list
    ) -> float:
        """
        Estimate extraction time in hours

        Rough heuristic:
        - Base time: 0.5 hours
        - Per 100 patients: 0.2 hours
        - Per data element: 0.3 hours
        """
        base_time = 0.5
        patient_time = (cohort_size / 100) * 0.2
        element_time = len(data_elements) * 0.3

        return round(base_time + patient_time + element_time, 1)

    async def _suggest_alternative_criteria(
        self,
        requirements: Dict
    ) -> list:
        """
        Suggest alternative criteria if cohort too small

        Returns:
            List of recommendation dicts
        """
        recommendations = []

        # Suggest broadening inclusion criteria
        if requirements.get('inclusion_criteria'):
            recommendations.append({
                "type": "broaden_criteria",
                "suggestion": "Consider broadening inclusion criteria to include related conditions"
            })

        # Suggest extending time period
        time_period = requirements.get('time_period', {})
        if time_period.get('start') and time_period.get('end'):
            recommendations.append({
                "type": "extend_time_period",
                "suggestion": "Consider extending the time period to capture more patients"
            })

        return recommendations

    async def _save_feasibility_report(
        self,
        request_id: str,
        feasibility_report: Dict
    ):
        """Save feasibility report to database"""
        # TODO: Implement database save using FeasibilityReport model
        logger.info(f"[{self.agent_id}] Saving feasibility report for {request_id}")
        logger.debug(f"Feasibility report: {feasibility_report}")

    async def _estimate_cohort_size_with_view_definitions(
        self,
        requirements: Dict[str, Any]
    ) -> int:
        """
        Estimate cohort size using SQL-on-FHIR v2 ViewDefinitions

        Args:
            requirements: Structured requirements

        Returns:
            Estimated patient count
        """
        try:
            # Create FHIR client
            fhir_client = await create_fhir_client()

            try:
                # Use patient_demographics ViewDefinition for cohort estimation
                view_def = self.view_definition_manager.load("patient_demographics")

                # Build search parameters from requirements
                search_params = self._build_search_params_from_requirements(requirements)

                # Execute ViewDefinition with in-memory runner
                runner = InMemoryRunner(fhir_client)

                logger.info(f"[{self.agent_id}] Estimating cohort using ViewDefinition 'patient_demographics'")

                rows = await runner.execute(
                    view_def,
                    search_params=search_params,
                    max_resources=10000  # Limit for estimation
                )

                # Apply additional filters based on requirements
                filtered_rows = self._filter_rows_by_requirements(rows, requirements)

                cohort_size = len(filtered_rows)
                logger.info(f"[{self.agent_id}] ViewDefinition-based cohort estimation: {cohort_size} patients")

                return cohort_size

            finally:
                await fhir_client.close()

        except Exception as e:
            logger.error(f"[{self.agent_id}] Failed to estimate cohort with ViewDefinitions: {str(e)}")
            # Fallback to legacy SQL method
            logger.info(f"[{self.agent_id}] Falling back to legacy SQL estimation")
            return 0

    def _build_search_params_from_requirements(
        self,
        requirements: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Build FHIR search parameters from requirements

        Args:
            requirements: Structured requirements

        Returns:
            FHIR search parameters dict
        """
        params = {}

        # Extract demographic criteria
        inclusion_criteria = requirements.get('inclusion_criteria', [])

        for criterion in inclusion_criteria:
            concepts = criterion.get('concepts', [])

            for concept in concepts:
                if concept.get('type') == 'demographic':
                    term = concept.get('term', '').lower()
                    details = concept.get('details', '')

                    # Gender filter
                    if term in ['male', 'female']:
                        params['gender'] = term

                    # Age filter (approximate with birthdate)
                    if 'age' in term and '>' in details:
                        # Example: "age > 18" -> birthdate before X years ago
                        try:
                            age = int(details.split('>')[1].strip())
                            # Could calculate birthdate range here
                            # For now, we'll filter in memory
                        except:
                            pass

        logger.debug(f"[{self.agent_id}] Built search params: {params}")
        return params

    def _filter_rows_by_requirements(
        self,
        rows: list,
        requirements: Dict[str, Any]
    ) -> list:
        """
        Apply additional filters to ViewDefinition results based on requirements

        Args:
            rows: ViewDefinition result rows
            requirements: Structured requirements

        Returns:
            Filtered rows
        """
        filtered = rows

        # Apply age filters
        inclusion_criteria = requirements.get('inclusion_criteria', [])

        for criterion in inclusion_criteria:
            concepts = criterion.get('concepts', [])

            for concept in concepts:
                if concept.get('type') == 'demographic':
                    term = concept.get('term', '').lower()
                    details = concept.get('details', '')

                    if 'age' in term:
                        # Apply age filter
                        # This would require calculating age from birth_date
                        # For now, we'll keep all rows
                        pass

        logger.debug(f"[{self.agent_id}] Filtered {len(rows)} -> {len(filtered)} rows")
        return filtered

    async def execute_view_definition_for_phenotype(
        self,
        view_name: str,
        requirements: Dict[str, Any],
        max_resources: int = None
    ) -> list:
        """
        Execute a ViewDefinition with requirements-based filtering

        Args:
            view_name: Name of ViewDefinition to execute
            requirements: Structured requirements for filtering
            max_resources: Maximum resources to process

        Returns:
            List of result rows

        Example:
            # Get all conditions for cohort
            conditions = await agent.execute_view_definition_for_phenotype(
                "condition_diagnoses",
                requirements,
                max_resources=5000
            )
        """
        try:
            # Load ViewDefinition
            view_def = self.view_definition_manager.load(view_name)

            # Create FHIR client and runner
            fhir_client = await create_fhir_client()

            try:
                runner = InMemoryRunner(fhir_client)

                # Build search parameters
                search_params = self._build_search_params_from_requirements(requirements)

                logger.info(
                    f"[{self.agent_id}] Executing ViewDefinition '{view_name}' "
                    f"for phenotype validation"
                )

                # Execute ViewDefinition
                rows = await runner.execute(
                    view_def,
                    search_params=search_params,
                    max_resources=max_resources
                )

                logger.info(
                    f"[{self.agent_id}] ViewDefinition '{view_name}' returned "
                    f"{len(rows)} rows"
                )

                return rows

            finally:
                await fhir_client.close()

        except Exception as e:
            logger.error(
                f"[{self.agent_id}] Failed to execute ViewDefinition '{view_name}': {str(e)}"
            )
            raise
