"""UserToken entity - Domain model for user tokens (activation, password reset)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4


class TokenType(Enum):
    """Token type enumeration."""

    ACTIVATION = "activation"
    PASSWORD_RESET = "password_reset"


@dataclass
class UserToken:
    """UserToken entity representing a single-use token for user operations.

    Tokens are cryptographically secure and stored as hashes only.
    Each token has explicit expiration and can only be used once.
    """

    id: UUID
    user_id: UUID
    token_hash: str
    token_type: TokenType
    expires_at: datetime
    used_at: Optional[datetime]
    created_at: datetime = field(default_factory=datetime.utcnow)

    @classmethod
    def create(
        cls,
        user_id: UUID,
        token_hash: str,
        token_type: TokenType,
        expires_in_hours: int = 48,
    ) -> UserToken:
        """Factory method to create a new UserToken.

        Args:
            user_id: ID of the user this token belongs to.
            token_hash: Hash of the token (never store raw token).
            token_type: Type of token (ACTIVATION or PASSWORD_RESET).
            expires_in_hours: Hours until token expires (default 48).

        Returns:
            New UserToken entity.
        """
        now = datetime.utcnow()
        return cls(
            id=uuid4(),
            user_id=user_id,
            token_hash=token_hash,
            token_type=token_type,
            expires_at=now + timedelta(hours=expires_in_hours),
            used_at=None,
            created_at=now,
        )

    def is_expired(self) -> bool:
        """Check if token has expired."""
        return datetime.utcnow() > self.expires_at

    def is_used(self) -> bool:
        """Check if token has been used."""
        return self.used_at is not None

    def is_valid(self) -> bool:
        """Check if token is valid (not expired and not used)."""
        return not self.is_expired() and not self.is_used()

    def mark_as_used(self) -> None:
        """Mark the token as used.

        Raises:
            ValueError: If token is already used.
        """
        if self.is_used():
            raise ValueError("Token has already been used")
        self.used_at = datetime.utcnow()
