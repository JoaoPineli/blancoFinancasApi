"""Plan API schemas for request/response validation."""

from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field, model_validator


class PlanBase(BaseModel):
    """Base schema for plan data.
    
    Note: max_value_cents and max_duration_months can be null to indicate indefinite (no limit).
    """

    title: str = Field(..., min_length=1, max_length=100, description="Plan title")
    description: str = Field(..., description="Plan description (Markdown text)")
    min_value_cents: int = Field(..., ge=0, description="Minimum contracted value in cents")
    max_value_cents: Optional[int] = Field(
        None, ge=0, description="Maximum contracted value in cents (null = indefinite)"
    )
    min_duration_months: int = Field(..., ge=1, description="Minimum duration in months")
    max_duration_months: Optional[int] = Field(
        None, ge=1, description="Maximum duration in months (null = indefinite)"
    )
    admin_tax_value_cents: int = Field(..., ge=0, description="Administrative tax in cents")
    insurance_percent: Decimal = Field(
        ..., ge=0, le=100, description="Insurance rate percentage (0-100)"
    )
    guarantee_fund_percent_1: Decimal = Field(
        ..., ge=0, le=100, description="Guarantee fund tier 1 percentage (0-100)"
    )
    guarantee_fund_percent_2: Decimal = Field(
        ..., ge=0, le=100, description="Guarantee fund tier 2 percentage (0-100)"
    )
    guarantee_fund_threshold_cents: int = Field(
        ..., ge=0, description="Threshold for guarantee fund tier switch in cents"
    )
    active: bool = Field(..., description="Indicates whether the plan is active")

    @model_validator(mode="after")
    def validate_ranges(self) -> "PlanBase":
        """Validate that max values are >= min values when max values are set."""
        if self.max_value_cents is not None and self.max_value_cents < self.min_value_cents:
            raise ValueError("Maximum value must be greater than minimum value")
        if self.max_duration_months is not None and self.max_duration_months < self.min_duration_months:
            raise ValueError(
                "Maximum duration must be greater than minimum duration"
            )
        return self


class CreatePlanRequest(PlanBase):
    """Request schema for creating a plan."""

    pass


class UpdatePlanRequest(PlanBase):
    """Request schema for updating a plan."""

    pass

class PlanResponse(BaseModel):
    """Response schema for a single plan."""

    id: str = Field(..., description="Plan UUID")
    title: str = Field(..., description="Plan title")
    description: str = Field(..., description="Plan description (Markdown text)")
    min_value_cents: int = Field(..., description="Minimum contracted value in cents")
    max_value_cents: Optional[int] = Field(
        None, description="Maximum contracted value in cents (null = indefinite)"
    )
    min_duration_months: int = Field(..., description="Minimum duration in months")
    max_duration_months: Optional[int] = Field(
        None, description="Maximum duration in months (null = indefinite)"
    )
    admin_tax_value_cents: int = Field(..., description="Administrative tax in cents")
    insurance_percent: Decimal = Field(..., description="Insurance rate percentage")
    guarantee_fund_percent_1: Decimal = Field(..., description="Guarantee fund tier 1 percentage")
    guarantee_fund_percent_2: Decimal = Field(..., description="Guarantee fund tier 2 percentage")
    guarantee_fund_threshold_cents: int = Field(
        ..., description="Threshold for guarantee fund tier switch in cents"
    )
    active: bool = Field(..., description="Plan active flag")


class PlanListResponse(BaseModel):
    """Response schema for list of plans."""

    plans: List[PlanResponse] = Field(..., description="List of plans")
    total: int = Field(..., description="Total number of plans")


class PlanSummaryResponse(BaseModel):
    """Response schema for a plan summary entry."""

    id: str = Field(..., description="Plan UUID")
    title: str = Field(..., description="Plan title")
    active: bool = Field(..., description="Plan active flag")