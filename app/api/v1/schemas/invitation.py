"""Invitation and activation schemas."""

from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator


class InviteUserRequest(BaseModel):
    """Request schema for inviting a user (admin-only)."""

    name: str = Field(..., min_length=2, max_length=255, description="Full name")
    email: EmailStr = Field(..., description="Email address")
    plan_id: Optional[str] = Field(None, description="Optional plan UUID to associate")


class InviteUserResponse(BaseModel):
    """Response schema for user invitation.

    Note: The activation token is sent via email and NOT included in the response.
    """

    user_id: str = Field(..., description="Created user UUID")
    email: str = Field(..., description="User email")
    name: str = Field(..., description="User name")
    message: str = Field(default="User invited successfully. Activation email sent.")


class ActivateAccountRequest(BaseModel):
    """Request schema for account activation."""

    token: str = Field(
        ...,
        min_length=32,
        max_length=64,
        description="Activation token from invitation email",
    )
    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Password to set for the account",
    )
    cpf: str = Field(
        ...,
        min_length=11,
        max_length=14,
        description="CPF (with or without formatting)",
    )
    phone: str = Field(
        ...,
        min_length=10,
        max_length=20,
        description="Phone number",
    )
    nickname: Optional[str] = Field(
        None,
        max_length=100,
        description="Optional nickname",
    )

    @field_validator("cpf")
    @classmethod
    def validate_cpf(cls, v: str) -> str:
        """Remove formatting from CPF."""
        import re
        return re.sub(r"\D", "", v)


class ActivateAccountResponse(BaseModel):
    """Response schema for account activation."""

    user_id: str = Field(..., description="Activated user UUID")
    email: str = Field(..., description="User email")
    name: str = Field(..., description="User name")
    message: str = Field(default="Account activated successfully")
