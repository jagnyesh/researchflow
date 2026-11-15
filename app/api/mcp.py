from fastapi import APIRouter, HTTPException

from ..mcp.store import FileContextStore
from ..schemas.mcp import ContextRequest

router = APIRouter(prefix="/mcp")


@router.post("/context")
async def save_context(req: ContextRequest):
    store = FileContextStore()
    try:
        store.save(req.request_id, req.context)
    except ValueError:
        # Fixed detail: the unsafe request_id must not be echoed (#478).
        raise HTTPException(status_code=400, detail="Invalid request_id") from None
    return {"status": "saved"}


@router.get("/context/{request_id}")
async def get_context(request_id: str):
    store = FileContextStore()
    ctx = store.load(request_id)
    return {"context": ctx}
