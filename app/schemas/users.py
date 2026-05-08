"""Schemas for /users router — Sprint 6.1 Phase 2.3 Issue #6 (Tier 2)."""

from typing import Literal, Optional

from app.schemas import EmailStr, PHIInputModel, ShortText
from app.schemas.auth import PasswordField

# Role discipline: researchers can submit/view, data stewards can approve, admins can manage.
Role = Literal["researcher", "data_steward", "admin"]


class UserCreate(PHIInputModel):
    """Body for POST /users."""

    email: EmailStr
    full_name: ShortText
    department: Optional[ShortText] = None
    role: Role = "researcher"
    password: PasswordField


class UserUpdate(PHIInputModel):
    """Body for PUT /users/{user_id}."""

    full_name: Optional[ShortText] = None
    department: Optional[ShortText] = None
    role: Optional[Role] = None
    is_active: Optional[bool] = None


class PasswordChange(PHIInputModel):
    """Body for PATCH /users/{user_id}/password."""

    current_password: PasswordField
    new_password: PasswordField
