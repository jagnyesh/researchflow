"""
Feasibility Service

Executes fast COUNT queries using SQL-on-FHIR v2 to estimate cohort sizes
without exposing actual patient data.

Uses:
- SQL-on-FHIR in-memory runner for speed
- COUNT queries only (no PHI exposure)
- Data availability calculations
- Feasibility scoring
"""

from typing import Dict, Any, List, Optional
import logging
import httpx
from datetime import datetime

logger = logging.getLogger(__name__)


class FeasibilityService:
    """Service for executing feasibility checks using SQL-on-FHIR"""

    def __init__(self, api_base_url: str = "http://localhost:8000"):
        self.api_base_url = api_base_url
        self.client = httpx.AsyncClient(timeout=30.0)

    async def execute_feasibility_check(
        self,
        query_intent: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute feasibility check for research query

        Args:
            query_intent: Dictionary with:
                - view_definitions: List of ViewDefinition names
                - search_params: Filter parameters
                - data_elements: Requested data elements
                - time_period: Time range

        Returns:
            Dictionary with feasibility results:
                - estimated_cohort: Patient count
                - data_availability: Completeness by element
                - feasibility_score: 0.0-1.0
                - warnings: List of concerns
                - recommendations: List of suggestions
        """
        try:
            # Execute COUNT query for each ViewDefinition
            cohort_counts = {}

            for view_name in query_intent.get('view_definitions', []):
                try:
                    count = await self._execute_count_query(
                        view_name=view_name,
                        search_params=query_intent.get('search_params', {})
                    )
                    cohort_counts[view_name] = count
                except Exception as e:
                    logger.warning(f"Failed to count {view_name}: {e}")
                    cohort_counts[view_name] = 0

            # Calculate estimated cohort (use primary ViewDefinition, usually demographics)
            estimated_cohort = cohort_counts.get('patient_demographics', 0)
            if estimated_cohort == 0 and cohort_counts:
                # Fall back to first ViewDefinition with non-zero count
                estimated_cohort = next((v for v in cohort_counts.values() if v > 0), 0)

            # Calculate data availability
            data_availability = await self._calculate_data_availability(
                query_intent.get('data_elements', []),
                estimated_cohort
            )

            # Generate warnings
            warnings = self._generate_warnings(
                estimated_cohort,
                data_availability,
                query_intent
            )

            # Generate recommendations
            recommendations = self._generate_recommendations(
                estimated_cohort,
                data_availability,
                query_intent
            )

            # Calculate feasibility score
            feasibility_score = self._calculate_feasibility_score(
                estimated_cohort,
                data_availability
            )

            return {
                "estimated_cohort": estimated_cohort,
                "cohort_counts_by_view": cohort_counts,
                "data_availability": data_availability,
                "feasibility_score": feasibility_score,
                "warnings": warnings,
                "recommendations": recommendations,
                "time_period": query_intent.get('time_period', {}),
                "executed_at": datetime.now().isoformat()
            }

        except Exception as e:
            logger.error(f"Feasibility check failed: {e}")
            raise

    async def _execute_count_query(
        self,
        view_name: str,
        search_params: Dict[str, Any]
    ) -> int:
        """
        Execute COUNT query for a ViewDefinition

        Args:
            view_name: ViewDefinition name
            search_params: FHIR search parameters

        Returns:
            Count of matching resources
        """
        try:
            # Call analytics API to execute ViewDefinition
            # We request max_resources=1 to minimize data transfer
            # The API will still return the full count
            response = await self.client.post(
                f"{self.api_base_url}/analytics/execute",
                json={
                    "view_name": view_name,
                    "search_params": search_params,
                    "max_resources": 1  # Minimal data transfer
                }
            )
            response.raise_for_status()

            result = response.json()
            return result.get("row_count", 0)

        except httpx.HTTPError as e:
            logger.error(f"HTTP error executing count query for {view_name}: {e}")
            return 0
        except Exception as e:
            logger.error(f"Error executing count query for {view_name}: {e}")
            return 0

    async def _calculate_data_availability(
        self,
        data_elements: List[str],
        cohort_size: int
    ) -> Dict[str, Any]:
        """
        Calculate data availability for requested elements

        Args:
            data_elements: List of requested data elements
            cohort_size: Estimated cohort size

        Returns:
            Dictionary with availability scores
        """
        # Map data elements to ViewDefinitions
        element_to_view = {
            "demographics": "patient_demographics",
            "conditions": "condition_diagnoses",
            "medications": "medication_requests",
            "labs": "observation_labs",
            "procedures": "procedure_history"
        }

        availability_by_element = {}

        for element in data_elements:
            view_name = element_to_view.get(element)
            if not view_name:
                # Unknown data element
                availability_by_element[element] = 0.0
                continue

            try:
                # Count how many patients have this data element
                count = await self._execute_count_query(
                    view_name=view_name,
                    search_params={}
                )

                # Calculate availability as percentage
                availability = min(count / cohort_size, 1.0) if cohort_size > 0 else 0.0
                availability_by_element[element] = availability

            except Exception as e:
                logger.warning(f"Failed to calculate availability for {element}: {e}")
                availability_by_element[element] = 0.0

        # Calculate overall availability
        overall_availability = sum(availability_by_element.values()) / len(availability_by_element) if availability_by_element else 0.0

        return {
            "overall_availability": overall_availability,
            "by_element": availability_by_element
        }

    def _generate_warnings(
        self,
        cohort_size: int,
        data_availability: Dict[str, Any],
        query_intent: Dict[str, Any]
    ) -> List[Dict[str, str]]:
        """Generate warnings based on feasibility results"""
        warnings = []

        # Warn if cohort is too small
        if cohort_size < 10:
            warnings.append({
                "type": "small_cohort",
                "message": f"Small cohort size ({cohort_size} patients) may not provide sufficient statistical power"
            })

        # Warn if cohort is very large
        if cohort_size > 10000:
            warnings.append({
                "type": "large_cohort",
                "message": f"Large cohort size ({cohort_size} patients) may require extended processing time"
            })

        # Warn about low data availability
        for element, availability in data_availability.get("by_element", {}).items():
            if availability < 0.5:
                warnings.append({
                    "type": "data_availability",
                    "message": f"{element.title()} data availability is {availability:.0%}, many patients may have incomplete records"
                })

        return warnings

    def _generate_recommendations(
        self,
        cohort_size: int,
        data_availability: Dict[str, Any],
        query_intent: Dict[str, Any]
    ) -> List[str]:
        """Generate recommendations to improve feasibility"""
        recommendations = []

        # Recommend time period extension if cohort is small
        if cohort_size < 100:
            recommendations.append(
                "Consider extending the time period to increase cohort size"
            )

        # Recommend relaxing criteria if cohort is very small
        if cohort_size < 50:
            recommendations.append(
                "Consider relaxing inclusion criteria to capture more patients"
            )

        # Recommend excluding data elements with low availability
        for element, availability in data_availability.get("by_element", {}).items():
            if availability < 0.3:
                recommendations.append(
                    f"Consider excluding {element} (only {availability:.0%} available) or use alternative data source"
                )

        # Recommend reviewing with informatician for large extractions
        if cohort_size > 5000:
            recommendations.append(
                "Large extraction - recommend discussing scope with informatician before submission"
            )

        return recommendations

    def _calculate_feasibility_score(
        self,
        cohort_size: int,
        data_availability: Dict[str, Any]
    ) -> float:
        """
        Calculate overall feasibility score (0.0-1.0)

        Factors:
        - Cohort size (optimal: 100-5000 patients)
        - Data availability (optimal: >90%)
        """
        # Score cohort size (bell curve with peak at 500)
        if cohort_size == 0:
            size_score = 0.0
        elif cohort_size < 10:
            size_score = cohort_size / 10 * 0.3  # 0-30%
        elif cohort_size < 100:
            size_score = 0.3 + (cohort_size - 10) / 90 * 0.4  # 30-70%
        elif cohort_size < 5000:
            size_score = 0.7 + (cohort_size - 100) / 4900 * 0.3  # 70-100%
        else:
            # Slightly penalize very large cohorts (processing time)
            size_score = max(0.8, 1.0 - (cohort_size - 5000) / 50000 * 0.2)

        # Score data availability
        availability_score = data_availability.get("overall_availability", 0.0)

        # Combined score (weighted average: 60% size, 40% availability)
        feasibility_score = (size_score * 0.6) + (availability_score * 0.4)

        return min(feasibility_score, 1.0)

    async def close(self):
        """Close HTTP client"""
        await self.client.aclose()
