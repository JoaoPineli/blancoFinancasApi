"""Tests for domain services."""

import pytest
from datetime import date
from decimal import Decimal

from app.domain.services.fundo_garantidor_calculator import FundoGarantidorCalculator
from app.domain.services.installment_calculator import InstallmentCalculator
from app.domain.services.poupanca_yield_calculator import PoupancaYieldCalculator
from app.domain.entities.yield_data import SGSSeries, YieldData
from app.domain.value_objects.money import Money


class TestFundoGarantidorCalculator:
    """Test Fundo Garantidor Calculator."""

    def test_calculate_at_minimum_percentage(self):
        """Test calculation at 1.0% (minimum)."""
        calculator = FundoGarantidorCalculator(Decimal("1.0"))
        amount = Money("1000.00")
        result = calculator.calculate(amount)
        assert result.cents == 1000  # R$ 10.00

    def test_calculate_at_maximum_percentage(self):
        """Test calculation at 1.3% (maximum)."""
        calculator = FundoGarantidorCalculator(Decimal("1.3"))
        amount = Money("1000.00")
        result = calculator.calculate(amount)
        assert result.cents == 1300  # R$ 13.00

    def test_split_installment(self):
        """Test splitting installment into investment and fundo."""
        calculator = FundoGarantidorCalculator(Decimal("1.0"))
        amount = Money("1000.00")
        investment, fundo = calculator.split_installment(amount)
        
        assert fundo.cents == 1000  # R$ 10.00
        assert investment.cents == 99000  # R$ 990.00

    def test_invalid_percentage_below_minimum_raises_error(self):
        """Test that percentage below 1.0% raises error."""
        with pytest.raises(ValueError):
            FundoGarantidorCalculator(Decimal("0.5"))

    def test_invalid_percentage_above_maximum_raises_error(self):
        """Test that percentage above 1.3% raises error."""
        with pytest.raises(ValueError):
            FundoGarantidorCalculator(Decimal("2.0"))


class TestInstallmentCalculator:
    """Test Installment Calculator."""

    def test_first_installment_breakdown(self):
        """Test first installment includes fees, insurance, and fundo."""
        calculator = InstallmentCalculator(
            fundo_garantidor_percentage=Decimal("1.0"),
            fee_percentage=Decimal("2.0"),
            insurance_percentage=Decimal("1.0"),
        )
        amount = Money("1000.00")
        breakdown = calculator.calculate_first_installment(amount)

        # Fee: 2% = R$ 20.00
        assert breakdown.fee_amount.cents == 2000
        # Insurance: 1% = R$ 10.00
        assert breakdown.insurance_amount.cents == 1000
        # Fundo: 1% = R$ 10.00
        assert breakdown.fundo_garantidor_amount.cents == 1000
        # Investment: R$ 1000 - R$ 40 = R$ 960.00
        assert breakdown.investment_amount.cents == 96000

    def test_subsequent_installment_breakdown(self):
        """Test subsequent installments include only investment and fundo."""
        calculator = InstallmentCalculator(
            fundo_garantidor_percentage=Decimal("1.0"),
        )
        amount = Money("1000.00")
        breakdown = calculator.calculate_subsequent_installment(amount)

        # Fundo: 1% = R$ 10.00
        assert breakdown.fundo_garantidor_amount.cents == 1000
        # Investment: R$ 990.00
        assert breakdown.investment_amount.cents == 99000


