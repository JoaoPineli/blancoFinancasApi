"""Fundo Garantidor Calculator - Domain service for Fundo Garantidor calculations.

Logic for calculating Fundo Garantidor retention (1% to 1.3%).
This logic is isolated and testable independently of the API.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Tuple

from app.domain.value_objects.money import Money


class FundoGarantidorCalculator:
    """Domain service for calculating Fundo Garantidor retention.

    Fundo Garantidor is a retention fund that ranges from 1% to 1.3%
    of each installment, configurable per plan.
    """

    PRECISION = Decimal("0.01")
    ROUNDING = ROUND_HALF_UP

    # Allowed percentage range
    MIN_PERCENTAGE = Decimal("1.0")
    MAX_PERCENTAGE = Decimal("1.3")

    def __init__(self, percentage: Decimal) -> None:
        """Initialize calculator with configured percentage.

        Args:
            percentage: Fundo Garantidor percentage (1.0 to 1.3)

        Raises:
            ValueError: If percentage is outside allowed range
        """
        if not (self.MIN_PERCENTAGE <= percentage <= self.MAX_PERCENTAGE):
            raise ValueError(
                f"Fundo Garantidor percentage must be between "
                f"{self.MIN_PERCENTAGE}% and {self.MAX_PERCENTAGE}%"
            )
        self._percentage = percentage

    def calculate(self, installment_amount: Money) -> Money:
        """Calculate Fundo Garantidor retention for an installment.

        Args:
            installment_amount: The installment amount

        Returns:
            Fundo Garantidor retention amount
        """
        return installment_amount.percentage(self._percentage)

    def split_installment(self, installment_amount: Money) -> Tuple[Money, Money]:
        """Split installment into investment and Fundo Garantidor portions.

        Args:
            installment_amount: Total installment amount

        Returns:
            Tuple of (investment_amount, fundo_garantidor_amount)
        """
        fundo_amount = self.calculate(installment_amount)
        investment_amount = installment_amount.subtract(fundo_amount)
        return investment_amount, fundo_amount

    @property
    def percentage(self) -> Decimal:
        """Get configured percentage."""
        return self._percentage
