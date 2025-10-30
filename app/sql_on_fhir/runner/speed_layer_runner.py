"""Speed layer runner for querying Redis-cached FHIR data."""
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
import logging

from app.cache.redis_client import RedisClient

logger = logging.getLogger(__name__)


class SpeedLayerRunner:
    """
    Query recent FHIR data from Redis cache.

    This runner queries the speed layer (Redis) for FHIR resources
    added/updated in the last 24 hours that haven't been materialized yet.
    """

    def __init__(self, redis_client: RedisClient):
        self.redis_client = redis_client

    async def execute(
        self,
        view_definition: Dict[str, Any],
        search_params: Optional[Dict[str, str]] = None,
        max_resources: int = 1000,
        since: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Execute query against speed layer (Redis cache).

        Args:
            view_definition: SQL-on-FHIR ViewDefinition
            search_params: Search parameters (gender, code, etc.)
            max_resources: Maximum results to return
            since: Only include resources cached after this time

        Returns:
            Query results with patient IDs and metadata
        """
        view_name = view_definition.get("name", "unknown")
        resource_type = self._get_resource_type(view_definition)

        logger.info(f"[SpeedLayerRunner] Querying Redis for {resource_type} (view: {view_name})")

        # Default to last 24 hours if not specified
        if not since:
            since = datetime.utcnow() - timedelta(hours=24)

        # Scan Redis for recent resources
        resources = await self.redis_client.scan_recent_resources(
            resource_type=resource_type,
            since=since
        )

        logger.info(f"[SpeedLayerRunner] Found {len(resources)} recent {resource_type} resources in Redis")

        # Apply search parameter filters
        if search_params:
            resources = self._apply_filters(resources, search_params, view_definition)

        # Limit results
        resources = resources[:max_resources]

        # Extract patient IDs
        patient_ids = self._extract_patient_ids(resources, view_definition)

        return {
            "view_name": view_name,
            "source": "speed_layer",
            "total_count": len(patient_ids),
            "patient_ids": list(patient_ids),
            "resources": resources,
            "query_timestamp": datetime.utcnow().isoformat(),
            "since": since.isoformat() if since else None
        }

    def _get_resource_type(self, view_definition: Dict[str, Any]) -> str:
        """Extract FHIR resource type from ViewDefinition."""
        # Try top-level 'resource' field first (standard SQL-on-FHIR)
        if "resource" in view_definition:
            return view_definition["resource"]

        # Fall back to select[0].from field
        select = view_definition.get("select", [])
        if select and len(select) > 0:
            from_clause = select[0].get("from", "")
            # Extract resource type (e.g., "Patient" from "Patient")
            if from_clause:
                return from_clause.split(".")[0] if "." in from_clause else from_clause

        return "Patient"  # default

    def _apply_filters(
        self,
        resources: List[Dict[str, Any]],
        search_params: Dict[str, str],
        view_definition: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Apply search parameter filters to resources."""
        filtered = resources

        # Gender filter (for Patient resources)
        if "gender" in search_params:
            gender = search_params["gender"].lower()
            filtered = [
                r for r in filtered
                if r.get("gender", "").lower() == gender
            ]

        # Code filter (for Condition/Observation resources)
        if "code" in search_params:
            code_value = search_params["code"]
            filtered = [
                r for r in filtered
                if self._matches_code(r, code_value)
            ]

        return filtered

    def _matches_code(self, resource: Dict[str, Any], code_value: str) -> bool:
        """Check if resource matches a code value."""
        code = resource.get("code", {})

        # Check coding array
        codings = code.get("coding", [])
        for coding in codings:
            if coding.get("code") == code_value:
                return True

        # Check text
        if code_value.lower() in code.get("text", "").lower():
            return True

        return False

    def _extract_patient_ids(
        self,
        resources: List[Dict[str, Any]],
        view_definition: Dict[str, Any]
    ) -> set:
        """Extract patient IDs from resources."""
        patient_ids = set()

        for resource in resources:
            resource_type = resource.get("resourceType", "")

            if resource_type == "Patient":
                # Patient resource: use ID directly
                patient_ids.add(resource.get("id"))
            else:
                # Other resources: extract from subject reference
                subject = resource.get("subject", {})
                reference = subject.get("reference", "")
                # Extract "12345" from "Patient/12345"
                if reference.startswith("Patient/"):
                    patient_id = reference.split("/")[1]
                    patient_ids.add(patient_id)

        return patient_ids
