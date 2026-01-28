"""Poupança Yield Calculator - Domain service for yield calculations.

CRITICAL: This service MUST:
- Respect deposit anniversary dates
- Apply daily accumulation (not naive monthly multiplication)
- Be deterministic and pure (no I/O)
- Use explicit and configurable TR and Selic-based rules

Official Poupança Yield Source: BCB SGS API
- SGS 25: Depósitos de poupança (até 03/05/2012)
- SGS 195: Depósitos de poupança (a partir de 04/05/2012)
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import List, Optional

from app.domain.entities.yield_data import SGSSeries, YieldData
from app.domain.exceptions import YieldCalculationError
from app.domain.value_objects.money import Money


@dataclass
class YieldCalculationResult:
    """Result of yield calculation with audit data."""

    principal: Money
    yield_amount: Money
    final_amount: Money
    start_date: date
    end_date: date
    series_id: SGSSeries
    effective_rate: Decimal
    days_accrued: int


class PoupancaYieldCalculator:
    """Domain service for calculating poupança-based yields.

    This calculator:
    - Respects deposit anniversary dates (dia de aniversário)
    - Applies daily accumulation correctly
    - Is deterministic and pure (requires pre-fetched yield data)
    - Uses explicit rounding (ROUND_HALF_UP)

    Poupança rules (post May 4, 2012):
    - If Selic > 8.5% p.a.: 0.5% per month + TR
    - If Selic <= 8.5% p.a.: 70% of Selic + TR

    Yield is credited monthly on the anniversary date of the deposit.
    """

    PRECISION = Decimal("0.00000001")
    DISPLAY_PRECISION = Decimal("0.01")
    ROUNDING = ROUND_HALF_UP

    def __init__(self, yield_data: List[YieldData]) -> None:
        """Initialize calculator with pre-fetched yield data.

        Args:
            yield_data: List of BCB yield data for calculation period
        """
        self._yield_data = {
            (data.reference_date, data.series_id): data.rate
            for data in yield_data
        }
        self._yield_data_list = yield_data

    def calculate_yield(
        self,
        principal: Money,
        deposit_date: date,
        calculation_date: date,
    ) -> YieldCalculationResult:
        """Calculate yield for a deposit from deposit date to calculation date.

        Yield is only credited on anniversary dates (same day of month as deposit).

        Args:
            principal: Initial deposit amount
            deposit_date: Date of the deposit
            calculation_date: Date to calculate yield up to

        Returns:
            YieldCalculationResult with all audit data

        Raises:
            YieldCalculationError: If yield data is missing or calculation fails
        """
        if calculation_date < deposit_date:
            raise YieldCalculationError("Calculation date cannot be before deposit date")

        if principal.is_zero():
            return YieldCalculationResult(
                principal=principal,
                yield_amount=Money.zero(),
                final_amount=principal,
                start_date=deposit_date,
                end_date=calculation_date,
                series_id=YieldData.get_series_for_date(deposit_date),
                effective_rate=Decimal("0"),
                days_accrued=0,
            )

        # Determine the appropriate SGS series
        series_id = YieldData.get_series_for_date(deposit_date)

        # Calculate complete months between dates
        complete_months = self._calculate_complete_months(deposit_date, calculation_date)

        if complete_months == 0:
            return YieldCalculationResult(
                principal=principal,
                yield_amount=Money.zero(),
                final_amount=principal,
                start_date=deposit_date,
                end_date=calculation_date,
                series_id=series_id,
                effective_rate=Decimal("0"),
                days_accrued=(calculation_date - deposit_date).days,
            )

        # Calculate accumulated yield using compound interest
        accumulated_rate = Decimal("1")
        current_date = deposit_date

        for _ in range(complete_months):
            next_anniversary = self._get_next_anniversary(current_date)

            # Get monthly rate from stored data
            monthly_rate = self._get_monthly_rate(current_date, series_id)
            if monthly_rate is None:
                raise YieldCalculationError(
                    f"Missing yield data for {current_date} (series {series_id.value})"
                )

            accumulated_rate *= (Decimal("1") + monthly_rate)
            current_date = next_anniversary

        # Calculate effective rate and yield
        effective_rate = accumulated_rate - Decimal("1")
        yield_decimal = principal.amount * effective_rate
        yield_rounded = yield_decimal.quantize(self.DISPLAY_PRECISION, self.ROUNDING)
        yield_amount = Money(str(yield_rounded))

        final_amount = principal.add(yield_amount)

        return YieldCalculationResult(
            principal=principal,
            yield_amount=yield_amount,
            final_amount=final_amount,
            start_date=deposit_date,
            end_date=calculation_date,
            series_id=series_id,
            effective_rate=effective_rate.quantize(self.PRECISION, self.ROUNDING),
            days_accrued=(calculation_date - deposit_date).days,
        )

    def _calculate_complete_months(self, start_date: date, end_date: date) -> int:
        """Calculate complete months based on anniversary dates.

        A month is only complete when the anniversary date is reached.

        Args:
            start_date: Start date (deposit date)
            end_date: End date (calculation date)

        Returns:
            Number of complete months
        """
        if end_date < start_date:
            return 0

        months = (end_date.year - start_date.year) * 12 + (end_date.month - start_date.month)

        # Check if we've passed the anniversary day in the end month
        anniversary_day = min(start_date.day, self._days_in_month(end_date.year, end_date.month))
        if end_date.day < anniversary_day:
            months -= 1

        return max(0, months)

    def _get_next_anniversary(self, current_date: date) -> date:
        """Get the next anniversary date from current date.

        Args:
            current_date: Current date

        Returns:
            Next anniversary date
        """
        year = current_date.year
        month = current_date.month + 1

        if month > 12:
            month = 1
            year += 1

        day = min(current_date.day, self._days_in_month(year, month))
        return date(year, month, day)

    def _get_monthly_rate(self, reference_date: date, series_id: SGSSeries) -> Optional[Decimal]:
        """Get monthly rate from stored yield data.

        Args:
            reference_date: Reference date for the rate
            series_id: SGS series to use

        Returns:
            Monthly rate as decimal, or None if not found
        """
        return self._yield_data.get((reference_date, series_id))

    @staticmethod
    def _days_in_month(year: int, month: int) -> int:
        """Get number of days in a month."""
        if month == 12:
            next_month = date(year + 1, 1, 1)
        else:
            next_month = date(year, month + 1, 1)
        return (next_month - date(year, month, 1)).days
