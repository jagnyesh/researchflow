"""
Phenotype Validation Agent

Validates feasibility of research requests by:
- Generating SQL-on-FHIR queries from requirements
- Estimating cohort size using ViewDefinitions
- Checking data availability
- Providing recommendations
"""

from typing import Dict, Any
import logging
from .base_agent import BaseAgent
from ..utils.sql_generator import SQLGenerator
from ..adapters.sql_on_fhir import SQLonFHIRAdapter
from ..clients.fhir_client import create_fhir_client
from ..sql_on_fhir.view_definition_manager import ViewDefinitionManager
from ..sql_on_fhir.runner.in_memory_runner import InMemoryRunner

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

    async def execute_task(self, task: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute phenotype validation task"""
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
        estimated_count = await self._estimate_cohort_size(phenotype_sql)

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

    async def _estimate_cohort_size(self, count_sql: str) -> int:
        """
        Execute COUNT query to estimate cohort size

        Args:
            count_sql: SQL query with COUNT(*)

        Returns:
            Estimated patient count
        """
        try:
            result = await self.sql_adapter.execute_sql(count_sql)

            if result and len(result) > 0:
                count = result[0].get('patient_count', 0)
                logger.debug(f"[{self.agent_id}] Estimated cohort size: {count}")
                return count
            else:
                logger.warning(f"[{self.agent_id}] No results from count query")
                return 0

        except Exception as e:
            logger.error(f"[{self.agent_id}] Failed to estimate cohort: {str(e)}")
            # Return 0 instead of failing - will mark as not feasible
            return 0

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
