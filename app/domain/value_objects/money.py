"""Money value object for financial calculations.

CRITICAL: Never use float for monetary values.
Uses Python's decimal.Decimal for all calculations.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Union

from app.domain.exceptions import InvalidMoneyError


class Money:
    """Immutable value object representing monetary values.

    All calculations use Decimal with explicit rounding.
    Internal storage is in cents (integer) for database compatibility.
    """

    # Precision for calculations (4 decimal places for intermediate calculations)
    CALCULATION_PRECISION = Decimal("0.0001")
    # Precision for display/storage (2 decimal places)
    DISPLAY_PRECISION = Decimal("0.01")
    # Rounding strategy
    ROUNDING = ROUND_HALF_UP

    def __init__(self, amount: Union[int, str, Decimal]) -> None:
        """Initialize Money from cents (int) or decimal string.

        Args:
            amount: Amount in cents (int) or as decimal string (e.g., "100.50")
        """
        if isinstance(amount, int):
            # Assume amount is in cents
            self._cents = amount
        elif isinstance(amount, (str, Decimal)):
            # Parse decimal string and convert to cents
            try:
                decimal_amount = Decimal(str(amount))
                if decimal_amount < 0:
                    raise InvalidMoneyError("Money amount cannot be negative")
                # Round to 2 decimal places and convert to cents
                rounded = decimal_amount.quantize(self.DISPLAY_PRECISION, self.ROUNDING)
                self._cents = int(rounded * 100)
            except Exception as e:
                if isinstance(e, InvalidMoneyError):
                    raise
                raise InvalidMoneyError(f"Invalid money amount: {amount}") from e
        else:
            raise InvalidMoneyError(f"Invalid money type: {type(amount)}")

    @classmethod
    def from_cents(cls, cents: int) -> Money:
        """Create Money from cents value."""
        if cents < 0:
            raise InvalidMoneyError("Money amount cannot be negative")
        return cls(cents)

    @classmethod
    def zero(cls) -> Money:
        """Create zero Money."""
        return cls(0)

    @property
    def cents(self) -> int:
        """Get amount in cents (for database storage)."""
        return self._cents

    @property
    def amount(self) -> Decimal:
        """Get amount as Decimal (for calculations and display)."""
        return Decimal(self._cents) / Decimal(100)

    def add(self, other: Money) -> Money:
        """Add two Money values."""
        return Money.from_cents(self._cents + other._cents)

    def subtract(self, other: Money) -> Money:
        """Subtract Money value."""
        result = self._cents - other._cents
        if result < 0:
            raise InvalidMoneyError("Subtraction would result in negative amount")
        return Money.from_cents(result)

    def multiply(self, factor: Union[int, Decimal, str]) -> Money:
        """Multiply Money by a factor."""
        decimal_factor = Decimal(str(factor))
        result = self.amount * decimal_factor
        rounded = result.quantize(self.DISPLAY_PRECISION, self.ROUNDING)
        return Money(str(rounded))

    def percentage(self, percent: Union[Decimal, str]) -> Money:
        """Calculate percentage of Money."""
        decimal_percent = Decimal(str(percent)) / Decimal(100)
        return self.multiply(decimal_percent)

    def is_zero(self) -> bool:
        """Check if amount is zero."""
        return self._cents == 0

    def is_greater_than(self, other: Money) -> bool:
        """Check if this amount is greater than other."""
        return self._cents > other._cents

    def is_less_than(self, other: Money) -> bool:
        """Check if this amount is less than other."""
        return self._cents < other._cents

    def is_greater_or_equal(self, other: Money) -> bool:
        """Check if this amount is greater than or equal to other."""
        return self._cents >= other._cents

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        return self._cents == other._cents

    def __hash__(self) -> int:
        return hash(self._cents)

    def __repr__(self) -> str:
        return f"Money({self.amount})"

    def __str__(self) -> str:
        return f"R$ {self.amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
