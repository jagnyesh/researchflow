from fastapi import APIRouter
from pydantic import BaseModel
from ..adapters.sql_on_fhir import SQLonFHIRAdapter

router = APIRouter()


class SQLQueryRequest(BaseModel):
    sql: str


@router.post("/sql_query")
async def sql_query(req: SQLQueryRequest):
    adapter = SQLonFHIRAdapter()
    rows = await adapter.execute_sql(req.sql)
    return {"rows": rows}
