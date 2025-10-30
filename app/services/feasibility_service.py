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

from app.sql_on_fhir.join_query_builder import JoinQueryBuilder
from app.clients.hapi_db_client import HAPIDBClient
import os

logger = logging.getLogger(__name__)


class FeasibilityService:
    """Service for executing feasibility checks using SQL-on-FHIR"""

    def __init__(self, api_base_url: str = "http://localhost:8000"):
        self.api_base_url = api_base_url
        self.client = httpx.AsyncClient(timeout=30.0)
        self.join_query_builder = JoinQueryBuilder()
        # Initialize direct database client for JOIN queries
        hapi_db_url = os.getenv("HAPI_DB_URL", "postgresql://hapi:hapi@localhost:5433/hapi")
        self.db_client = HAPIDBClient(hapi_db_url)

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
            # Detect if this is a multi-view query (e.g., demographics + conditions)
            view_definitions = query_intent.get('view_definitions', [])
            post_filters = query_intent.get('post_filters', [])
            search_params = query_intent.get('search_params', {})

            # Use JOIN query if:
            # 1. Multiple views specified, OR
            # 2. Single view with post_filters (need JOIN to apply condition filters)
            use_join_query = len(view_definitions) > 1 or (post_filters and len(post_filters) > 0)

            if use_join_query:
                # Multi-view query - use JOIN
                logger.info(f"Using JOIN query for views: {view_definitions}")
                query_result = self.join_query_builder.build_multi_view_count_query(
                    view_definitions=view_definitions,
                    search_params=search_params,
                    post_filters=post_filters
                )

                # Execute JOIN query
                try:
                    start_time = datetime.now()
                    result = await self.db_client.execute_query(query_result['sql'])
                    execution_time_ms = (datetime.now() - start_time).total_seconds() * 1000

                    estimated_cohort = result[0]['count'] if result else 0
                    cohort_counts = {
                        query_result['primary_view']: estimated_cohort
                    }

                    # Store SQL visibility info
                    generated_sql = query_result['sql']
                    filter_summary = query_result['filter_summary']

                    logger.info(f"JOIN query returned {estimated_cohort} patients ({execution_time_ms:.1f}ms)")

                except Exception as e:
                    logger.error(f"JOIN query failed: {e}")
                    logger.debug(f"SQL: {query_result['sql']}")
                    estimated_cohort = 0
                    cohort_counts = {}
                    generated_sql = query_result['sql']
                    filter_summary = str(e)
                    execution_time_ms = 0

            else:
                # Single-view query - use existing API approach
                logger.info(f"Using single-view query for: {view_definitions}")
                cohort_counts = {}
                demographic_views = ['patient_demographics', 'patient_simple']

                for view_name in view_definitions:
                    try:
                        # Only pass demographic search_params to demographic views
                        if view_name in demographic_views:
                            view_search_params = search_params
                        else:
                            view_search_params = {}

                        count = await self._execute_count_query(
                            view_name=view_name,
                            search_params=view_search_params
                        )
                        cohort_counts[view_name] = count
                    except Exception as e:
                        logger.warning(f"Failed to count {view_name}: {e}")
                        cohort_counts[view_name] = 0

                # Calculate estimated cohort
                estimated_cohort = cohort_counts.get('patient_demographics', 0)
                if estimated_cohort == 0 and cohort_counts:
                    estimated_cohort = next((v for v in cohort_counts.values() if v > 0), 0)

                # Generate simple SQL for visibility
                generated_sql = f"SELECT COUNT(*) FROM sqlonfhir.{view_definitions[0]}" if view_definitions else ""
                filter_summary = f"Gender: {search_params.get('gender', 'any')}"
                execution_time_ms = 0

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
                "executed_at": datetime.now().isoformat(),
                # SQL visibility fields
                "generated_sql": generated_sql,
                "filter_summary": filter_summary,
                "execution_time_ms": execution_time_ms,
                "used_join_query": use_join_query
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
        """Close HTTP client and database client"""
        await self.client.aclose()
        await self.db_client.close()
