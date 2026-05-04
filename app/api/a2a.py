from fastapi import APIRouter, HTTPException

from ..a2a.auth import issue_token
from ..schemas.a2a import TokenRequest

router = APIRouter(prefix="/a2a")


@router.post("/token")
async def token(req: TokenRequest):
    token = issue_token(req.client_id, req.client_secret)
    if not token:
        raise HTTPException(status_code=401, detail="invalid_client")
    return {"access_token": token}
