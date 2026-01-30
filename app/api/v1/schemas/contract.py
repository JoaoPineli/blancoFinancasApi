"""Contract schemas."""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class PlanResponse(BaseModel):
    """Response schema for plan data."""

    id: str = Field(..., description="Plan UUID")
    title: str = Field(..., description="Plan title")
    description: str = Field(..., description="Plan description (Markdown)")
    min_value_cents: int = Field(..., description="Minimum contracted value in cents")
    max_value_cents: Optional[int] = Field(None, description="Maximum contracted value in cents")
    min_duration_months: int = Field(..., description="Minimum duration in months")
    max_duration_months: Optional[int] = Field(None, description="Maximum duration in months")
    admin_tax_value_cents: int = Field(..., description="Fixed administrative tax in cents")
    insurance_percent: Decimal = Field(..., description="Insurance percentage (0-100)")
    guarantee_fund_percent_1: Decimal = Field(..., description="Guarantee fund tier 1 percentage")
    guarantee_fund_percent_2: Decimal = Field(..., description="Guarantee fund tier 2 percentage")
    guarantee_fund_threshold_cents: int = Field(..., description="Threshold for guarantee fund tier switch")
    active: bool = Field(..., description="Plan active status")


class PlanListResponse(BaseModel):
    """Response schema for plan list."""

    plans: list[PlanResponse] = Field(..., description="List of plans")


class ContractResponse(BaseModel):
    """Response schema for contract data."""

    id: str = Field(..., description="Contract UUID")
    user_id: str = Field(..., description="User UUID")
    plan_id: str = Field(..., description="Plan UUID")
    status: str = Field(..., description="Contract status")
    pdf_storage_path: Optional[str] = Field(None, description="PDF storage path")
    accepted_at: Optional[datetime] = Field(None, description="Acceptance date")
    start_date: Optional[datetime] = Field(None, description="Contract start date")
    end_date: Optional[datetime] = Field(None, description="Contract end date")
    created_at: datetime = Field(..., description="Creation date")


class CreateContractRequest(BaseModel):
    """Request schema for creating a contract."""

    plan_id: str = Field(..., description="Plan UUID")


class AcceptContractRequest(BaseModel):
    """Request schema for accepting a contract."""

    contract_id: str = Field(..., description="Contract UUID")
