"""Subscription DTOs for application layer."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional
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


@dataclass
class SubscriptionResult:
    """Result containing subscription data."""

    id: UUID
    user_id: UUID
    plan_id: UUID
    plan_title: str
    target_amount_cents: int
    deposit_count: int
    monthly_amount_cents: int
    admin_tax_value_cents: int
    insurance_percent: Decimal
    guarantee_fund_percent: Decimal
    total_cost_cents: int
    status: str
    created_at: str  # ISO format string


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
