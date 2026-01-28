"""Contract schemas."""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class PlanResponse(BaseModel):
    """Response schema for plan data."""

    id: str = Field(..., description="Plan UUID")
    name: str = Field(..., description="Plan name")
    plan_type: str = Field(..., description="Plan type (geral or pequeno_agricultor)")
    description: str = Field(..., description="Plan description")
    monthly_installment_cents: int = Field(..., description="Monthly installment in cents")
    duration_months: int = Field(..., description="Duration in months")
    fundo_garantidor_percentage: Decimal = Field(..., description="Fundo Garantidor percentage")
    status: str = Field(..., description="Plan status")


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
