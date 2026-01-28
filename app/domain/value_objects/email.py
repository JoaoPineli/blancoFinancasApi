"""Email value object."""

from __future__ import annotations

import re

from app.domain.exceptions import InvalidEmailError


class Email:
    """Immutable value object representing an email address."""

    # Simple but effective email regex
    EMAIL_PATTERN = re.compile(
        r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    )

    def __init__(self, value: str) -> None:
        """Initialize Email with validation.

        Args:
            value: Email address string

        Raises:
            InvalidEmailError: If email format is invalid
        """
        if not value or not self.EMAIL_PATTERN.match(value):
            raise InvalidEmailError(value)

        self._value = value.lower().strip()

    @property
    def value(self) -> str:
        """Get email address."""
        return self._value

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Email):
            return NotImplemented
        return self._value == other._value

    def __hash__(self) -> int:
        return hash(self._value)

    def __repr__(self) -> str:
        return f"Email({self._value})"

    def __str__(self) -> str:
        return self._value
