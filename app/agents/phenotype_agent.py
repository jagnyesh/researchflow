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
from app.schemas._errors import log_internal_error
from langsmith import traceable
from .base_agent import BaseAgent
from ..utils.sql_generator import SQLGenerator
from ..adapters.sql_on_fhir import SQLonFHIRAdapter

logger = logging.getLogger(__name__)


class CohortEstimateUnavailable(Exception):
    """The cohort count could not be computed; `ref` points at the log line."""

    def __init__(self, ref: str):
        super().__init__(f"cohort estimate unavailable (ref: {ref})")
        self.ref = ref


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
        self.sql_generator = SQLGenerator(use_materialized_views=True)
        # The estimate counts the phenotype SQL itself on the batch tables
        # (#206): one cohort definition for the estimate, the G2 review and the
        # extraction. Replaced the HybridRunner FORMAL_DRAFT path (ADR 0033).
        self.sql_adapter = SQLonFHIRAdapter(database_url)

    @traceable(tags=["phenotype-agent", "agent-execution", "portal:formal"])
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
        requirements = context.get("requirements")
        request_id = context.get("request_id")

        if not requirements:
            raise ValueError("Requirements not found in context")

        logger.info(f"[{self.agent_id}] Validating feasibility for {request_id}")
        logger.info(
            f"[{self.agent_id}] Requirements structure being passed to SQL generator:"
            f"\n  Inclusion criteria count: {len(requirements.get('inclusion_criteria', []))}"
            f"\n  Exclusion criteria count: {len(requirements.get('exclusion_criteria', []))}"
            f"\n  Data elements: {requirements.get('data_elements', [])}"
        )
        logger.debug(f"[{self.agent_id}] Full requirements: {requirements}")

        # Step 1: Generate phenotype SQL (with parameters for security)
        phenotype_sql, sql_params = self.sql_generator.generate_phenotype_sql(
            requirements, count_only=True
        )
        logger.info(
            f"[{self.agent_id}] Generated SQL with {len(sql_params)} parameters: {list(sql_params.keys())}"
        )

        # Step 2: Estimate cohort size. A failed estimate stays None: an error
        # must never reach G2 as a count (ADR 0028 honest-failure invariant).
        estimate_error_ref = None
        try:
            estimated_count = await self._estimate_cohort_size(
                phenotype_sql, sql_params, requirements
            )
        except CohortEstimateUnavailable as unavailable:
            estimated_count = None
            estimate_error_ref = unavailable.ref

        # Step 3: Check data availability
        data_availability = await self._check_data_availability(
            requirements.get("data_elements", []), requirements.get("time_period", {})
        )

        # Step 4: Calculate feasibility score
        feasibility_score = (
            None
            if estimated_count is None
            else self._calculate_feasibility_score(estimated_count, data_availability, requirements)
        )

        # Step 5: Generate full SQL (not count-only) with parameters
        full_phenotype_sql, full_sql_params = self.sql_generator.generate_phenotype_sql(
            requirements, count_only=False
        )

        # Step 6: Build feasibility report
        estimated = estimated_count is not None
        feasibility_report = {
            "feasible": estimated and feasibility_score > 0.6,
            "feasibility_score": feasibility_score,
            "estimated_cohort_size": estimated_count,
            "cohort_estimate": (
                {"status": "ok"}
                if estimated
                else {"status": "unavailable", "error_ref": estimate_error_ref}
            ),
            "confidence_interval": (
                (int(estimated_count * 0.85), int(estimated_count * 1.15)) if estimated else None
            ),
            "data_availability": data_availability,
            "phenotype_sql": full_phenotype_sql,
            "estimated_extraction_time_hours": (
                self._estimate_extraction_time(
                    estimated_count, requirements.get("data_elements", [])
                )
                if estimated
                else None
            ),
            "warnings": [],
            "recommendations": [],
        }

        # Step 7: Add warnings and recommendations
        min_cohort = requirements.get("minimum_cohort_size", 50)
        if not estimated:
            feasibility_report["warnings"].append(
                {
                    "type": "cohort_estimate_unavailable",
                    "message": f"Cohort estimate unavailable: the count query failed (ref: {estimate_error_ref})",
                    "suggestion": "Review the SQL on its own; no cohort size is known",
                }
            )
        elif estimated_count < min_cohort:
            feasibility_report["warnings"].append(
                {
                    "type": "small_cohort",
                    "message": f"Estimated cohort ({estimated_count}) smaller than requested minimum ({min_cohort})",
                    "suggestion": "Consider broadening inclusion criteria or extending time period",
                }
            )

            # Generate alternative suggestions
            alternatives = await self._suggest_alternative_criteria(requirements)
            if alternatives:
                feasibility_report["recommendations"] = alternatives

        # Check for low data availability
        for element, availability in data_availability.get("by_element", {}).items():
            if availability["availability"] < 0.5:
                feasibility_report["warnings"].append(
                    {
                        "type": "low_data_availability",
                        "element": element,
                        "availability": availability["availability"],
                        "message": f"{element} only available for {availability['availability']:.1%} of patients",
                    }
                )

        # Step 8: Save feasibility report
        await self._save_feasibility_report(request_id, feasibility_report)

        logger.info(
            f"[{self.agent_id}] Feasibility: {feasibility_report['feasible']}, "
            f"Score: {feasibility_score}, Cohort: {estimated_count}"
        )

        # Step 9: Determine next step
        # CRITICAL: ALWAYS request informatician approval for SQL review (Gap #1)
        # The agent calculates feasibility metrics, but only the informatician decides
        # whether the SQL is appropriate to run, regardless of cohort size
        feasible = feasibility_report["feasible"]

        if not estimated:
            logger.warning(
                f"[{self.agent_id}] SQL generated without a cohort estimate "
                f"(ref={estimate_error_ref}), requesting informatician review"
            )
        elif feasible:
            logger.info(
                f"[{self.agent_id}] SQL generated with adequate cohort (score {feasibility_score:.2f}), "
                f"requesting informatician approval"
            )
        else:
            logger.warning(
                f"[{self.agent_id}] SQL generated with low cohort (score {feasibility_score:.2f}), "
                f"requesting informatician review"
            )

        return {
            "feasible": feasible,  # Include as informational metric
            "feasibility_report": feasibility_report,
            "phenotype_sql": full_phenotype_sql,
            "estimated_cohort": estimated_count,
            "estimated_cohort_size": estimated_count,  # For workflow compatibility
            "feasibility_score": feasibility_score,  # For workflow compatibility
            "requires_approval": True,  # ALWAYS require informatician approval
            "approval_type": "phenotype_sql",  # Type of approval needed
            "next_agent": None,  # Wait for approval - orchestrator will route
            "next_task": None,
            "additional_context": {
                "feasibility_report": feasibility_report,
                "phenotype_sql": full_phenotype_sql,
                "estimated_cohort": estimated_count,
                "approval_data": {
                    "sql_query": full_phenotype_sql,
                    "parameters": full_sql_params,  # Store SQL parameters for debugging/audit
                    "estimated_cohort": estimated_count,
                    "feasibility_score": feasibility_score,
                    "data_availability": data_availability,
                    "warnings": feasibility_report["warnings"],
                    "recommendations": feasibility_report["recommendations"],
                    "auto_feasibility_assessment": (
                        "unavailable"
                        if not estimated
                        else "feasible" if feasible else "not_feasible"
                    ),
                    # Include research request context for informatician review
                    "initial_request": context.get("initial_request", ""),
                    "structured_requirements": requirements,
                },
            },
        }

    async def _estimate_cohort_size(
        self, count_sql: str, sql_params: Dict[str, Any], requirements: Dict[str, Any] = None
    ) -> int:
        """Count the patients the phenotype SQL selects, on the batch tables.

        The same SQL and bound parameters the G2 reviewer approves, so the
        estimate can't disagree with the extraction (#206). A failure raises
        CohortEstimateUnavailable (#245), never a number.
        """
        try:
            result = await self.sql_adapter.execute_sql(count_sql, sql_params)
            if not result:
                raise LookupError("count query returned no rows")
            count = result[0]["patient_count"]
            logger.info(f"[{self.agent_id}] Estimated cohort size: {count} patients")
            return count
        except Exception as e:
            ref = log_internal_error(logger, f"[{self.agent_id}] Failed to estimate cohort", e)
            raise CohortEstimateUnavailable(ref) from e

    async def _check_data_availability(self, data_elements: list, time_period: Dict) -> Dict:
        """
        Check what percentage of data is available for requested elements

        Args:
            data_elements: List of data element names
            time_period: Time period dict

        Returns:
            Dict with overall and per-element availability
        """
        availability = {"overall_availability": 0.0, "by_element": {}}

        if not data_elements:
            return availability

        # When using ViewDefinitions OR materialized views, skip detailed data availability checks
        # (legacy SQL queries expect HAPI FHIR schema tables that don't exist)
        # Assume high availability for HAPI FHIR materialized views (conservatively 0.9)
        if self.sql_generator.use_materialized_views:
            logger.info(
                f"[{self.agent_id}] Skipping detailed data availability checks (using materialized views)"
            )
            # Assume high availability for HAPI FHIR data (conservatively 0.9)
            for element in data_elements:
                availability["by_element"][element] = {
                    "availability": 0.9,
                    "patients_with_data": -1,  # Unknown
                    "total_records": -1,  # Unknown
                }
            availability["overall_availability"] = 0.9
            return availability

        for element in data_elements:
            try:
                # Generate availability check query with parameters (security)
                availability_sql, availability_params = (
                    self.sql_generator.generate_data_availability_query(element, time_period)
                )

                # Execute parameterized query
                result = await self.sql_adapter.execute_sql(availability_sql, availability_params)

                if result and len(result) > 0:
                    row = result[0]
                    patients_with_data = row.get("patients_with_data", 0)
                    total_patients = row.get("total_patients", 1)
                    total_records = row.get("total_records", 0)

                    element_availability = (
                        patients_with_data / total_patients if total_patients > 0 else 0
                    )

                    availability["by_element"][element] = {
                        "availability": element_availability,
                        "patients_with_data": patients_with_data,
                        "total_records": total_records,
                    }

                    logger.debug(
                        f"[{self.agent_id}] {element}: {element_availability:.1%} "
                        f"({patients_with_data}/{total_patients} patients)"
                    )

            except Exception as e:
                log_internal_error(
                    logger,
                    f"[{self.agent_id}] Could not check availability for {element}",
                    e,
                    level=logging.WARNING,
                )
                availability["by_element"][element] = {
                    "availability": 0.0,
                    "patients_with_data": 0,
                    "total_records": 0,
                }

        # Calculate overall availability
        if availability["by_element"]:
            availability["overall_availability"] = sum(
                e["availability"] for e in availability["by_element"].values()
            ) / len(availability["by_element"])

        return availability

    def _calculate_feasibility_score(
        self, estimated_count: int, data_availability: Dict, requirements: Dict
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
        min_cohort = requirements.get("minimum_cohort_size", 50)
        if estimated_count >= min_cohort * 2:
            score += 0.4  # Excellent
        elif estimated_count >= min_cohort:
            score += 0.3  # Good
        elif estimated_count >= min_cohort * 0.5:
            score += 0.2  # Marginal
        else:
            score += 0.0  # Too small

        # Factor 2: Data availability (0.4 weight)
        overall_availability = data_availability.get("overall_availability", 0)
        score += overall_availability * 0.4

        # Factor 3: Time period (0.2 weight)
        # If time period specified and reasonable, add points
        time_period = requirements.get("time_period", {})
        if time_period.get("start") and time_period.get("end"):
            score += 0.2
        elif time_period.get("start") or time_period.get("end"):
            score += 0.1

        return min(score, 1.0)

    def _estimate_extraction_time(self, cohort_size: int, data_elements: list) -> float:
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

    async def _suggest_alternative_criteria(self, requirements: Dict) -> list:
        """
        Suggest alternative criteria if cohort too small

        Returns:
            List of recommendation dicts
        """
        recommendations = []

        # Suggest broadening inclusion criteria
        if requirements.get("inclusion_criteria"):
            recommendations.append(
                {
                    "type": "broaden_criteria",
                    "suggestion": "Consider broadening inclusion criteria to include related conditions",
                }
            )

        # Suggest extending time period
        time_period = requirements.get("time_period", {})
        if time_period.get("start") and time_period.get("end"):
            recommendations.append(
                {
                    "type": "extend_time_period",
                    "suggestion": "Consider extending the time period to capture more patients",
                }
            )

        return recommendations

    async def _save_feasibility_report(self, request_id: str, feasibility_report: Dict):
        """Save feasibility report to database"""
        logger.info(f"[{self.agent_id}] Saving feasibility report for {request_id}")
        logger.debug(f"Feasibility report: {feasibility_report}")

        from app.database import get_db_session, FeasibilityReport
        from sqlalchemy import select

        async with get_db_session() as session:
            # Check if report already exists
            result = await session.execute(
                select(FeasibilityReport).where(FeasibilityReport.request_id == request_id)
            )
            existing = result.scalar_one_or_none()

            # feasibility_score is NOT NULL; an unavailable estimate (#245) is
            # marked by the NULL cohort, not by this placeholder.
            score = feasibility_report.get("feasibility_score") or 0.0

            # Extract confidence interval
            confidence_interval = feasibility_report.get("confidence_interval") or []
            conf_low = confidence_interval[0] if len(confidence_interval) > 0 else None
            conf_high = confidence_interval[1] if len(confidence_interval) > 1 else None

            # Extract data availability
            data_avail = feasibility_report.get("data_availability", {})
            overall_avail = (
                data_avail.get("overall_availability", 0.0) if isinstance(data_avail, dict) else 0.0
            )

            if existing:
                # Update existing record
                existing.is_feasible = feasibility_report.get("feasible", False)
                existing.feasibility_score = score
                existing.estimated_cohort_size = feasibility_report.get("estimated_cohort_size")
                existing.confidence_interval_low = conf_low
                existing.confidence_interval_high = conf_high
                existing.phenotype_sql = feasibility_report.get("phenotype_sql", "")
                existing.data_availability = data_avail
                existing.overall_availability = overall_avail
                existing.warnings = feasibility_report.get("warnings", [])
                existing.recommendations = feasibility_report.get("recommendations", [])
                logger.info(
                    f"[{self.agent_id}] Updated existing feasibility report for {request_id}"
                )
            else:
                # Create new record
                feasibility = FeasibilityReport(
                    request_id=request_id,
                    is_feasible=feasibility_report.get("feasible", False),
                    feasibility_score=score,
                    estimated_cohort_size=feasibility_report.get("estimated_cohort_size"),
                    confidence_interval_low=conf_low,
                    confidence_interval_high=conf_high,
                    phenotype_sql=feasibility_report.get("phenotype_sql", ""),
                    data_availability=data_avail,
                    overall_availability=overall_avail,
                    warnings=feasibility_report.get("warnings", []),
                    recommendations=feasibility_report.get("recommendations", []),
                )
                session.add(feasibility)
                logger.info(f"[{self.agent_id}] Created new feasibility report for {request_id}")

            await session.commit()
            logger.info(
                f"[{self.agent_id}] Successfully saved feasibility report to database for {request_id}"
            )