class TestPoupancaYieldCalculator:
    """Test Poupança Yield Calculator."""

    def test_zero_principal_returns_zero_yield(self):
        """Test that zero principal returns zero yield."""
        calculator = PoupancaYieldCalculator([])
        principal = Money.zero()
        
        result = calculator.calculate_yield(
            principal=principal,
            deposit_date=date(2024, 1, 15),
            calculation_date=date(2024, 2, 15),
        )
        
        assert result.yield_amount.is_zero()
        assert result.final_amount.is_zero()

    def test_calculation_before_first_anniversary_returns_zero(self):
        """Test that yield before first anniversary is zero."""
        calculator = PoupancaYieldCalculator([])
        principal = Money("1000.00")
        
        result = calculator.calculate_yield(
            principal=principal,
            deposit_date=date(2024, 1, 15),
            calculation_date=date(2024, 2, 10),  # Before anniversary
        )
        
        assert result.yield_amount.is_zero()
        assert result.days_accrued == 26

    def test_yield_calculation_with_data(self):
        """Test yield calculation with stored BCB data."""
        # Create mock yield data
        yield_data = [
            YieldData.create(
                series_id=SGSSeries.POST_2012,
                reference_date=date(2024, 1, 15),
                rate=Decimal("0.005"),  # 0.5% monthly
            ),
        ]
        
        calculator = PoupancaYieldCalculator(yield_data)
        principal = Money("10000.00")
        
        result = calculator.calculate_yield(
            principal=principal,
            deposit_date=date(2024, 1, 15),
            calculation_date=date(2024, 2, 15),
        )
        
        # 0.5% of R$ 10,000 = R$ 50.00
        assert result.yield_amount.cents == 5000
        assert result.series_id == SGSSeries.POST_2012

    def test_calculation_date_before_deposit_raises_error(self):
        """Test that calculation date before deposit raises error."""
        from app.domain.exceptions import YieldCalculationError
        
        calculator = PoupancaYieldCalculator([])
        principal = Money("1000.00")
        
        with pytest.raises(YieldCalculationError):
            calculator.calculate_yield(
                principal=principal,
                deposit_date=date(2024, 2, 15),
                calculation_date=date(2024, 1, 15),
            )

    def test_series_selection_pre_2012(self):
        """Test correct series selection for pre-2012 dates."""
        from app.domain.entities.yield_data import YieldData, SGSSeries
        
        # Date before May 4, 2012
        series = YieldData.get_series_for_date(date(2012, 5, 3))
        assert series == SGSSeries.PRE_2012

    def test_series_selection_post_2012(self):
        """Test correct series selection for post-2012 dates."""
        from app.domain.entities.yield_data import YieldData, SGSSeries

        # Date on or after May 4, 2012
        series = YieldData.get_series_for_date(date(2012, 5, 4))
        assert series == SGSSeries.POST_2012

    def test_multi_month_compound_yield(self):
        """Test compound yield over multiple months."""
        yield_data = [
            YieldData.create(
                series_id=SGSSeries.POST_2012,
                reference_date=date(2024, 1, 15),
                rate=Decimal("0.005"),  # 0.5%
            ),
            YieldData.create(
                series_id=SGSSeries.POST_2012,
                reference_date=date(2024, 2, 15),
                rate=Decimal("0.005"),  # 0.5%
            ),
        ]

        calculator = PoupancaYieldCalculator(yield_data)
        principal = Money("10000.00")

        result = calculator.calculate_yield(
            principal=principal,
            deposit_date=date(2024, 1, 15),
            calculation_date=date(2024, 3, 15),
        )

        # effective_rate = (1.005)^2 - 1 = 0.010025
        # yield = R$10,000 * 0.010025 = R$100.25 → 10025 cents
        assert result.yield_amount.cents == 10025
        assert result.series_id == SGSSeries.POST_2012

    def test_yield_delta_idempotency(self):
        """Test that delta calculation correctly produces zero on repeated dates."""
        yield_data = [
            YieldData.create(
                series_id=SGSSeries.POST_2012,
                reference_date=date(2024, 1, 15),
                rate=Decimal("0.005"),
            ),
        ]
        calculator = PoupancaYieldCalculator(yield_data)
        principal = Money("10000.00")

        # First call: calculate yield through Feb 15
        result_total = calculator.calculate_yield(
            principal=principal,
            deposit_date=date(2024, 1, 15),
            calculation_date=date(2024, 2, 15),
        )
        # Second call: previously credited = same date → delta = 0
        result_prev = calculator.calculate_yield(
            principal=principal,
            deposit_date=date(2024, 1, 15),
            calculation_date=date(2024, 2, 15),
        )
        delta = result_total.yield_amount.cents - result_prev.yield_amount.cents
        assert delta == 0

    def test_yield_delta_new_month(self):
        """Test that delta yields only the increment for the new month."""
        yield_data = [
            YieldData.create(
                series_id=SGSSeries.POST_2012,
                reference_date=date(2024, 1, 15),
                rate=Decimal("0.005"),
            ),
            YieldData.create(
                series_id=SGSSeries.POST_2012,
                reference_date=date(2024, 2, 15),
                rate=Decimal("0.005"),
            ),
        ]
        calculator = PoupancaYieldCalculator(yield_data)
        principal = Money("10000.00")

        # Previously credited: 1 month
        prev_result = calculator.calculate_yield(
            principal=principal,
            deposit_date=date(2024, 1, 15),
            calculation_date=date(2024, 2, 15),
        )
        # Total: 2 months
        total_result = calculator.calculate_yield(
            principal=principal,
            deposit_date=date(2024, 1, 15),
            calculation_date=date(2024, 3, 15),
        )

        delta = total_result.yield_amount.cents - prev_result.yield_amount.cents
        # Month 2 yield on growing principal: 10000 * 1.005 * 0.005 = 50.25 → 5025 cents
        assert delta == 5025

    def test_rounding_explicit_half_up(self):
        """Test that rounding is ROUND_HALF_UP (never truncated or floored)."""
        yield_data = [
            YieldData.create(
                series_id=SGSSeries.POST_2012,
                reference_date=date(2024, 1, 15),
                rate=Decimal("0.00497"),  # 0.497% — yields sub-cent amount
            ),
        ]
        calculator = PoupancaYieldCalculator(yield_data)
        # R$ 100.00 * 0.00497 = R$ 0.497 → rounds to R$ 0.50 (ROUND_HALF_UP)
        principal = Money("100.00")
        result = calculator.calculate_yield(
            principal=principal,
            deposit_date=date(2024, 1, 15),
            calculation_date=date(2024, 2, 15),
        )
        assert result.yield_amount.cents == 50  # R$ 0.50

    def test_series_boundary_cutoff_date(self):
        """Test series selection exactly on the cutoff date (May 4, 2012)."""
        assert YieldData.get_series_for_date(date(2012, 5, 3)) == SGSSeries.PRE_2012
        assert YieldData.get_series_for_date(date(2012, 5, 4)) == SGSSeries.POST_2012
        assert YieldData.get_series_for_date(date(2012, 5, 5)) == SGSSeries.POST_2012

    def test_missing_yield_data_raises_error(self):
        """Test that missing BCB data raises YieldCalculationError (fail loud)."""
        from app.domain.exceptions import YieldCalculationError

        # No yield data at all — should raise when a complete month is present
        calculator = PoupancaYieldCalculator([])
        principal = Money("1000.00")

        with pytest.raises(YieldCalculationError):
            calculator.calculate_yield(
                principal=principal,
                deposit_date=date(2024, 1, 15),
                calculation_date=date(2024, 2, 15),  # 1 complete month
            )

    def test_zero_yield_before_first_anniversary(self):
        """Yield is zero if calculation_date has not reached the first anniversary."""
        calculator = PoupancaYieldCalculator([])
        principal = Money("5000.00")

        result = calculator.calculate_yield(
            principal=principal,
            deposit_date=date(2024, 1, 15),
            calculation_date=date(2024, 2, 14),  # one day before anniversary
        )
        assert result.yield_amount.is_zero()
        assert result.days_accrued == 30
