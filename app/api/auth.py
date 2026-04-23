"""
Authentication API Endpoints

Provides JWT-based authentication endpoints for ResearchFlow API.

Endpoints:
- POST /auth/login - Authenticate user and return JWT token
- POST /auth/logout - Logout (client-side token deletion for stateless JWT)
- POST /auth/refresh - Refresh JWT token
- GET /auth/me - Get current user information
"""

from datetime import timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr

from app.security.auth import (
    create_access_token,
    verify_password,
    get_password_hash,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    Token,
)
from app.security.dependencies import get_current_user, get_current_active_user, User
from app.database import get_db_session
from app.database.models import User as UserModel
from sqlalchemy import select


router = APIRouter(prefix="/auth", tags=["authentication"])


class LoginRequest(BaseModel):
    """Login request model"""

    email: EmailStr
    password: str


class UserResponse(BaseModel):
    """User information response"""

    email: str
    user_id: str
    full_name: str
    role: str
    is_active: bool


class LoginResponse(BaseModel):
    """Login response with token and user info"""

    access_token: str
    token_type: str = "bearer"
    user: UserResponse


# Mock users with bcrypt hashed passwords for testing
# Password for both users: "password123"
# These are pre-hashed using bcrypt directly (Phase 1.3)
MOCK_USERS = {
    "researcher@example.com": {
        "user_id": "USR-00000001",
        "email": "researcher@example.com",
        "full_name": "Jane Researcher",
        "role": "researcher",
        "hashed_password": "$2b$12$tdO60AuFrQE2z5McrZCsa.OUDmLvOHXoSpKY3fVUOVvIseCr8Hm0y",  # password123  # nosec B106
        "is_active": True,
    },
    "admin@example.com": {
        "user_id": "USR-00000002",
        "email": "admin@example.com",
        "full_name": "John Admin",
        "role": "admin",
        "hashed_password": "$2b$12$tn1DrM0IUpMEimr.i/FTreCElmZFpwGd3rh.1ULG9jJEHzV.COElm",  # password123  # nosec B106
        "is_active": True,
    },
}


@router.post("/login", response_model=LoginResponse)
async def login(login_request: LoginRequest):
    """
    Authenticate user and return JWT token

    Args:
        login_request: Email and password

    Returns:
        JWT access token and user information

    Raises:
        HTTPException: 401 if credentials are invalid

    Example:
        POST /auth/login
        {
            "email": "researcher@example.com",
            "password": "password123"  # pragma: allowlist secret
        }

        Response:
        {
            "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
            "token_type": "bearer",
            "user": {
                "email": "researcher@example.com",
                "user_id": "USR-00000001",
                "full_name": "Jane Researcher",
                "role": "researcher",
                "is_active": true
            }
        }
    """
    # Try database lookup first, fallback to MOCK_USERS
    async with get_db_session() as db:
        result = await db.execute(select(UserModel).filter(UserModel.email == login_request.email))
        user_model = result.scalar_one_or_none()

    if user_model:
        # Database user found - verify bcrypt hashed password
        if not verify_password(login_request.password, user_model.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Check if user is active
        if not user_model.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is inactive")

        # Create user dict for token generation
        user = {
            "email": user_model.email,
            "user_id": user_model.id,
            "full_name": user_model.full_name,
            "role": user_model.role,
            "is_active": user_model.is_active,
        }
    else:
        # Fallback to MOCK_USERS for testing
        user = MOCK_USERS.get(login_request.email)

        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Verify password using bcrypt
        if not verify_password(login_request.password, user["hashed_password"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Check if user is active
        if not user["is_active"]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is inactive")

    # Create JWT token
    access_token = create_access_token(
        data={
            "sub": user["email"],
            "user_id": user["user_id"],
            "role": user["role"],
        }
    )

    return LoginResponse(
        access_token=access_token,
        token_type="bearer",  # nosec B106  # OAuth2 token type, not a password
        user=UserResponse(
            email=user["email"],
            user_id=user["user_id"],
            full_name=user["full_name"],
            role=user["role"],
            is_active=user["is_active"],
        ),
    )


@router.post("/logout")
async def logout(current_user: User = Depends(get_current_active_user)):
    """
    Logout endpoint (client-side token deletion for stateless JWT)

    For stateless JWT authentication, logout is handled client-side by
    deleting the token from local storage. Server-side token invalidation
    would require a token blacklist (future enhancement).

    Args:
        current_user: Current authenticated user

    Returns:
        Success message

    Example:
        POST /auth/logout
        Authorization: Bearer <token>

        Response:
        {
            "message": "Successfully logged out"
        }
    """
    # In stateless JWT, logout is client-side (delete token from storage)
    # Server-side token blacklist can be added in Phase 1.3 if needed

    return {
        "message": "Successfully logged out",
        "detail": "Please delete the JWT token from client storage",
    }


@router.post("/refresh", response_model=Token)
async def refresh_token(current_user: User = Depends(get_current_user)):
    """
    Refresh JWT access token

    Issues a new JWT token with extended expiration. Old token remains
    valid until expiration (stateless JWT limitation).

    Args:
        current_user: Current authenticated user

    Returns:
        New JWT access token

    Example:
        POST /auth/refresh
        Authorization: Bearer <old_token>

        Response:
        {
            "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
            "token_type": "bearer"
        }
    """
    # Create new token with fresh expiration
    access_token = create_access_token(
        data={
            "sub": current_user.email,
            "user_id": current_user.user_id,
            "role": current_user.role,
        }
    )

    return Token(access_token=access_token, token_type="bearer")  # nosec B106  # OAuth2 token type


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: User = Depends(get_current_active_user)):
    """
    Get current authenticated user information

    Args:
        current_user: Current authenticated user from JWT token

    Returns:
        User profile information

    Example:
        GET /auth/me
        Authorization: Bearer <token>

        Response:
        {
            "email": "researcher@example.com",
            "user_id": "USR-00000001",
            "full_name": "Jane Researcher",
            "role": "researcher",
            "is_active": true
        }
    """
    return UserResponse(
        email=current_user.email,
        user_id=current_user.user_id,
        full_name=current_user.email.split("@")[0].title(),  # Fallback for mock users
        role=current_user.role,
        is_active=current_user.is_active,
    )


@router.post("/token", response_model=Token, include_in_schema=False)
async def token_endpoint(form_data: OAuth2PasswordRequestForm = Depends()):
    """
    OAuth2 compatible token endpoint (for Swagger UI authentication)

    This endpoint uses OAuth2PasswordRequestForm which expects:
    - username (we use email)
    - password

    Hidden from main API docs (use /auth/login instead)
    """
    # Reuse login logic
    login_request = LoginRequest(email=form_data.username, password=form_data.password)
    response = await login(login_request)

    return Token(
        access_token=response.access_token, token_type="bearer"
    )  # nosec B106  # OAuth2 token type
