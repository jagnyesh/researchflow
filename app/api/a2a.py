from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from ..a2a.auth import issue_token

router = APIRouter(prefix="/a2a")


class TokenRequest(BaseModel):
    client_id: str
    client_secret: str


@router.post("/token")
async def token(req: TokenRequest):
    token = issue_token(req.client_id, req.client_secret)
    if not token:
        raise HTTPException(status_code=401, detail="invalid_client")
    return {"access_token": token}
