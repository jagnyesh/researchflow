"""
User Management API Endpoints

Provides CRUD operations for user management in ResearchFlow.

Endpoints:
- POST /users - Create new user (admin only)
- GET /users - List all users (admin only)
- GET /users/{user_id} - Get user by ID
- PUT /users/{user_id} - Update user
- DELETE /users/{user_id} - Delete user (admin only)
- PATCH /users/{user_id}/password - Change user password
"""

from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.database import get_db_session
from app.database.models import User as UserModel
from app.security.dependencies import (
    get_current_user,
    get_current_active_user,
    require_role,
    require_any_role,
    User,
)
from app.security.auth import get_password_hash, verify_password
from app.schemas.users import PasswordChange, UserCreate, UserUpdate
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

router = APIRouter(prefix="/users", tags=["users"])


# UserCreate, UserUpdate, PasswordChange migrated to app/schemas/users.py
# (Sprint 6.1 Phase 2.3 Issue #6)


class UserResponse(BaseModel):
    """User response model"""

    id: str
    email: str
    full_name: str
    department: Optional[str]
    role: str
    is_active: bool
    is_verified: bool
    created_at: datetime
    last_login_at: Optional[datetime]

    class Config:
        from_attributes = True


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_data: UserCreate,
    current_user: User = Depends(require_role("admin")),
):
    """
    Create a new user (admin only)

    Args:
        user_data: User creation data
        current_user: Current authenticated admin user

    Returns:
        Created user object

    Raises:
        HTTPException: 400 if email already exists
        HTTPException: 403 if not admin

    Example:
        POST /users
        {
            "email": "newuser@example.com",
            "full_name": "New User",
            "department": "Research",
            "role": "researcher",
            "password": "securepassword"  # pragma: allowlist secret
        }
    """
    async with get_db_session() as db:
        # Check if user already exists
        result = await db.execute(select(UserModel).filter(UserModel.email == user_data.email))
        existing_user = result.scalar_one_or_none()

        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered"
            )

        # Generate user ID
        user_id = f"USR-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        # Create user with hashed password
        new_user = UserModel(
            id=user_id,
            email=user_data.email,
            full_name=user_data.full_name,
            department=user_data.department,
            role=user_data.role,
            hashed_password=get_password_hash(user_data.password),
            is_active=True,
            is_verified=False,
        )

        db.add(new_user)
        await db.commit()
        await db.refresh(new_user)

        return new_user


@router.get("", response_model=List[UserResponse])
async def list_users(
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(require_role("admin")),
):
    """
    List all users (admin only)

    Args:
        skip: Number of users to skip (pagination)
        limit: Maximum number of users to return
        current_user: Current authenticated admin user

    Returns:
        List of users

    Example:
        GET /users?skip=0&limit=10
    """
    async with get_db_session() as db:
        result = await db.execute(select(UserModel).offset(skip).limit(limit))
        users = result.scalars().all()
        return users


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """
    Get user by ID

    Users can view their own profile. Admins can view any user.

    Args:
        user_id: User ID to retrieve
        current_user: Current authenticated user

    Returns:
        User object

    Raises:
        HTTPException: 403 if not authorized
        HTTPException: 404 if user not found

    Example:
        GET /users/USR-00000001
    """
    # Check authorization: users can view their own profile, admins can view anyone
    if current_user.user_id != user_id and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view this user",
        )

    async with get_db_session() as db:
        result = await db.execute(select(UserModel).filter(UserModel.id == user_id))
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        return user


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    user_data: UserUpdate,
    current_user: User = Depends(get_current_active_user),
):
    """
    Update user information

    Users can update their own profile (except role).
    Admins can update any user including role changes.

    Args:
        user_id: User ID to update
        user_data: Updated user data
        current_user: Current authenticated user

    Returns:
        Updated user object

    Raises:
        HTTPException: 403 if not authorized
        HTTPException: 404 if user not found

    Example:
        PUT /users/USR-00000001
        {
            "full_name": "Updated Name",
            "department": "New Department"
        }
    """
    # Check authorization
    is_self = current_user.user_id == user_id
    is_admin = current_user.role == "admin"

    if not is_self and not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this user",
        )

    async with get_db_session() as db:
        # Retrieve user
        result = await db.execute(select(UserModel).filter(UserModel.id == user_id))
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        # Update fields
        if user_data.full_name is not None:
            user.full_name = user_data.full_name

        if user_data.department is not None:
            user.department = user_data.department

        # Only admins can change role and is_active
        if user_data.role is not None:
            if not is_admin:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Only admins can change user roles",
                )
            user.role = user_data.role

        if user_data.is_active is not None:
            if not is_admin:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Only admins can activate/deactivate users",
                )
            user.is_active = user_data.is_active

        user.updated_at = datetime.now()

        await db.commit()
        await db.refresh(user)

        return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    current_user: User = Depends(require_role("admin")),
):
    """
    Delete a user (admin only)

    Args:
        user_id: User ID to delete
        current_user: Current authenticated admin user

    Raises:
        HTTPException: 403 if not admin
        HTTPException: 404 if user not found

    Example:
        DELETE /users/USR-00000001
    """
    async with get_db_session() as db:
        result = await db.execute(select(UserModel).filter(UserModel.id == user_id))
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        await db.delete(user)
        await db.commit()

        return None


@router.patch("/{user_id}/password", status_code=status.HTTP_200_OK)
async def change_password(
    user_id: str,
    password_data: PasswordChange,
    current_user: User = Depends(get_current_active_user),
):
    """
    Change user password

    Users can only change their own password.

    Args:
        user_id: User ID
        password_data: Current and new passwords
        current_user: Current authenticated user

    Returns:
        Success message

    Raises:
        HTTPException: 403 if not authorized
        HTTPException: 404 if user not found
        HTTPException: 400 if current password is incorrect

    Example:
        PATCH /users/USR-00000001/password
        {
            "current_password": "oldpassword",  # pragma: allowlist secret
            "new_password": "newpassword"  # pragma: allowlist secret
        }
    """
    # Users can only change their own password
    if current_user.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to change this user's password",
        )

    async with get_db_session() as db:
        # Retrieve user
        result = await db.execute(select(UserModel).filter(UserModel.id == user_id))
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        # Verify current password using bcrypt
        if not verify_password(password_data.current_password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Incorrect current password"
            )

        # Update password with bcrypt hashing
        user.hashed_password = get_password_hash(password_data.new_password)
        user.updated_at = datetime.now()

        await db.commit()

        return {"message": "Password changed successfully"}
