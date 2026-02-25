"""Subscription API schemas for request/response validation."""

from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field


class RecommendSubscriptionRequest(BaseModel):
    """Request schema for plan recommendation."""

    target_amount_cents: int = Field(
        ..., gt=0, description="Total target amount in cents"
    )
    preference: str = Field(
        ...,
        pattern="^(FEWER_PAYMENTS|LOWER_MONTHLY_AMOUNT)$",
        description="Recommendation preference: FEWER_PAYMENTS or LOWER_MONTHLY_AMOUNT",
    )


class CalculateCostRequest(BaseModel):
    """Request schema for cost calculation with adjusted parameters."""

    plan_id: str = Field(..., description="Plan UUID")
    target_amount_cents: int = Field(
        ..., gt=0, description="Total target amount in cents"
    )
    deposit_count: int = Field(..., ge=1, description="Number of deposits")
    monthly_amount_cents: int = Field(
        ..., gt=0, description="Monthly amount in cents"
    )


class CreateSubscriptionRequest(BaseModel):
    """Request schema for creating a subscription."""

    plan_id: str = Field(..., description="Plan UUID")
    target_amount_cents: int = Field(
        ..., gt=0, description="Total target amount in cents"
    )
    deposit_count: int = Field(..., ge=1, description="Number of deposits")
    monthly_amount_cents: int = Field(
        ..., gt=0, description="Monthly amount in cents"
    )


class SubscriptionResponse(BaseModel):
    """Response schema for a single subscription."""

    id: str = Field(..., description="Subscription UUID")
    user_id: str = Field(..., description="User UUID")
    plan_id: str = Field(..., description="Plan UUID")
    plan_title: str = Field(..., description="Plan title at time of display")
    target_amount_cents: int = Field(..., description="Total target amount in cents")
    deposit_count: int = Field(..., description="Number of deposits")
    monthly_amount_cents: int = Field(..., description="Monthly amount in cents")
    admin_tax_value_cents: int = Field(
        ..., description="Admin tax snapshot in cents"
    )
    insurance_percent: Decimal = Field(
        ..., description="Insurance percentage snapshot"
    )
    guarantee_fund_percent: Decimal = Field(
        ..., description="Guarantee fund percentage snapshot"
    )
    total_cost_cents: int = Field(..., description="Total fees/taxes in cents")
    status: str = Field(..., description="Subscription status")
    created_at: str = Field(..., description="Creation date (ISO format)")


class SubscriptionListResponse(BaseModel):
    """Response schema for list of subscriptions."""

    subscriptions: List[SubscriptionResponse] = Field(
        ..., description="List of subscriptions"
    )
    total: int = Field(..., description="Total number of subscriptions")


class RecommendationResponse(BaseModel):
    """Response schema for plan recommendation."""

    plan_id: str = Field(..., description="Recommended plan UUID")
    plan_title: str = Field(..., description="Recommended plan title")
    deposit_count: int = Field(..., description="Recommended number of deposits")
    monthly_amount_cents: int = Field(
        ..., description="Recommended monthly amount in cents"
    )
    total_cost_cents: int = Field(..., description="Estimated total fees/taxes")
    admin_tax_value_cents: int = Field(
        ..., description="Admin tax component in cents"
    )
    insurance_cost_cents: int = Field(
        ..., description="Insurance cost component in cents"
    )
    guarantee_fund_cost_cents: int = Field(
        ..., description="Guarantee fund cost component in cents"
    )
    guarantee_fund_percent: Decimal = Field(
        ..., description="Applied guarantee fund percentage"
    )
    min_duration_months: int = Field(
        ..., description="Plan minimum duration in months"
    )
    max_duration_months: Optional[int] = Field(
        None, description="Plan maximum duration in months (null = indefinite)"
    )
    min_value_cents: int = Field(
        ..., description="Plan minimum contracted value in cents"
    )
    max_value_cents: Optional[int] = Field(
        None, description="Plan maximum contracted value in cents (null = indefinite)"
    )


class CostResponse(BaseModel):
    """Response schema for cost calculation."""

    total_cost_cents: int = Field(..., description="Total fees/taxes in cents")
    admin_tax_value_cents: int = Field(
        ..., description="Admin tax component in cents"
    )
    insurance_cost_cents: int = Field(
        ..., description="Insurance cost component in cents"
    )
    guarantee_fund_cost_cents: int = Field(
        ..., description="Guarantee fund cost component in cents"
    )
    guarantee_fund_percent: Decimal = Field(
        ..., description="Applied guarantee fund percentage"
    )
    monthly_amount_cents: int = Field(
        ..., description="Monthly amount used for calculation"
    )
    deposit_count: int = Field(
        ..., description="Deposit count used for calculation"
    )
