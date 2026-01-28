"""Invitation DTOs."""

from dataclasses import dataclass
from typing import Optional
from uuid import UUID


@dataclass
class InviteUserInput:
    """Input for inviting a new user."""

    name: str
    email: str
    plan_id: Optional[str] = None


@dataclass
class InviteUserResult:
    """Result of invite operation.

    Note: activation_token is NOT included here.
    The token is sent via email only and never exposed in API responses.
    """

    user_id: UUID
    email: str
    name: str


@dataclass
class ActivateAccountInput:
    """Input for account activation."""

    token: str
    password: str
    cpf: str
    phone: str
    nickname: Optional[str] = None


@dataclass
class ActivateAccountResult:
    """Result of activation operation."""

    user_id: UUID
    email: str
    name: str
