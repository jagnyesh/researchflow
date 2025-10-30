"""
Real-Time Analytics API

Provides endpoints for executing SQL-on-FHIR v2 ViewDefinitions
and running real-time analytics queries against FHIR data.

Supports two runner types (configured via VIEWDEF_RUNNER env var):
- 'postgres': PostgresRunner (10-100x faster, in-database execution)
- 'in_memory': InMemoryRunner (slower, REST API-based)
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Dict, List, Any, Optional
import logging
import os

from ..clients.fhir_client import create_fhir_client
from ..clients.hapi_db_client import create_hapi_db_client, close_hapi_db_client
from ..sql_on_fhir.view_definition_manager import ViewDefinitionManager
from ..sql_on_fhir.runner.in_memory_runner import InMemoryRunner
from ..sql_on_fhir.runner.materialized_view_runner import MaterializedViewRunner
from ..sql_on_fhir.runner.hybrid_runner import HybridRunner
from ..sql_on_fhir.runner import create_postgres_runner

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analytics", tags=["analytics"])


async def create_runner():
    """
    Create ViewDefinition runner based on VIEWDEF_RUNNER environment variable

    Returns:
        Tuple of (runner, cleanup_function)
        - runner: InMemoryRunner, PostgresRunner, MaterializedViewRunner, or HybridRunner
        - cleanup_function: async function to call for cleanup (or None)

    Environment Variables:
        VIEWDEF_RUNNER: 'hybrid' (default), 'postgres', 'materialized', or 'in_memory'
        ENABLE_QUERY_CACHE: 'true' or 'false' (default: true)
        CACHE_TTL_SECONDS: Cache TTL in seconds (default: 300)
    """
    runner_type = os.getenv('VIEWDEF_RUNNER', 'hybrid').lower()
    enable_cache = os.getenv('ENABLE_QUERY_CACHE', 'true').lower() == 'true'
    cache_ttl = int(os.getenv('CACHE_TTL_SECONDS', '300'))

    if runner_type == 'hybrid':
        logger.info(
            f"Using HybridRunner (materialized views when available, postgres fallback, cache={enable_cache}, TTL={cache_ttl}s)"
        )

        # Create HAPI DB client
        db_client = await create_hapi_db_client()

        # Create HybridRunner
        runner = HybridRunner(
            db_client,
            enable_cache=enable_cache,
            cache_ttl_seconds=cache_ttl
        )

        # Cleanup function
        async def cleanup():
            await close_hapi_db_client()

        return runner, cleanup

    elif runner_type == 'postgres':
        logger.info(f"Using PostgresRunner (cache={enable_cache}, TTL={cache_ttl}s)")

        # Create HAPI DB client
        db_client = await create_hapi_db_client()

        # Create PostgresRunner
        runner = await create_postgres_runner(
            db_client,
            enable_cache=enable_cache,
            cache_ttl_seconds=cache_ttl
        )

        # Cleanup function
        async def cleanup():
            await close_hapi_db_client()

        return runner, cleanup

    elif runner_type == 'materialized':
        logger.info("Using MaterializedViewRunner (10-100x faster, queries pre-computed views)")

        # Create HAPI DB client
        db_client = await create_hapi_db_client()

        # Create MaterializedViewRunner
        runner = MaterializedViewRunner(db_client)

        # Cleanup function
        async def cleanup():
            await close_hapi_db_client()

        return runner, cleanup

    else:  # in_memory
        logger.info("Using InMemoryRunner (REST API-based)")

        # Create FHIR client
        fhir_client = await create_fhir_client()

        # Create InMemoryRunner
        runner = InMemoryRunner(fhir_client)

        # Cleanup function
        async def cleanup():
            await fhir_client.close()

        return runner, cleanup


class ViewDefinitionRequest(BaseModel):
    """Request to execute a ViewDefinition"""
    view_name: str = Field(..., description="Name of the ViewDefinition to execute")
    search_params: Optional[Dict[str, Any]] = Field(None, description="FHIR search parameters to filter resources")
    max_resources: Optional[int] = Field(None, description="Maximum number of resources to process")


class ViewDefinitionResponse(BaseModel):
    """Response from ViewDefinition execution"""
    view_name: str
    resource_type: str
    row_count: int
    rows: List[Dict[str, Any]]
    column_schema: Dict[str, str]
    generated_sql: Optional[str] = None  # SQL query that was executed


class ViewDefinitionListResponse(BaseModel):
    """List of available ViewDefinitions"""
    view_definitions: List[Dict[str, str]]


class CreateViewDefinitionRequest(BaseModel):
    """Request to create a ViewDefinition"""
    view_definition: Dict[str, Any] = Field(..., description="ViewDefinition resource")
    name: Optional[str] = Field(None, description="Optional name override")


@router.get("/view-definitions", response_model=ViewDefinitionListResponse)
async def list_view_definitions():
    """
    List all available ViewDefinitions

    Returns:
        List of ViewDefinition names and their resource types
    """
    try:
        manager = ViewDefinitionManager()
        view_defs = manager.load_all()

        view_list = [
            {
                "name": name,
                "resource_type": vd.get("resource"),
                "title": vd.get("title", ""),
                "description": vd.get("description", "")
            }
            for name, vd in view_defs.items()
        ]

        logger.info(f"Listed {len(view_list)} ViewDefinitions")
        return ViewDefinitionListResponse(view_definitions=view_list)

    except Exception as e:
        logger.error(f"Error listing ViewDefinitions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/view-definitions/{view_name}")
async def get_view_definition(view_name: str):
    """
    Get a specific ViewDefinition by name

    Args:
        view_name: Name of the ViewDefinition

    Returns:
        ViewDefinition resource
    """
    try:
        manager = ViewDefinitionManager()
        view_def = manager.load(view_name)

        logger.info(f"Retrieved ViewDefinition '{view_name}'")
        return view_def

    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"ViewDefinition '{view_name}' not found")
    except Exception as e:
        logger.error(f"Error retrieving ViewDefinition: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/view-definitions")
async def create_view_definition(request: CreateViewDefinitionRequest):
    """
    Create a new ViewDefinition

    Args:
        request: ViewDefinition creation request

    Returns:
        Created ViewDefinition name
    """
    try:
        manager = ViewDefinitionManager()
        name = manager.save(request.view_definition, request.name)

        logger.info(f"Created ViewDefinition '{name}'")
        return {"name": name, "message": f"ViewDefinition '{name}' created successfully"}

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating ViewDefinition: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/view-definitions/{view_name}")
async def delete_view_definition(view_name: str):
    """
    Delete a ViewDefinition

    Args:
        view_name: Name of the ViewDefinition to delete

    Returns:
        Success message
    """
    try:
        manager = ViewDefinitionManager()
        deleted = manager.delete(view_name)

        if not deleted:
            raise HTTPException(status_code=404, detail=f"ViewDefinition '{view_name}' not found")

        logger.info(f"Deleted ViewDefinition '{view_name}'")
        return {"message": f"ViewDefinition '{view_name}' deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting ViewDefinition: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/execute", response_model=ViewDefinitionResponse)
async def execute_view_definition(request: ViewDefinitionRequest):
    """
    Execute a ViewDefinition and return tabular results

    Runner selection is controlled by VIEWDEF_RUNNER environment variable:
    - 'hybrid': Smart routing - uses materialized views when available, postgres when not (RECOMMENDED, default)
    - 'materialized': Ultra-fast queries against pre-computed views only (10-100x faster)
    - 'postgres': Fast in-database execution with SQL generation
    - 'in_memory': REST API-based execution (slower but more flexible)

    Args:
        request: ViewDefinition execution request

    Returns:
        Tabular results with row data and schema

    Example:
        POST /analytics/execute
        {
            "view_name": "patient_demographics",
            "search_params": {"gender": "female"},
            "max_resources": 100
        }
    """
    try:
        # Load ViewDefinition
        manager = ViewDefinitionManager()
        view_def = manager.load(request.view_name)

        # Create runner based on environment configuration
        runner, cleanup = await create_runner()

        try:
            logger.info(
                f"Executing ViewDefinition '{request.view_name}' "
                f"with params: {request.search_params}, max: {request.max_resources}"
            )

            rows = await runner.execute(
                view_def,
                search_params=request.search_params,
                max_resources=request.max_resources
            )

            # Get schema
            schema = runner.get_schema(view_def)

            # Get generated SQL (if PostgresRunner)
            generated_sql = None
            if hasattr(runner, 'get_last_executed_sql'):
                generated_sql = runner.get_last_executed_sql()

            logger.info(f"ViewDefinition '{request.view_name}' returned {len(rows)} rows")

            return ViewDefinitionResponse(
                view_name=request.view_name,
                resource_type=view_def.get("resource"),
                row_count=len(rows),
                rows=rows,
                column_schema=schema,
                generated_sql=generated_sql
            )

        finally:
            await cleanup()

    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"ViewDefinition '{request.view_name}' not found")
    except Exception as e:
        logger.error(f"Error executing ViewDefinition: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/execute/{view_name}", response_model=ViewDefinitionResponse)
async def execute_view_definition_get(
    view_name: str,
    max_resources: Optional[int] = Query(None, description="Maximum resources to process")
):
    """
    Execute a ViewDefinition via GET request (simplified version)

    Args:
        view_name: Name of the ViewDefinition
        max_resources: Maximum resources to process

    Returns:
        Tabular results with row data and schema

    Example:
        GET /analytics/execute/patient_demographics?max_resources=100
    """
    request = ViewDefinitionRequest(
        view_name=view_name,
        search_params=None,
        max_resources=max_resources
    )

    return await execute_view_definition(request)


@router.post("/query")
async def execute_custom_query(
    view_names: List[str] = Query(..., description="ViewDefinitions to execute"),
    search_params: Optional[Dict[str, Any]] = None,
    max_resources: Optional[int] = None
):
    """
    Execute multiple ViewDefinitions and return combined results

    Args:
        view_names: List of ViewDefinition names to execute
        search_params: FHIR search parameters
        max_resources: Maximum resources per ViewDefinition

    Returns:
        Combined results from all ViewDefinitions

    Example:
        POST /analytics/query?view_names=patient_demographics&view_names=condition_diagnoses
        {
            "search_params": {"_id": "patient-123"},
            "max_resources": 1000
        }
    """
    try:
        manager = ViewDefinitionManager()
        runner, cleanup = await create_runner()

        results = {}

        try:
            for view_name in view_names:
                try:
                    view_def = manager.load(view_name)

                    logger.info(f"Executing ViewDefinition '{view_name}' in batch query")

                    rows = await runner.execute(
                        view_def,
                        search_params=search_params,
                        max_resources=max_resources
                    )

                    results[view_name] = {
                        "resource_type": view_def.get("resource"),
                        "row_count": len(rows),
                        "rows": rows
                    }

                except Exception as e:
                    logger.warning(f"Error executing ViewDefinition '{view_name}': {e}")
                    results[view_name] = {
                        "error": str(e)
                    }

            logger.info(f"Batch query complete: {len(view_names)} ViewDefinitions")
            return results

        finally:
            await cleanup()

    except Exception as e:
        logger.error(f"Error executing batch query: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/schema/{view_name}")
async def get_view_schema(view_name: str):
    """
    Get the schema (column names and types) for a ViewDefinition

    Args:
        view_name: Name of the ViewDefinition

    Returns:
        Schema mapping column names to types
    """
    try:
        manager = ViewDefinitionManager()
        view_def = manager.load(view_name)

        # Create runner to extract schema
        runner, cleanup = await create_runner()
        try:
            schema = runner.get_schema(view_def)

            logger.info(f"Retrieved schema for ViewDefinition '{view_name}'")
            return {
                "view_name": view_name,
                "resource_type": view_def.get("resource"),
                "schema": schema
            }

        finally:
            await cleanup()

    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"ViewDefinition '{view_name}' not found")
    except Exception as e:
        logger.error(f"Error retrieving schema: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health_check():
    """
    Health check endpoint for analytics service

    Returns:
        Health status including FHIR server connectivity
    """
    try:
        # Test FHIR server connection
        fhir_client = await create_fhir_client()
        try:
            is_connected = await fhir_client.test_connection()

            return {
                "status": "healthy" if is_connected else "degraded",
                "fhir_server_connected": is_connected,
                "fhir_server_url": fhir_client.base_url
            }

        finally:
            await fhir_client.close()

    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e)
        }
