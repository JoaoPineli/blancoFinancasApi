"""Subscription DTOs for application layer."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import List, Optional
from uuid import UUID


@dataclass
class RecommendSubscriptionInput:
    """Input for plan recommendation."""

    target_amount_cents: int
    preference: str  # "FEWER_PAYMENTS" or "LOWER_MONTHLY_AMOUNT"


@dataclass
class CalculateCostInput:
    """Input for cost calculation with specific parameters."""

    plan_id: UUID
    target_amount_cents: int
    deposit_count: int
    monthly_amount_cents: int


@dataclass
class CreateSubscriptionInput:
    """Input for creating a new subscription."""

    user_id: UUID
    plan_id: UUID
    target_amount_cents: int
    deposit_count: int
    monthly_amount_cents: int
    name: str = ""
    deposit_day_of_month: int = 1


@dataclass
class UpdateDepositDayInput:
    """Input for updating the deposit day-of-month on a subscription."""

    user_id: UUID
    subscription_id: UUID
    deposit_day_of_month: int


@dataclass
class UpdateNameInput:
    """Input for updating the cosmetic name of a subscription."""

    user_id: UUID
    subscription_id: UUID
    name: str


@dataclass
class SubscriptionResult:
    """Result containing subscription data."""

    id: UUID
    user_id: UUID
    plan_id: UUID
    plan_title: str
    name: str
    target_amount_cents: int
    deposit_count: int
    monthly_amount_cents: int
    admin_tax_value_cents: int
    insurance_percent: Decimal
    guarantee_fund_percent: Decimal
    total_cost_cents: int
    deposit_day_of_month: int
    next_due_date: str  # ISO date string
    has_overdue_deposit: bool
    status: str
    created_at: str  # ISO format string
    accumulated_cents: int
    deposits_paid: int
    yield_cents: int


@dataclass
class RecommendationResultDTO:
    """Result containing recommendation data."""

    plan_id: str
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


@dataclass
class CostResultDTO:
    """Result containing cost breakdown data."""

    total_cost_cents: int
    admin_tax_value_cents: int
    insurance_cost_cents: int
    guarantee_fund_cost_cents: int
    guarantee_fund_percent: Decimal
    monthly_amount_cents: int
    deposit_count: int


# ------------------------------------------------------------------
# Dashboard DTOs
# ------------------------------------------------------------------


@dataclass
class DuePlanInfo:
    """Minimal info about a subscription that is due or overdue."""

    subscription_id: str
    plan_title: str
    name: str
    next_due_date: str  # ISO date


@dataclass
class DashboardDueStatus:
    """Due/overdue status for the dashboard banner."""

    overdue_plans: List[DuePlanInfo] = field(default_factory=list)
    due_today_plans: List[DuePlanInfo] = field(default_factory=list)
