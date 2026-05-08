"""Schemas for /auth router — Sprint 6.1 Phase 2.3 Issue #6 (Tier 2)."""

from typing import Annotated

from pydantic import Field

from app.schemas import EmailStr, PHIInputModel

# Password fields: bound length to prevent 1MB request bodies; no minimum length
# enforcement here (that's Phase 1.3 password-policy territory).
PasswordField = Annotated[str, Field(min_length=1, max_length=200)]


class LoginRequest(PHIInputModel):
    """Body for POST /auth/login."""

    email: EmailStr
    password: PasswordField
