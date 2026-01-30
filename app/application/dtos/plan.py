"""Plan DTOs for application layer."""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID


@dataclass
class CreatePlanInput:
    """Input for creating a new plan."""

    title: str
    description: str
    min_value_cents: int
    max_value_cents: int | None
    min_duration_months: int
    max_duration_months: int | None
    admin_tax_value_cents: int
    insurance_percent: Decimal
    guarantee_fund_percent_1: Decimal
    guarantee_fund_percent_2: Decimal
    guarantee_fund_threshold_cents: int
    active: bool


@dataclass
class UpdatePlanInput:
    """Input for updating an existing plan."""

    plan_id: UUID
    title: str
    active: bool
    description: str
    min_value_cents: int
    max_value_cents: int | None
    min_duration_months: int
    max_duration_months: int | None
    admin_tax_value_cents: int
    insurance_percent: Decimal
    guarantee_fund_percent_1: Decimal
    guarantee_fund_percent_2: Decimal
    guarantee_fund_threshold_cents: int
    active: bool


@dataclass
class PlanResult:
    """Result containing plan data."""

    id: UUID
    title: str
    description: str
    min_value_cents: int
    max_value_cents: int | None
    min_duration_months: int
    max_duration_months: int | None
    admin_tax_value_cents: int
    insurance_percent: Decimal
    guarantee_fund_percent_1: Decimal
    guarantee_fund_percent_2: Decimal
    guarantee_fund_threshold_cents: int
    active: bool
