"""Registration DTOs."""

from dataclasses import dataclass
from typing import Optional
from uuid import UUID


@dataclass
class RegisterUserInput:
    """Input for self-service user registration."""

    name: str
    email: str
    password: str
    cpf: str
    phone: str
    nickname: Optional[str] = None


@dataclass
class RegisterUserResult:
    """Result of registration operation."""

    user_id: UUID
    email: str
    name: str


@dataclass
class ActivateAccountInput:
    """Input for account activation (email confirmation)."""

    token: str


@dataclass
class ActivateAccountResult:
    """Result of activation operation."""

    user_id: UUID
    email: str
    name: str
