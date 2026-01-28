"""Authentication schemas."""

from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator


class RegisterRequest(BaseModel):
    """Request schema for user registration."""

    cpf: str = Field(..., min_length=11, max_length=14, description="CPF (with or without formatting)")
    email: EmailStr = Field(..., description="Email address")
    name: str = Field(..., min_length=2, max_length=255, description="Full name")
    password: str = Field(..., min_length=8, max_length=128, description="Password")
    phone: Optional[str] = Field(None, max_length=20, description="Phone number")

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
    cpf: str = Field(..., description="User CPF")
    email: str = Field(..., description="User email")
    name: str = Field(..., description="User name")
    message: str = Field(default="Registration successful")
