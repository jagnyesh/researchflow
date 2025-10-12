"""
FHIR Client for communicating with FHIR servers

Provides HTTP client functionality for:
- Searching FHIR resources
- Reading individual resources
- Batch operations
- Connection pooling and retry logic
"""

import os
import logging
from typing import Dict, List, Any, Optional
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


class FHIRClient:
    """
    HTTP client for FHIR server communication

    Supports:
    - RESTful FHIR operations (search, read, create, update, delete)
    - Connection pooling
    - Automatic retry with exponential backoff
    - Pagination handling
    - Batch/transaction bundles
    """

    def __init__(self, base_url: Optional[str] = None):
        """
        Initialize FHIR client

        Args:
            base_url: FHIR server base URL (e.g., http://localhost:8081/fhir)
                     If not provided, uses FHIR_SERVER_URL environment variable
        """
        self.base_url = base_url or os.getenv(
            "FHIR_SERVER_URL",
            "http://localhost:8081/fhir"
        )

        # Remove trailing slash if present
        self.base_url = self.base_url.rstrip('/')

        # Initialize HTTP client with connection pooling
        self.client = httpx.AsyncClient(
            timeout=30.0,
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)
        )

        logger.info(f"Initialized FHIR client with base URL: {self.base_url}")

    async def close(self):
        """Close HTTP client and cleanup resources"""
        await self.client.aclose()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def search(
        self,
        resource_type: str,
        params: Optional[Dict[str, Any]] = None,
        max_results: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Search for FHIR resources

        Args:
            resource_type: FHIR resource type (e.g., "Patient", "Observation")
            params: Search parameters (e.g., {"name": "John", "gender": "male"})
            max_results: Maximum number of results to return (handles pagination)

        Returns:
            List of FHIR resources matching search criteria

        Example:
            patients = await client.search("Patient", {"gender": "female"}, max_results=100)
        """
        url = f"{self.base_url}/{resource_type}"
        search_params = params or {}

        # Add _count parameter for pagination
        if max_results:
            search_params["_count"] = min(max_results, 200)

        logger.debug(f"Searching {resource_type} with params: {search_params}")

        all_resources = []
        next_url = url

        while next_url:
            try:
                response = await self.client.get(next_url, params=search_params if next_url == url else None)
                response.raise_for_status()

                bundle = response.json()

                # Extract resources from bundle
                if bundle.get("resourceType") == "Bundle":
                    entries = bundle.get("entry", [])
                    resources = [entry.get("resource") for entry in entries if "resource" in entry]
                    all_resources.extend(resources)

                    logger.debug(f"Retrieved {len(resources)} {resource_type} resources")

                    # Check if we've reached max_results
                    if max_results and len(all_resources) >= max_results:
                        all_resources = all_resources[:max_results]
                        break

                    # Get next page URL
                    next_url = None
                    for link in bundle.get("link", []):
                        if link.get("relation") == "next":
                            next_url = link.get("url")
                            break
                else:
                    logger.warning(f"Unexpected response type: {bundle.get('resourceType')}")
                    break

                # Clear search_params for subsequent requests (use URL from next link)
                search_params = None

            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error searching {resource_type}: {e}")
                raise
            except Exception as e:
                logger.error(f"Error searching {resource_type}: {e}")
                raise

        logger.info(f"Search complete: retrieved {len(all_resources)} {resource_type} resources")
        return all_resources

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def read(self, resource_type: str, resource_id: str) -> Dict[str, Any]:
        """
        Read a specific FHIR resource by ID

        Args:
            resource_type: FHIR resource type (e.g., "Patient")
            resource_id: Resource ID

        Returns:
            FHIR resource as dict

        Example:
            patient = await client.read("Patient", "patient-123")
        """
        url = f"{self.base_url}/{resource_type}/{resource_id}"

        logger.debug(f"Reading {resource_type}/{resource_id}")

        try:
            response = await self.client.get(url)
            response.raise_for_status()

            resource = response.json()
            logger.debug(f"Successfully read {resource_type}/{resource_id}")
            return resource

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error reading {resource_type}/{resource_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Error reading {resource_type}/{resource_id}: {e}")
            raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def create(self, resource: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a new FHIR resource

        Args:
            resource: FHIR resource as dict (must include resourceType)

        Returns:
            Created resource with id and metadata

        Example:
            patient = {"resourceType": "Patient", "name": [{"family": "Smith"}]}
            created = await client.create(patient)
        """
        resource_type = resource.get("resourceType")
        if not resource_type:
            raise ValueError("Resource must have 'resourceType' field")

        url = f"{self.base_url}/{resource_type}"

        logger.debug(f"Creating {resource_type}")

        try:
            response = await self.client.post(url, json=resource)
            response.raise_for_status()

            created_resource = response.json()
            logger.info(f"Created {resource_type}/{created_resource.get('id')}")
            return created_resource

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error creating {resource_type}: {e}")
            raise
        except Exception as e:
            logger.error(f"Error creating {resource_type}: {e}")
            raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def batch(self, bundle: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a batch or transaction bundle

        Args:
            bundle: FHIR Bundle resource with type "batch" or "transaction"

        Returns:
            Bundle with batch/transaction results

        Example:
            bundle = {
                "resourceType": "Bundle",
                "type": "batch",
                "entry": [...]
            }
            result = await client.batch(bundle)
        """
        url = self.base_url

        bundle_type = bundle.get("type")
        logger.debug(f"Executing {bundle_type} bundle with {len(bundle.get('entry', []))} entries")

        try:
            response = await self.client.post(url, json=bundle)
            response.raise_for_status()

            result_bundle = response.json()
            logger.info(f"Batch operation complete: {len(result_bundle.get('entry', []))} results")
            return result_bundle

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error executing batch: {e}")
            raise
        except Exception as e:
            logger.error(f"Error executing batch: {e}")
            raise

    async def get_metadata(self) -> Dict[str, Any]:
        """
        Get FHIR server capability statement (metadata)

        Returns:
            CapabilityStatement resource
        """
        url = f"{self.base_url}/metadata"

        logger.debug("Fetching server metadata")

        try:
            response = await self.client.get(url)
            response.raise_for_status()

            metadata = response.json()
            logger.info(f"Server: {metadata.get('software', {}).get('name', 'Unknown')}")
            return metadata

        except Exception as e:
            logger.error(f"Error fetching metadata: {e}")
            raise

    async def test_connection(self) -> bool:
        """
        Test if FHIR server is reachable

        Returns:
            True if server responds, False otherwise
        """
        try:
            await self.get_metadata()
            logger.info("FHIR server connection successful")
            return True
        except Exception as e:
            logger.error(f"FHIR server connection failed: {e}")
            return False


# Convenience function to create a FHIR client
async def create_fhir_client(base_url: Optional[str] = None) -> FHIRClient:
    """
    Create and test FHIR client connection

    Args:
        base_url: FHIR server base URL

    Returns:
        FHIRClient instance
    """
    client = FHIRClient(base_url)

    # Test connection
    if not await client.test_connection():
        logger.warning("FHIR server connection test failed - client created anyway")

    return client
