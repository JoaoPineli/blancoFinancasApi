"""User schemas.""" 

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class UserResponse(BaseModel):
    """Response schema for user data."""

    id: str = Field(..., description="User UUID")
    cpf: str = Field(..., description="User CPF (formatted)")
    email: str = Field(..., description="User email")
    name: str = Field(..., description="User name")
    role: str = Field(..., description="User role")
    status: str = Field(..., description="User status")
    phone: Optional[str] = Field(None, description="User phone")
    created_at: datetime = Field(..., description="Registration date")


class UserListResponse(BaseModel):
    """Response schema for user list."""

    users: list[UserResponse] = Field(..., description="List of users")
    total: int = Field(..., description="Total count")
    page: int = Field(..., description="Current page")
    page_size: int = Field(..., description="Page size")


class UpdateUserRequest(BaseModel):
    """Request schema for updating user."""

    email: Optional[EmailStr] = Field(None, description="New email")
    phone: Optional[str] = Field(None, max_length=20, description="New phone")
    name: Optional[str] = Field(None, min_length=2, max_length=255, description="New name")


class UserStatusRequest(BaseModel):
    """Request schema for changing user status."""

    status: str = Field(..., pattern="^(active|inactive|defaulting)$", description="New status")
