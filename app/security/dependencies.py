"""
FastAPI Authentication Dependencies

Provides dependency injection functions for JWT authentication and authorization.
Used to protect API endpoints and extract user information from requests.

Usage:
    @app.get("/protected")
    async def protected_route(current_user: User = Depends(get_current_user)):
        return {"user": current_user.email}
"""

from typing import Optional
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from .auth import decode_access_token

# HTTP Bearer token scheme (Authorization: Bearer <token>)
security = HTTPBearer()


class User(BaseModel):
    """User model for authentication (minimal version for Phase 1.1)"""

    email: str
    user_id: str
    role: str
    is_active: bool = True


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> User:
    """Extract and validate JWT token from Authorization header.

    Side effect: writes the resolved User to ``request.state.principal`` so
    audit middleware (and any downstream consumer) sees a unified principal
    regardless of which path resolved it (Sprint 6.1 Phase 2.2 Issue #2).
    """
    token = credentials.credentials
    token_data = decode_access_token(token)

    if token_data is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = User(
        email=token_data.email,
        user_id=token_data.user_id,
        role=token_data.role or "researcher",
        is_active=True,
    )
    request.state.principal = user
    return user


async def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    """
    Verify that the authenticated user is active

    Args:
        current_user: User from get_current_user dependency

    Returns:
        Active user object

    Raises:
        HTTPException: 403 if user is inactive

    Usage:
        @app.delete("/api/data/{id}")
        async def delete_data(
            id: str,
            user: User = Depends(get_current_active_user)
        ):
            # Only active users can delete data
            ...
    """
    if not current_user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")

    return current_user


def require_role(required_role: str):
    """
    Dependency factory for role-based access control

    Args:
        required_role: Required user role (e.g., "admin", "researcher", "data_steward")

    Returns:
        Dependency function that verifies user has required role

    Raises:
        HTTPException: 403 if user lacks required role

    Usage:
        @app.post("/api/admin/users")
        async def create_user(
            user_data: dict,
            current_user: User = Depends(require_role("admin"))
        ):
            # Only admins can create users
            ...
    """

    async def role_checker(current_user: User = Depends(get_current_active_user)) -> User:
        if current_user.role != required_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required role: {required_role}",
            )
        return current_user

    return role_checker


def require_any_role(*roles: str):
    """
    Dependency factory for multi-role access control

    Args:
        roles: List of acceptable roles

    Returns:
        Dependency function that verifies user has one of the roles

    Raises:
        HTTPException: 403 if user lacks all required roles

    Usage:
        @app.get("/api/data/{id}")
        async def get_data(
            id: str,
            current_user: User = Depends(require_any_role("admin", "data_steward", "researcher"))
        ):
            # Admins, data stewards, or researchers can view data
            ...
    """

    async def role_checker(current_user: User = Depends(get_current_active_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required roles: {', '.join(roles)}",
            )
        return current_user

    return role_checker
