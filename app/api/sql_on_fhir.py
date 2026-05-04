from fastapi import APIRouter

from ..adapters.sql_on_fhir import SQLonFHIRAdapter
from ..schemas.sql_on_fhir import SQLQueryRequest

router = APIRouter()


@router.post("/sql_query")
async def sql_query(req: SQLQueryRequest):
    adapter = SQLonFHIRAdapter()
    rows = await adapter.execute_sql(req.sql)
    return {"rows": rows}
