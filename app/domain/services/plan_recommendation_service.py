"""Plan Recommendation Service - Domain logic for plan recommendation.

Uses existing domain value objects (Money) and plan configuration parameters
to calculate costs and recommend optimal plan + parameter combinations.

IMPORTANT: This service does NOT invent financial formulas. It uses:
- Plan entity's stored fee parameters (admin_tax, insurance_percent, guarantee_fund tiers)
- Money value object for precise decimal arithmetic
- Guarantee fund tier selection based on plan's threshold

No I/O is performed. This is pure domain logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import List, Optional

from app.domain.entities.plan import Plan
from app.domain.value_objects.money import Money


# Maximum deposit count when plan has no upper limit (indefinite).
# This bounds the search space for recommendation.
MAX_DEPOSIT_COUNT_CAP = 360


class RecommendationPreference(Enum):
    """User preference for recommendation tiebreaking."""

    FEWER_PAYMENTS = "FEWER_PAYMENTS"
    LOWER_MONTHLY_AMOUNT = "LOWER_MONTHLY_AMOUNT"


@dataclass(frozen=True)
class CostBreakdown:
    """Breakdown of total cost for a subscription configuration.

    All values in cents. All calculated using existing plan parameters.
    """

    total_cost_cents: int
    admin_tax_value_cents: int
    insurance_cost_cents: int
    guarantee_fund_cost_cents: int
    guarantee_fund_percent: Decimal
    monthly_amount_cents: int
    deposit_count: int


@dataclass(frozen=True)
class RecommendationResult:
    """Result of the plan recommendation algorithm."""

    plan_id: str  # UUID as string for serialization
    plan_title: str
    deposit_count: int
    monthly_amount_cents: int
    total_cost_cents: int
    admin_tax_value_cents: int
    insurance_cost_cents: int
    guarantee_fund_cost_cents: int
    guarantee_fund_percent: Decimal
    min_duration_months: int
    max_duration_months: Optional[int]
    min_value_cents: int
    max_value_cents: Optional[int]


class PlanRecommendationService:
    """Domain service for recommending plans to users.

    Algorithm:
    1. Filter active plans where target_amount fits within [min_value, max_value]
    2. For each viable plan, iterate valid deposit_count values
    3. Calculate monthly_amount and total cost using plan's existing parameters
    4. Select combination with lowest total cost
    5. Tiebreak by user preference (FEWER_PAYMENTS or LOWER_MONTHLY_AMOUNT)

    Cost calculation uses:
    - admin_tax_value_cents: Fixed cost (first installment only)
    - insurance_percent: Percentage of monthly amount (first installment only)
    - guarantee_fund_percent: Selected tier based on threshold (all installments)

    These are the plan's stored configuration parameters, not invented formulas.
    """

    def recommend(
        self,
        plans: List[Plan],
        target_amount_cents: int,
        preference: RecommendationPreference,
    ) -> Optional[RecommendationResult]:
        """Find the best plan + parameters for the user's goal.

        Args:
            plans: List of available Plan entities (only active ones considered).
            target_amount_cents: Total contracted value the user wants in cents.
            preference: Tiebreaking preference.

        Returns:
            RecommendationResult if a viable combination exists, None otherwise.

        Raises:
            ValueError: If target_amount_cents is not positive.
        """
        if target_amount_cents <= 0:
            raise ValueError("Target amount must be positive")

        candidates: List[RecommendationResult] = []

        for plan in plans:
            if not plan.is_active():
                continue

            # Check if target_amount fits within plan's value range
            if target_amount_cents < plan.min_value_cents:
                continue
            if (
                plan.max_value_cents is not None
                and target_amount_cents > plan.max_value_cents
            ):
                continue

            # Generate valid deposit_count values
            min_deposits = plan.min_duration_months
            max_deposits = (
                plan.max_duration_months
                if plan.max_duration_months is not None
                else MAX_DEPOSIT_COUNT_CAP
            )

            for deposit_count in range(min_deposits, max_deposits + 1):
                # Ceiling division to ensure payments cover target
                monthly_amount_cents = (
                    (target_amount_cents + deposit_count - 1) // deposit_count
                )

                if monthly_amount_cents <= 0:
                    continue

                cost = self.calculate_cost(plan, deposit_count, monthly_amount_cents)

                candidates.append(
                    RecommendationResult(
                        plan_id=str(plan.id),
                        plan_title=plan.title,
                        deposit_count=deposit_count,
                        monthly_amount_cents=monthly_amount_cents,
                        total_cost_cents=cost.total_cost_cents,
                        admin_tax_value_cents=cost.admin_tax_value_cents,
                        insurance_cost_cents=cost.insurance_cost_cents,
                        guarantee_fund_cost_cents=cost.guarantee_fund_cost_cents,
                        guarantee_fund_percent=cost.guarantee_fund_percent,
                        min_duration_months=plan.min_duration_months,
                        max_duration_months=plan.max_duration_months,
                        min_value_cents=plan.min_value_cents,
                        max_value_cents=plan.max_value_cents,
                    )
                )

        if not candidates:
            return None

        # Sort by user preference first, then tiebreak by cost.
        # FEWER_PAYMENTS  -> fewest deposits (higher monthly), cost tiebreak
        # LOWER_MONTHLY_AMOUNT -> lowest monthly (more deposits), cost tiebreak
        def sort_key(r: RecommendationResult) -> tuple:
            if preference == RecommendationPreference.FEWER_PAYMENTS:
                return (r.deposit_count, r.total_cost_cents)
            else:  # LOWER_MONTHLY_AMOUNT
                return (r.monthly_amount_cents, r.total_cost_cents)

        candidates.sort(key=sort_key)
        return candidates[0]

    def calculate_cost(
        self,
        plan: Plan,
        deposit_count: int,
        monthly_amount_cents: int,
    ) -> CostBreakdown:
        """Calculate cost breakdown for specific parameters.

        Uses the plan's existing fee/tax parameters:
        - admin_tax_value_cents: Fixed cost on first installment
        - insurance_percent: Percentage on first installment
        - guarantee_fund_percent: Tiered percentage on all installments

        Args:
            plan: The Plan entity with fee configuration.
            deposit_count: Number of deposits.
            monthly_amount_cents: Amount per deposit in cents.

        Returns:
            CostBreakdown with all cost components.

        Raises:
            ValueError: If parameters are invalid.
        """
        if deposit_count < 1:
            raise ValueError("Deposit count must be at least 1")
        if monthly_amount_cents <= 0:
            raise ValueError("Monthly amount must be positive")

        # Select guarantee fund tier based on threshold
        gf_percent = self._select_guarantee_fund_percent(plan, monthly_amount_cents)

        # Calculate costs using Money value object for precision
        monthly_money = Money.from_cents(monthly_amount_cents)

        # First installment: admin_tax (fixed) + insurance (%) + guarantee_fund (%)
        admin_tax_cost = plan.admin_tax_value_cents
        insurance_cost = monthly_money.percentage(plan.insurance_percent).cents
        gf_per_installment = monthly_money.percentage(gf_percent).cents

        # Guarantee fund applies to all installments
        total_gf_cost = gf_per_installment * deposit_count

        # Total cost = admin_tax + insurance + all guarantee fund
        total_cost = admin_tax_cost + insurance_cost + total_gf_cost

        return CostBreakdown(
            total_cost_cents=total_cost,
            admin_tax_value_cents=admin_tax_cost,
            insurance_cost_cents=insurance_cost,
            guarantee_fund_cost_cents=total_gf_cost,
            guarantee_fund_percent=gf_percent,
            monthly_amount_cents=monthly_amount_cents,
            deposit_count=deposit_count,
        )

    def validate_params_against_plan(
        self,
        plan: Plan,
        target_amount_cents: int,
        deposit_count: int,
    ) -> Optional[str]:
        """Validate subscription parameters against plan limits.

        Args:
            plan: The Plan entity.
            target_amount_cents: Total contracted value in cents.
            deposit_count: Number of deposits.

        Returns:
            Error message string if invalid, None if valid.
        """
        if target_amount_cents < plan.min_value_cents:
            return (
                f"Target amount {target_amount_cents} is below "
                f"plan minimum {plan.min_value_cents}"
            )
        if (
            plan.max_value_cents is not None
            and target_amount_cents > plan.max_value_cents
        ):
            return (
                f"Target amount {target_amount_cents} exceeds "
                f"plan maximum {plan.max_value_cents}"
            )
        if deposit_count < plan.min_duration_months:
            return (
                f"Deposit count {deposit_count} is below "
                f"plan minimum {plan.min_duration_months} months"
            )
        if (
            plan.max_duration_months is not None
            and deposit_count > plan.max_duration_months
        ):
            return (
                f"Deposit count {deposit_count} exceeds "
                f"plan maximum {plan.max_duration_months} months"
            )
        return None

    def _select_guarantee_fund_percent(
        self, plan: Plan, monthly_amount_cents: int
    ) -> Decimal:
        """Select guarantee fund tier based on monthly amount vs threshold.

        Args:
            plan: The Plan entity with tier configuration.
            monthly_amount_cents: The monthly installment amount in cents.

        Returns:
            The applicable guarantee fund percentage.
        """
        if monthly_amount_cents <= plan.guarantee_fund_threshold_cents:
            return plan.guarantee_fund_percent_1
        return plan.guarantee_fund_percent_2
