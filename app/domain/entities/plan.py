"""Plan entity - Domain model for investment plans.

This entity stores configuration parameters only.
No monetary calculations or installment simulations are performed here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4


@dataclass
class Plan:
    """Plan entity representing an investment plan configuration.

    This entity stores configuration parameters for plans:
    - Identification: title, description
    - Constraints: value ranges, duration ranges
    - First installment parameters: admin tax, insurance, guarantee fund rates

    IMPORTANT: This entity does NOT perform calculations.
    All financial computations happen in dedicated domain services.
    """

    id: UUID
    title: str
    description: str  # Stored as Markdown text

    # Constraints (based on total contracted plan value and duration)
    min_value_cents: int  # Minimum contracted value in cents
    max_value_cents: Optional[int]  # Maximum contracted value in cents (None = indefinite)
    min_duration_months: int
    max_duration_months: Optional[int]  # Maximum duration in months (None = indefinite)

    # First installment configuration parameters
    admin_tax_value_cents: int  # Fixed administrative tax in cents
    insurance_percent: Decimal  # Percentage applied once (0-100)
    guarantee_fund_percent_1: Decimal  # Tier 1 percentage (0-100)
    guarantee_fund_percent_2: Decimal  # Tier 2 percentage (0-100)
    guarantee_fund_threshold_cents: int  # Threshold amount in cents for tier switch

    active: bool
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    deleted_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        """Validate invariants after initialization."""
        self._validate_invariants()

    def _validate_invariants(self) -> None:
        """Validate all business invariants.

        Raises:
            ValueError: If any invariant is violated.
        """
        # Value constraints
        if self.min_value_cents < 0:
            raise ValueError("Minimum value cannot be negative")
        if self.max_value_cents is not None:
            if self.max_value_cents < 0:
                raise ValueError("Maximum value cannot be negative")
            if self.min_value_cents > self.max_value_cents:
                raise ValueError("Minimum value cannot exceed maximum value")

        # Duration constraints
        if self.min_duration_months < 1:
            raise ValueError("Minimum duration must be at least 1 month")
        if self.max_duration_months is not None:
            if self.max_duration_months < 1:
                raise ValueError("Maximum duration must be at least 1 month")
            if self.min_duration_months > self.max_duration_months:
                raise ValueError("Minimum duration cannot exceed maximum duration")

        # Admin tax validation
        if self.admin_tax_value_cents < 0:
            raise ValueError("Administrative tax cannot be negative")

        # Percentage validations (0-100 range)
        if not (Decimal("0") <= self.insurance_percent <= Decimal("100")):
            raise ValueError("Insurance percentage must be between 0 and 100")
        if not (Decimal("0") <= self.guarantee_fund_percent_1 <= Decimal("100")):
            raise ValueError("Guarantee fund tier 1 percentage must be between 0 and 100")
        if not (Decimal("0") <= self.guarantee_fund_percent_2 <= Decimal("100")):
            raise ValueError("Guarantee fund tier 2 percentage must be between 0 and 100")

        # Threshold validation
        if self.guarantee_fund_threshold_cents < 0:
            raise ValueError("Guarantee fund threshold cannot be negative")

        # Title validation
        if not self.title or not self.title.strip():
            raise ValueError("Plan title cannot be empty")

    @classmethod
    def create(
        cls,
        title: str,
        description: str,
        min_value_cents: int,
        max_value_cents: Optional[int],
        min_duration_months: int,
        max_duration_months: Optional[int],
        admin_tax_value_cents: int,
        insurance_percent: Decimal,
        guarantee_fund_percent_1: Decimal,
        guarantee_fund_percent_2: Decimal,
        guarantee_fund_threshold_cents: int,
        active: bool = True,
    ) -> Plan:
        """Factory method to create a new Plan.

        Args:
            title: Plan title
            description: Plan description (Markdown text)
            min_value_cents: Minimum contracted value in cents
            max_value_cents: Maximum contracted value in cents (None = indefinite)
            min_duration_months: Minimum duration in months
            max_duration_months: Maximum duration in months (None = indefinite)
            admin_tax_value_cents: Administrative tax in cents
            insurance_percent: Insurance rate (0-100)
            guarantee_fund_percent_1: Guarantee fund tier 1 rate (0-100)
            guarantee_fund_percent_2: Guarantee fund tier 2 rate (0-100)
            guarantee_fund_threshold_cents: Threshold for tier switch in cents

        Returns:
            A new Plan instance marked as active.

        Raises:
            ValueError: If any invariant is violated.
        """
        now = datetime.utcnow()
        return cls(
            id=uuid4(),
            title=title,
            description=description,
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
            created_at=now,
            updated_at=now,
        )

    def update(
        self,
        title: str,
        description: str,
        min_value_cents: int,
        max_value_cents: Optional[int],
        min_duration_months: int,
        max_duration_months: Optional[int],
        admin_tax_value_cents: int,
        insurance_percent: Decimal,
        guarantee_fund_percent_1: Decimal,
        guarantee_fund_percent_2: Decimal,
        guarantee_fund_threshold_cents: int,
        active: bool,
    ) -> None:
        """Update plan configuration.

        Updates plan fields and validates invariants.
        This does NOT affect existing contracts.

        Args:
            title: Plan title
            description: Plan description (Markdown text)
            min_value_cents: Minimum contracted value in cents
            max_value_cents: Maximum contracted value in cents (None = indefinite)
            min_duration_months: Minimum duration in months
            max_duration_months: Maximum duration in months (None = indefinite)
            admin_tax_value_cents: Administrative tax in cents
            insurance_percent: Insurance rate (0-100)
            guarantee_fund_percent_1: Guarantee fund tier 1 rate (0-100)
            guarantee_fund_percent_2: Guarantee fund tier 2 rate (0-100)
            guarantee_fund_threshold_cents: Threshold for tier switch in cents

        Raises:
            ValueError: If any invariant is violated.
        """
        # Store previous values in case validation fails
        prev_title = self.title
        prev_description = self.description
        prev_min_value = self.min_value_cents
        prev_max_value = self.max_value_cents
        prev_min_duration = self.min_duration_months
        prev_max_duration = self.max_duration_months
        prev_admin_tax = self.admin_tax_value_cents
        prev_insurance = self.insurance_percent
        prev_gf1 = self.guarantee_fund_percent_1
        prev_gf2 = self.guarantee_fund_percent_2
        prev_threshold = self.guarantee_fund_threshold_cents
        prev_active = self.active

        try:
            self.title = title
            self.description = description
            self.min_value_cents = min_value_cents
            self.max_value_cents = max_value_cents
            self.min_duration_months = min_duration_months
            self.max_duration_months = max_duration_months
            self.admin_tax_value_cents = admin_tax_value_cents
            self.insurance_percent = insurance_percent
            self.guarantee_fund_percent_1 = guarantee_fund_percent_1
            self.guarantee_fund_percent_2 = guarantee_fund_percent_2
            self.guarantee_fund_threshold_cents = guarantee_fund_threshold_cents
            self.active = active
            self._validate_invariants()
            self.updated_at = datetime.utcnow()
        except ValueError:
            # Rollback on validation failure
            self.title = prev_title
            self.description = prev_description
            self.min_value_cents = prev_min_value
            self.max_value_cents = prev_max_value
            self.min_duration_months = prev_min_duration
            self.max_duration_months = prev_max_duration
            self.admin_tax_value_cents = prev_admin_tax
            self.insurance_percent = prev_insurance
            self.guarantee_fund_percent_1 = prev_gf1
            self.guarantee_fund_percent_2 = prev_gf2
            self.guarantee_fund_threshold_cents = prev_threshold
            self.active = prev_active
            raise

    def activate(self) -> None:
        """Activate the plan."""
        self.active = True
        self.updated_at = datetime.utcnow()

    def deactivate(self) -> None:
        """Deactivate the plan."""
        self.active = False
        self.updated_at = datetime.utcnow()

    def is_active(self) -> bool:
        """Check if plan is active and not deleted."""
        return self.active and self.deleted_at is None

    def is_deleted(self) -> bool:
        """Check if plan has been soft deleted."""
        return self.deleted_at is not None

    def soft_delete(self) -> None:
        """Mark the plan as deleted.

        Sets the deleted_at timestamp to mark the plan as soft deleted.
        Soft deleted plans are excluded from listing endpoints.

        Raises:
            ValueError: If plan is already deleted.
        """
        if self.deleted_at is not None:
            raise ValueError("Plan is already deleted")
        self.deleted_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)
