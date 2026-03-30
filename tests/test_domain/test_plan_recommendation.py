"""Tests for PlanRecommendationService."""

import pytest
from decimal import Decimal
from uuid import uuid4

from app.domain.entities.plan import Plan
from app.domain.services.plan_recommendation_service import (
    PlanRecommendationService,
    RecommendationPreference,
)


def _make_plan(
    min_value_cents: int = 100_00,
    max_value_cents: int | None = 1_000_000_00,
    min_duration_months: int = 6,
    max_duration_months: int | None = 60,
    admin_tax_value_cents: int = 50_00,
    insurance_percent: Decimal = Decimal("1.0"),
    guarantee_fund_percent_1: Decimal = Decimal("1.0"),
    guarantee_fund_percent_2: Decimal = Decimal("1.3"),
    guarantee_fund_threshold_cents: int = 500_00,
    active: bool = True,
    title: str = "Plano Teste",
) -> Plan:
    """Helper to create a plan for testing."""
    return Plan.create(
        title=title,
        description="Plano de teste",
        min_value_cents=min_value_cents,
        max_value_cents=max_value_cents,
        min_duration_months=min_duration_months,
        max_duration_months=max_duration_months,
        admin_tax_value_cents=admin_tax_value_cents,
        insurance_percent=insurance_percent,
        guarantee_fund_percent_1=guarantee_fund_percent_1,
        guarantee_fund_percent_2=guarantee_fund_percent_2,
        guarantee_fund_threshold_cents=guarantee_fund_threshold_cents,
        active=active,
    )


