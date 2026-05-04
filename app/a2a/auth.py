import os
import time
from typing import Optional
from jose import jwt, JWTError

_SECRET = os.getenv("A2A_JWT_SECRET", "devsecret")


def _validate_client(client_id: str, client_secret: str) -> bool:
    # demo: accept client_id==client_secret for local testing
    return client_id and client_secret and client_id == client_secret


def issue_token(client_id: str, client_secret: str) -> str | None:
    if not _validate_client(client_id, client_secret):
        return None
    now = int(time.time())
    payload = {"sub": client_id, "iat": now, "exp": now + 3600}
    token = jwt.encode(payload, _SECRET, algorithm="HS256")
    return token


def verify_service_token(token: str) -> Optional[str]:
    """Verify a service token issued by issue_token. Returns sub (client_id) or None."""
    if not token:
        return None
    try:
        payload = jwt.decode(token, _SECRET, algorithms=["HS256"])
        return payload.get("sub")
    except JWTError:
        return None
