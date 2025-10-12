from fastapi import APIRouter
from pydantic import BaseModel
from ..services.text2sql import Text2SQLService

router = APIRouter()


class Text2SQLRequest(BaseModel):
    prompt: str


@router.post("/text2sql")
async def text2sql(req: Text2SQLRequest):
    svc = Text2SQLService()
    sql = await svc.generate_sql(req.prompt)
    return {"sql": sql}
