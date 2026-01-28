"""CPF value object for Brazilian individual taxpayer registry."""

from __future__ import annotations

import re

from app.domain.exceptions import InvalidCPFError


class CPF:
    """Immutable value object representing a Brazilian CPF.

    Validates CPF format and check digits.
    """

    def __init__(self, value: str) -> None:
        """Initialize CPF with validation.

        Args:
            value: CPF string (with or without formatting)

        Raises:
            InvalidCPFError: If CPF is invalid
        """
        # Remove non-numeric characters
        cleaned = re.sub(r"\D", "", value)

        if not self._is_valid(cleaned):
            raise InvalidCPFError(value)

        self._value = cleaned

    @staticmethod
    def _is_valid(cpf: str) -> bool:
        """Validate CPF check digits."""
        if len(cpf) != 11:
            return False

        # Check for known invalid CPFs (all same digits)
        if cpf == cpf[0] * 11:
            return False

        # Calculate first check digit
        total = sum(int(cpf[i]) * (10 - i) for i in range(9))
        remainder = total % 11
        first_digit = 0 if remainder < 2 else 11 - remainder

        if int(cpf[9]) != first_digit:
            return False

        # Calculate second check digit
        total = sum(int(cpf[i]) * (11 - i) for i in range(10))
        remainder = total % 11
        second_digit = 0 if remainder < 2 else 11 - remainder

        return int(cpf[10]) == second_digit

    @property
    def value(self) -> str:
        """Get CPF without formatting."""
        return self._value

    @property
    def formatted(self) -> str:
        """Get CPF with formatting (XXX.XXX.XXX-XX)."""
        return f"{self._value[:3]}.{self._value[3:6]}.{self._value[6:9]}-{self._value[9:]}"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CPF):
            return NotImplemented
        return self._value == other._value

    def __hash__(self) -> int:
        return hash(self._value)

    def __repr__(self) -> str:
        return f"CPF({self.formatted})"

    def __str__(self) -> str:
        return self.formatted
