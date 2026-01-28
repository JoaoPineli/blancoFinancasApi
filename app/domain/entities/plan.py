"""Plan entity - Domain model for investment plans."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4


class PlanType(Enum):
    """Plan type enumeration."""

    GERAL = "geral"
    PEQUENO_AGRICULTOR = "pequeno_agricultor"


class PlanStatus(Enum):
    """Plan status enumeration."""

    ACTIVE = "active"
    INACTIVE = "inactive"


@dataclass
class Plan:
    """Plan entity representing an investment plan.

    Plans define:
    - Type (Geral or Pequeno Agricultor)
    - Monthly installment amount
    - Duration in months
    - Fundo Garantidor percentage (1% to 1.3%)
    """

    id: UUID
    name: str
    plan_type: PlanType
    description: str
    monthly_installment_cents: int  # Stored in cents
    duration_months: int
    fundo_garantidor_percentage: Decimal  # Stored as decimal (e.g., 1.0 or 1.3)
    status: PlanStatus
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    @classmethod
    def create(
        cls,
        name: str,
        plan_type: PlanType,
        description: str,
        monthly_installment_cents: int,
        duration_months: int,
        fundo_garantidor_percentage: Decimal,
    ) -> Plan:
        """Factory method to create a new Plan.

        Args:
            name: Plan name
            plan_type: Type of plan (Geral or Pequeno Agricultor)
            description: Plan description
            monthly_installment_cents: Monthly installment in cents
            duration_months: Duration in months
            fundo_garantidor_percentage: Fundo Garantidor percentage (1.0 to 1.3)
        """
        # Validate Fundo Garantidor percentage range
        if not (Decimal("1.0") <= fundo_garantidor_percentage <= Decimal("1.3")):
            raise ValueError("Fundo Garantidor percentage must be between 1.0% and 1.3%")

        now = datetime.utcnow()
        return cls(
            id=uuid4(),
            name=name,
            plan_type=plan_type,
            description=description,
            monthly_installment_cents=monthly_installment_cents,
            duration_months=duration_months,
            fundo_garantidor_percentage=fundo_garantidor_percentage,
            status=PlanStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )

    def activate(self) -> None:
        """Activate the plan."""
        self.status = PlanStatus.ACTIVE
        self.updated_at = datetime.utcnow()

    def deactivate(self) -> None:
        """Deactivate the plan."""
        self.status = PlanStatus.INACTIVE
        self.updated_at = datetime.utcnow()

    def is_active(self) -> bool:
        """Check if plan is active."""
        return self.status == PlanStatus.ACTIVE

    @property
    def monthly_installment_amount(self) -> Decimal:
        """Get monthly installment as decimal amount."""
        return Decimal(self.monthly_installment_cents) / Decimal(100)
