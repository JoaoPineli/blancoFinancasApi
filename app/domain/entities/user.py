"""Client entity - Domain model for platform clients."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from app.domain.value_objects.cpf import CPF
from app.domain.value_objects.email import Email


class UserStatus(Enum):
    """User status enumeration."""

    INVITED = "invited"  # User invited but not yet activated
    ACTIVE = "active"
    INACTIVE = "inactive"
    DEFAULTING = "defaulting"  # Inadimplente


class UserRole(Enum):
    """User role enumeration."""

    CLIENT = "client"
    ADMIN = "admin"


@dataclass
class User:
    """User entity representing a platform user.

    Encapsulates state and behavior for users.
    Invariants are validated in constructor and methods.
    """

    id: UUID
    cpf: Optional[CPF]  # Optional for invited users
    email: Email
    name: str
    password_hash: Optional[str]  # Optional for invited users
    role: UserRole
    status: UserStatus
    phone: Optional[str] = None
    nickname: Optional[str] = None
    plan_id: Optional[UUID] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    @classmethod
    def create(
        cls,
        cpf: CPF,
        email: Email,
        name: str,
        password_hash: str,
        role: UserRole = UserRole.CLIENT,
        phone: Optional[str] = None,
        nickname: Optional[str] = None,
        plan_id: Optional[UUID] = None,
    ) -> User:
        """Factory method to create a new User."""
        now = datetime.utcnow()
        return cls(
            id=uuid4(),
            cpf=cpf,
            email=email,
            name=name,
            password_hash=password_hash,
            role=role,
            status=UserStatus.ACTIVE,
            phone=phone,
            nickname=nickname,
            plan_id=plan_id,
            created_at=now,
            updated_at=now,
        )

    @classmethod
    def create_invited(
        cls,
        email: Email,
        name: str,
        role: UserRole = UserRole.CLIENT,
        plan_id: Optional[UUID] = None,
    ) -> User:
        """Factory method to create an invited user (no password, no CPF).

        Invited users must complete activation to set password, CPF, phone.
        """
        now = datetime.utcnow()
        return cls(
            id=uuid4(),
            cpf=None,
            email=email,
            name=name,
            password_hash=None,
            role=role,
            status=UserStatus.INVITED,
            phone=None,
            nickname=None,
            plan_id=plan_id,
            created_at=now,
            updated_at=now,
        )

    def activate(self) -> None:
        """Activate the user."""
        self.status = UserStatus.ACTIVE
        self.updated_at = datetime.utcnow()

    def complete_activation(
        self,
        cpf: CPF,
        password_hash: str,
        phone: str,
        nickname: Optional[str] = None,
    ) -> None:
        """Complete account activation for invited users.

        Sets password, CPF, phone, and optionally nickname.
        Transitions status from INVITED to ACTIVE.

        Raises:
            ValueError: If user is not in INVITED status.
        """
        if self.status != UserStatus.INVITED:
            raise ValueError("Only invited users can complete activation")

        self.cpf = cpf
        self.password_hash = password_hash
        self.phone = phone
        if nickname is not None:
            self.nickname = nickname
        self.status = UserStatus.ACTIVE
        self.updated_at = datetime.utcnow()

    def deactivate(self) -> None:
        """Deactivate the user."""
        self.status = UserStatus.INACTIVE
        self.updated_at = datetime.utcnow()

    def mark_as_defaulting(self) -> None:
        """Mark user as defaulting (inadimplente)."""
        self.status = UserStatus.DEFAULTING
        self.updated_at = datetime.utcnow()

    def update_email(self, email: Email) -> None:
        """Update user email."""
        self.email = email
        self.updated_at = datetime.utcnow()

    def update_phone(self, phone: str) -> None:
        """Update user phone."""
        self.phone = phone
        self.updated_at = datetime.utcnow()

    def update_password(self, password_hash: str) -> None:
        """Update user password hash."""
        self.password_hash = password_hash
        self.updated_at = datetime.utcnow()

    def is_admin(self) -> bool:
        """Check if user has admin role."""
        return self.role == UserRole.ADMIN

    def is_active(self) -> bool:
        """Check if user is active."""
        return self.status == UserStatus.ACTIVE

    def is_invited(self) -> bool:
        """Check if user is in invited status (pending activation)."""
        return self.status == UserStatus.INVITED

    def update_nickname(self, nickname: str) -> None:
        """Update user nickname."""
        self.nickname = nickname
        self.updated_at = datetime.utcnow()

    def set_cpf(self, cpf: CPF) -> None:
        """Set user CPF."""
        self.cpf = cpf
        self.updated_at = datetime.utcnow()
