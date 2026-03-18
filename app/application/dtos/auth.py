"""Authentication DTOs."""

from dataclasses import dataclass
from uuid import UUID

from app.domain.entities.user import UserRole


@dataclass
class LoginResult:
    """Result of login operation."""

    access_token: str
    token_type: str
    user_id: UUID
    role: UserRole
    name: str


@dataclass
class LoginInput:
    """Input for login."""

    email: str
    password: str
