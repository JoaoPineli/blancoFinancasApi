"""Installment Calculator - Domain service for installment logic.

Handles the logic for splitting installments:
- First installment: Fees + Insurance + Fundo Garantidor
- Subsequent installments: Investment + Fundo Garantidor
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from app.domain.services.fundo_garantidor_calculator import FundoGarantidorCalculator
from app.domain.value_objects.money import Money


@dataclass
class FirstInstallmentBreakdown:
    """Breakdown of the first installment."""

    total: Money
    fee_amount: Money
    insurance_amount: Money
    fundo_garantidor_amount: Money
    investment_amount: Money  # Remaining after fees and insurance


@dataclass
class SubsequentInstallmentBreakdown:
    """Breakdown of subsequent installments."""

    total: Money
    fundo_garantidor_amount: Money
    investment_amount: Money


class InstallmentCalculator:
    """Domain service for calculating installment breakdowns.

    First installment logic: Fees + Insurance + Fundo Garantidor
    Subsequent installment logic: Investment + Fundo Garantidor
    """

    PRECISION = Decimal("0.01")
    ROUNDING = ROUND_HALF_UP

    # Default fee and insurance percentages (configurable)
    DEFAULT_FEE_PERCENTAGE = Decimal("2.0")  # 2% fee
    DEFAULT_INSURANCE_PERCENTAGE = Decimal("1.0")  # 1% insurance

    def __init__(
        self,
        fundo_garantidor_percentage: Decimal,
        fee_percentage: Optional[Decimal] = None,
        insurance_percentage: Optional[Decimal] = None,
    ) -> None:
        """Initialize calculator with plan-specific percentages.

        Args:
            fundo_garantidor_percentage: Fundo Garantidor percentage (1.0 to 1.3)
            fee_percentage: Fee percentage for first installment
            insurance_percentage: Insurance percentage for first installment
        """
        self._fundo_calculator = FundoGarantidorCalculator(fundo_garantidor_percentage)
        self._fee_percentage = fee_percentage or self.DEFAULT_FEE_PERCENTAGE
        self._insurance_percentage = insurance_percentage or self.DEFAULT_INSURANCE_PERCENTAGE

    def calculate_first_installment(
        self, installment_amount: Money
    ) -> FirstInstallmentBreakdown:
        """Calculate breakdown for the first installment.

        First installment includes fees, insurance, and Fundo Garantidor.
        The remaining goes to investment.

        Args:
            installment_amount: Total first installment amount

        Returns:
            FirstInstallmentBreakdown with all components
        """
        fee_amount = installment_amount.percentage(self._fee_percentage)
        insurance_amount = installment_amount.percentage(self._insurance_percentage)
        fundo_amount = self._fundo_calculator.calculate(installment_amount)

        # Investment is what remains after fees, insurance, and fundo
        deductions = fee_amount.add(insurance_amount).add(fundo_amount)
        investment_amount = installment_amount.subtract(deductions)

        return FirstInstallmentBreakdown(
            total=installment_amount,
            fee_amount=fee_amount,
            insurance_amount=insurance_amount,
            fundo_garantidor_amount=fundo_amount,
            investment_amount=investment_amount,
        )

    def calculate_subsequent_installment(
        self, installment_amount: Money
    ) -> SubsequentInstallmentBreakdown:
        """Calculate breakdown for subsequent installments.

        Subsequent installments include only investment and Fundo Garantidor.

        Args:
            installment_amount: Total installment amount

        Returns:
            SubsequentInstallmentBreakdown with all components
        """
        investment_amount, fundo_amount = self._fundo_calculator.split_installment(
            installment_amount
        )

        return SubsequentInstallmentBreakdown(
            total=installment_amount,
            fundo_garantidor_amount=fundo_amount,
            investment_amount=investment_amount,
        )
