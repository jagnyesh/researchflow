from fastapi import APIRouter
from pydantic import BaseModel
from ..mcp.store import FileContextStore

router = APIRouter(prefix="/mcp")


class ContextRequest(BaseModel):
    request_id: str
    context: dict


@router.post("/context")
async def save_context(req: ContextRequest):
    store = FileContextStore()
    store.save(req.request_id, req.context)
    return {"status": "saved"}


@router.get("/context/{request_id}")
async def get_context(request_id: str):
    store = FileContextStore()
    ctx = store.load(request_id)
    return {"context": ctx}
