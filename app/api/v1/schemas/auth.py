"""Authentication and registration schemas."""

from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator


class RegisterRequest(BaseModel):
    """Request schema for user registration."""

    name: str = Field(..., min_length=2, max_length=255, description="Full name")
    nickname: Optional[str] = Field(None, max_length=100, description="Optional nickname")
    email: EmailStr = Field(..., description="Email address")
    password: str = Field(..., min_length=8, max_length=128, description="Password")
    cpf: str = Field(..., min_length=11, max_length=14, description="CPF (with or without formatting)")
    phone: str = Field(..., min_length=10, max_length=20, description="Phone number")

    @field_validator("cpf")
    @classmethod
    def validate_cpf(cls, v: str) -> str:
        """Remove formatting from CPF."""
        import re
        return re.sub(r"\D", "", v)


class LoginRequest(BaseModel):
    """Request schema for login."""

    email: EmailStr = Field(..., description="Email address")
    password: str = Field(..., description="Password")


class TokenResponse(BaseModel):
    """Response schema for authentication token."""

    access_token: str = Field(..., description="JWT access token")
    token_type: str = Field(default="bearer", description="Token type")
    user_id: str = Field(..., description="User UUID")
    role: str = Field(..., description="User role (client or admin)")
    name: str = Field(..., description="User name")


class RegisterResponse(BaseModel):
    """Response schema for registration."""

    id: str = Field(..., description="User UUID")
    email: str = Field(..., description="User email")
    name: str = Field(..., description="User name")
    message: str = Field(default="Registration successful. Please check your email to confirm your account.")


class ActivateAccountRequest(BaseModel):
    """Request schema for account activation (email confirmation)."""

    token: str = Field(
        ...,
        min_length=32,
        max_length=64,
        description="Activation token from confirmation email",
    )


class ActivateAccountResponse(BaseModel):
    """Response schema for account activation."""

    user_id: str = Field(..., description="Activated user UUID")
    email: str = Field(..., description="User email")
    name: str = Field(..., description="User name")
    message: str = Field(default="Account activated successfully")
