"""User schemas.""" 

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class UserResponse(BaseModel):
    """Response schema for user data."""

    id: str = Field(..., description="User UUID")
    cpf: Optional[str] = Field(None, description="User CPF (formatted, None for invited users)")
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


# ------------------------------------------------------------------
# Admin client list schemas (separate from generic UserListResponse)
# ------------------------------------------------------------------


class AdminClientStats(BaseModel):
    """Status-based counts for admin client statistics."""

    active: int = Field(..., description="Number of active clients")
    inactive: int = Field(..., description="Number of inactive clients")
    defaulting: int = Field(..., description="Number of defaulting clients")
    registered: int = Field(..., description="Number of registered (not yet active) clients")
    total: int = Field(..., description="Total number of clients (all statuses)")


class AdminClientResponse(BaseModel):
    """Single client entry for admin client list."""

    id: str = Field(..., description="User UUID")
    name: str = Field(..., description="Client name")
    email: str = Field(..., description="Client email")
    cpf: Optional[str] = Field(None, description="CPF (11-digit string or None)")
    status: str = Field(..., description="Client status")
    phone: Optional[str] = Field(None, description="Phone number")
    created_at: datetime = Field(..., description="Registration date")
    total_invested_cents: int = Field(
        ..., description="Total invested (from wallet.total_invested_cents), 0 if no wallet"
    )


class AdminClientListResponse(BaseModel):
    """Paginated admin client list with real counts."""

    clients: list[AdminClientResponse] = Field(..., description="Clients on this page")
    total: int = Field(..., description="Total matching clients (for pagination)")
    page: int = Field(..., description="Current page")
    page_size: int = Field(..., description="Page size")
    stats: AdminClientStats = Field(..., description="Counts by status for all clients")
