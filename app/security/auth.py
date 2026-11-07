"""
Authentication and JWT Token Management

Provides utilities for JWT token generation, validation, and password hashing
for ResearchFlow API authentication.

Security Features:
- JWT token generation with configurable expiration
- Password hashing using bcrypt (HIPAA-compliant)
- Token validation and decoding
- Secure password verification
"""

import os
from datetime import datetime, timedelta
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, ValidationError

# JWT Configuration
_DEV_SECRET_KEY = "dev-secret-key-change-in-production"  # nosec B105  # pragma: allowlist secret
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))


def get_jwt_secret_key() -> str:
    """Return the JWT signing secret; in production, refuse an unset or default one.

    Resolved on every sign/verify rather than at import, so Streamlit dashboards
    and scripts are gated too, not only the FastAPI lifespan.
    """
    key = os.getenv("JWT_SECRET_KEY")
    if os.getenv("ENVIRONMENT", "development") == "production" and (
        not key or key == _DEV_SECRET_KEY
    ):
        raise RuntimeError("JWT_SECRET_KEY must be set to a non-default value in production.")
    return key or _DEV_SECRET_KEY


# Password hashing context (bcrypt)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class Token(BaseModel):
    """JWT token response"""

    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    """Data embedded in JWT token"""

    email: Optional[str] = None
    user_id: Optional[str] = None
    role: Optional[str] = None


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plain password against a hashed password

    Args:
        plain_password: Password in plain text
        hashed_password: Bcrypt hashed password from database

    Returns:
        True if password matches, False otherwise
    """
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """
    Hash a password using bcrypt

    Args:
        password: Password in plain text

    Returns:
        Bcrypt hashed password safe for database storage

    Security:
        Uses bcrypt with automatic salt generation
        Cost factor: 12 rounds (HIPAA recommended)
    """
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a JWT access token

    Args:
        data: Dictionary containing claims to encode (user_id, email, role, etc.)
        expires_delta: Optional custom expiration time

    Returns:
        Encoded JWT token string

    Example:
        token = create_access_token({"sub": user.email, "user_id": user.id, "role": user.role})
    """
    to_encode = data.copy()

    # Set expiration
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire})

    # Encode JWT token
    encoded_jwt = jwt.encode(to_encode, get_jwt_secret_key(), algorithm=ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> Optional[TokenData]:
    """
    Decode and validate a JWT access token

    Args:
        token: JWT token string from Authorization header

    Returns:
        TokenData if valid, None if invalid/expired

    Security:
        - Verifies token signature
        - Checks expiration
        - Validates token structure
    """
    try:
        payload = jwt.decode(token, get_jwt_secret_key(), algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        user_id: str = payload.get("user_id")
        role: str = payload.get("role")

        # Every caller needs both identities; a token missing either is invalid (#227).
        if not email or not user_id:
            return None

        return TokenData(email=email, user_id=user_id, role=role)
    except (JWTError, ValidationError):
        # A signed token with mistyped claims is still an invalid token (#227);
        # the ValidationError text would echo the claim values, so it is dropped.
        return None