class TestPlanRecommendationService:
    """Tests for PlanRecommendationService."""

    def setup_method(self):
        """Set up test fixtures."""
        self.service = PlanRecommendationService()

    # ----------------------------------------------------------------
    # Scenario 1: Successful recommendation with FEWER_PAYMENTS
    # ----------------------------------------------------------------
    def test_recommend_fewer_payments_returns_moderate_count(self):
        """With FEWER_PAYMENTS preference, the algorithm should pick
        a moderate deposit count near the 25th percentile — fewer payments
        but not the absolute minimum.
        """
        plan = _make_plan(
            min_value_cents=1_000_00,
            max_value_cents=100_000_00,
            min_duration_months=6,
            max_duration_months=60,
            admin_tax_value_cents=50_00,
            insurance_percent=Decimal("1.0"),
            guarantee_fund_percent_1=Decimal("1.0"),
            guarantee_fund_threshold_cents=500_00,
            guarantee_fund_percent_2=Decimal("1.3"),
        )

        target = 30_000_00  # R$ 30,000
        result = self.service.recommend(
            plans=[plan],
            target_amount_cents=target,
            preference=RecommendationPreference.FEWER_PAYMENTS,
        )

        assert result is not None
        # Must not pick the extreme minimum
        assert result.deposit_count > plan.min_duration_months
        # Must stay in the shorter half of the range (below midpoint)
        midpoint = (plan.min_duration_months + plan.max_duration_months) // 2
        assert result.deposit_count < midpoint
        assert result.monthly_amount_cents > 0
        assert result.total_cost_cents > 0

        # Verify cost breakdown makes sense:
        assert result.admin_tax_value_cents == 50_00
        assert result.insurance_cost_cents > 0
        assert result.guarantee_fund_cost_cents > 0

    # ----------------------------------------------------------------
    # Scenario 2: Successful recommendation with LOWER_MONTHLY_AMOUNT
    # ----------------------------------------------------------------
    def test_recommend_lower_monthly_amount_returns_moderate_count(self):
        """With LOWER_MONTHLY_AMOUNT preference, pick a moderate deposit count
        near the 75th percentile — lower monthly but not the absolute maximum.
        """
        plan = _make_plan(
            min_value_cents=1_000_00,
            max_value_cents=100_000_00,
            min_duration_months=6,
            max_duration_months=60,
            admin_tax_value_cents=50_00,
            insurance_percent=Decimal("1.0"),
            guarantee_fund_percent_1=Decimal("1.0"),
            guarantee_fund_threshold_cents=500_00,
            guarantee_fund_percent_2=Decimal("1.3"),
        )

        target = 30_000_00  # R$ 30,000
        result = self.service.recommend(
            plans=[plan],
            target_amount_cents=target,
            preference=RecommendationPreference.LOWER_MONTHLY_AMOUNT,
        )

        assert result is not None
        # Must not pick the extreme maximum
        assert result.deposit_count < plan.max_duration_months
        # Must stay in the longer half of the range (above midpoint)
        midpoint = (plan.min_duration_months + plan.max_duration_months) // 2
        assert result.deposit_count > midpoint
        assert result.monthly_amount_cents > 0
        assert result.monthly_amount_cents <= target

    def test_preferences_produce_different_results(self):
        """The two preferences must return different deposit_count values
        for the same plan and target amount.
        """
        plan = _make_plan(
            min_value_cents=1_000_00,
            max_value_cents=100_000_00,
            min_duration_months=6,
            max_duration_months=24,
            admin_tax_value_cents=50_00,
            insurance_percent=Decimal("1.0"),
            guarantee_fund_percent_1=Decimal("1.0"),
            guarantee_fund_threshold_cents=500_00,
            guarantee_fund_percent_2=Decimal("1.3"),
        )

        target = 12_000_00  # R$ 12,000

        fewer = self.service.recommend(
            plans=[plan],
            target_amount_cents=target,
            preference=RecommendationPreference.FEWER_PAYMENTS,
        )
        lower = self.service.recommend(
            plans=[plan],
            target_amount_cents=target,
            preference=RecommendationPreference.LOWER_MONTHLY_AMOUNT,
        )

        assert fewer is not None
        assert lower is not None
        # FEWER_PAYMENTS → fewer deposits, higher monthly
        # LOWER_MONTHLY_AMOUNT → more deposits, lower monthly
        assert fewer.deposit_count < lower.deposit_count
        assert fewer.monthly_amount_cents > lower.monthly_amount_cents

    # ----------------------------------------------------------------
    # Scenario 3: No viable plan (target exceeds all plans)
    # ----------------------------------------------------------------
    def test_recommend_no_viable_plan_returns_none(self):
        """When target_amount exceeds all plans' max_value, return None."""
        plan = _make_plan(
            min_value_cents=1_000_00,
            max_value_cents=10_000_00,  # Max R$ 10,000
        )

        # Target R$ 50,000 exceeds the plan's max
        result = self.service.recommend(
            plans=[plan],
            target_amount_cents=50_000_00,
            preference=RecommendationPreference.FEWER_PAYMENTS,
        )

        assert result is None

    def test_recommend_no_viable_plan_target_below_minimum(self):
        """When target_amount is below all plans' min_value, return None."""
        plan = _make_plan(min_value_cents=10_000_00)  # Min R$ 10,000

        result = self.service.recommend(
            plans=[plan],
            target_amount_cents=1_000_00,  # R$ 1,000
            preference=RecommendationPreference.FEWER_PAYMENTS,
        )

        assert result is None

    def test_recommend_no_active_plans_returns_none(self):
        """When all plans are inactive, return None."""
        plan = _make_plan(active=False)

        result = self.service.recommend(
            plans=[plan],
            target_amount_cents=5_000_00,
            preference=RecommendationPreference.FEWER_PAYMENTS,
        )

        assert result is None

    def test_recommend_raises_on_non_positive_target(self):
        """Target amount must be positive."""
        with pytest.raises(ValueError, match="Target amount must be positive"):
            self.service.recommend(
                plans=[],
                target_amount_cents=0,
                preference=RecommendationPreference.FEWER_PAYMENTS,
            )

    # ----------------------------------------------------------------
    # Cost calculation tests
    # ----------------------------------------------------------------
    def test_calculate_cost_basic(self):
        """Verify cost calculation uses plan's existing parameters."""
        plan = _make_plan(
            admin_tax_value_cents=50_00,
            insurance_percent=Decimal("1.0"),
            guarantee_fund_percent_1=Decimal("1.0"),
            guarantee_fund_percent_2=Decimal("1.3"),
            guarantee_fund_threshold_cents=500_00,
        )

        # Monthly R$ 1,000 (100_000 cents) x 12 deposits
        # Monthly amount > threshold (500_00), so use percent_2 = 1.3%
        cost = self.service.calculate_cost(
            plan=plan,
            deposit_count=12,
            monthly_amount_cents=100_000,
        )

        # Admin tax: R$ 50 = 5000 cents
        assert cost.admin_tax_value_cents == 50_00
        # Insurance: 1% of R$ 1,000 = R$ 10 = 1000 cents
        assert cost.insurance_cost_cents == 10_00
        # Guarantee fund: 1.3% of R$ 1,000 = R$ 13 per installment * 12 = R$ 156
        assert cost.guarantee_fund_cost_cents == 156_00
        # Total: 50 + 10 + 156 = R$ 216
        assert cost.total_cost_cents == 216_00
        assert cost.guarantee_fund_percent == Decimal("1.3")

    def test_calculate_cost_uses_tier_1_below_threshold(self):
        """When monthly amount is below threshold, use tier 1 percentage."""
        plan = _make_plan(
            admin_tax_value_cents=20_00,
            insurance_percent=Decimal("2.0"),
            guarantee_fund_percent_1=Decimal("1.0"),
            guarantee_fund_percent_2=Decimal("1.3"),
            guarantee_fund_threshold_cents=500_00,
        )

        # Monthly R$ 4 (400 cents) is below threshold (500_00 cents)
        cost = self.service.calculate_cost(
            plan=plan,
            deposit_count=6,
            monthly_amount_cents=400,
        )

        assert cost.guarantee_fund_percent == Decimal("1.0")
        # GF per installment: 1% of 400 = 4 cents
        assert cost.guarantee_fund_cost_cents == 4 * 6  # 24 cents

    # ----------------------------------------------------------------
    # Validation tests
    # ----------------------------------------------------------------
    def test_validate_params_within_limits(self):
        """Valid parameters should return None."""
        plan = _make_plan(
            min_value_cents=1_000_00,
            max_value_cents=100_000_00,
            min_duration_months=6,
            max_duration_months=60,
        )

        result = self.service.validate_params_against_plan(
            plan=plan,
            target_amount_cents=50_000_00,
            deposit_count=12,
        )

        assert result is None

    def test_validate_params_below_min_value(self):
        """Target below min value should return error message."""
        plan = _make_plan(min_value_cents=10_000_00)

        result = self.service.validate_params_against_plan(
            plan=plan,
            target_amount_cents=1_000_00,
            deposit_count=6,
        )

        assert result is not None
        assert "below" in result.lower()

    def test_validate_params_above_max_value(self):
        """Target above max value should return error message."""
        plan = _make_plan(max_value_cents=10_000_00)

        result = self.service.validate_params_against_plan(
            plan=plan,
            target_amount_cents=50_000_00,
            deposit_count=6,
        )

        assert result is not None
        assert "exceeds" in result.lower()

    def test_validate_params_below_min_duration(self):
        """Deposit count below min should return error."""
        plan = _make_plan(min_duration_months=6)

        result = self.service.validate_params_against_plan(
            plan=plan,
            target_amount_cents=5_000_00,
            deposit_count=3,
        )

        assert result is not None
        assert "below" in result.lower()

    def test_validate_params_above_max_duration(self):
        """Deposit count above max should return error."""
        plan = _make_plan(max_duration_months=12)

        result = self.service.validate_params_against_plan(
            plan=plan,
            target_amount_cents=5_000_00,
            deposit_count=24,
        )

        assert result is not None
        assert "exceeds" in result.lower()

    # ----------------------------------------------------------------
    # Multiple plans: picks cheapest
    # ----------------------------------------------------------------
    def test_recommend_picks_cheapest_plan(self):
        """When multiple plans are viable, pick the one with lowest cost."""
        expensive_plan = _make_plan(
            title="Expensive Plan",
            admin_tax_value_cents=200_00,
            insurance_percent=Decimal("3.0"),
            min_value_cents=1_000_00,
            max_value_cents=100_000_00,
            min_duration_months=6,
            max_duration_months=12,
        )
        cheap_plan = _make_plan(
            title="Cheap Plan",
            admin_tax_value_cents=10_00,
            insurance_percent=Decimal("0.5"),
            min_value_cents=1_000_00,
            max_value_cents=100_000_00,
            min_duration_months=6,
            max_duration_months=12,
        )

        result = self.service.recommend(
            plans=[expensive_plan, cheap_plan],
            target_amount_cents=6_000_00,
            preference=RecommendationPreference.FEWER_PAYMENTS,
        )

        assert result is not None
        assert result.plan_title == "Cheap Plan"

    # ----------------------------------------------------------------
    # Indefinite max (None) plans
    # ----------------------------------------------------------------
    def test_recommend_with_indefinite_max_value(self):
        """Plans with no max value should accept any target above min."""
        plan = _make_plan(
            min_value_cents=1_000_00,
            max_value_cents=None,
            min_duration_months=6,
            max_duration_months=12,
        )

        result = self.service.recommend(
            plans=[plan],
            target_amount_cents=999_999_99,
            preference=RecommendationPreference.FEWER_PAYMENTS,
        )

        assert result is not None

    def test_recommend_with_indefinite_max_duration(self):
        """Plans with no max duration should still produce results."""
        plan = _make_plan(
            min_duration_months=1,
            max_duration_months=None,
            min_value_cents=100_00,
            max_value_cents=100_000_00,
        )

        result = self.service.recommend(
            plans=[plan],
            target_amount_cents=10_000_00,
            preference=RecommendationPreference.LOWER_MONTHLY_AMOUNT,
        )

        assert result is not None
        assert result.deposit_count >= 1
