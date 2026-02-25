"""User Plan Subscription entity - Domain model for user plan subscriptions.

A user can have zero, one, or many subscriptions, including multiple
subscriptions to the same plan. Each subscription stores a snapshot of
the chosen parameters and applicable fees at creation time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4


class SubscriptionStatus(Enum):
    """Subscription status enumeration."""

    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass
class UserPlanSubscription:
    """Entity representing a user's subscription to a plan.

    A user can have zero, one, or many subscriptions,
    including multiple subscriptions to the same plan.

    Stores the chosen parameters at subscription time as immutable snapshots:
    - target_amount_cents: Total contracted value the user wants
    - deposit_count: Number of monthly deposits
    - monthly_amount_cents: Amount per deposit
    - Fee/tax snapshots from the plan at creation time
    - total_cost_cents: Pre-calculated total fees/taxes
    """

    id: UUID
    user_id: UUID
    plan_id: UUID

    # User-chosen parameters
    target_amount_cents: int
    deposit_count: int
    monthly_amount_cents: int

    # Snapshot of plan fees at time of subscription creation
    admin_tax_value_cents: int
    insurance_percent: Decimal
    guarantee_fund_percent: Decimal

    # Pre-calculated total cost (fees + taxes)
    total_cost_cents: int

    status: SubscriptionStatus
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def __post_init__(self) -> None:
        """Validate invariants after initialization."""
        self._validate_invariants()

    def _validate_invariants(self) -> None:
        """Validate all business invariants.

        Raises:
            ValueError: If any invariant is violated.
        """
        if self.target_amount_cents <= 0:
            raise ValueError("Target amount must be positive")
        if self.deposit_count < 1:
            raise ValueError("Deposit count must be at least 1")
        if self.monthly_amount_cents <= 0:
            raise ValueError("Monthly amount must be positive")
        if self.admin_tax_value_cents < 0:
            raise ValueError("Admin tax cannot be negative")
        if self.insurance_percent < Decimal("0"):
            raise ValueError("Insurance percent cannot be negative")
        if self.guarantee_fund_percent < Decimal("0"):
            raise ValueError("Guarantee fund percent cannot be negative")
        if self.total_cost_cents < 0:
            raise ValueError("Total cost cannot be negative")

    @classmethod
    def create(
        cls,
        user_id: UUID,
        plan_id: UUID,
        target_amount_cents: int,
        deposit_count: int,
        monthly_amount_cents: int,
        admin_tax_value_cents: int,
        insurance_percent: Decimal,
        guarantee_fund_percent: Decimal,
        total_cost_cents: int,
    ) -> UserPlanSubscription:
        """Factory method to create a new subscription.

        Args:
            user_id: UUID of the subscribing user.
            plan_id: UUID of the plan being subscribed to.
            target_amount_cents: Total contracted value in cents.
            deposit_count: Number of monthly deposits.
            monthly_amount_cents: Amount per deposit in cents.
            admin_tax_value_cents: Snapshot of plan admin tax in cents.
            insurance_percent: Snapshot of plan insurance percentage.
            guarantee_fund_percent: Selected guarantee fund tier percentage.
            total_cost_cents: Pre-calculated total fees/taxes in cents.

        Returns:
            A new UserPlanSubscription in ACTIVE status.

        Raises:
            ValueError: If any invariant is violated.
        """
        now = datetime.utcnow()
        return cls(
            id=uuid4(),
            user_id=user_id,
            plan_id=plan_id,
            target_amount_cents=target_amount_cents,
            deposit_count=deposit_count,
            monthly_amount_cents=monthly_amount_cents,
            admin_tax_value_cents=admin_tax_value_cents,
            insurance_percent=insurance_percent,
            guarantee_fund_percent=guarantee_fund_percent,
            total_cost_cents=total_cost_cents,
            status=SubscriptionStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )

    def cancel(self) -> None:
        """Cancel the subscription.

        Raises:
            ValueError: If subscription is not active.
        """
        if self.status != SubscriptionStatus.ACTIVE:
            raise ValueError(
                f"Cannot cancel subscription in status {self.status.value}"
            )
        self.status = SubscriptionStatus.CANCELLED
        self.updated_at = datetime.utcnow()

    def complete(self) -> None:
        """Mark the subscription as completed.

        Raises:
            ValueError: If subscription is not active.
        """
        if self.status != SubscriptionStatus.ACTIVE:
            raise ValueError(
                f"Cannot complete subscription in status {self.status.value}"
            )
        self.status = SubscriptionStatus.COMPLETED
        self.updated_at = datetime.utcnow()

    def is_active(self) -> bool:
        """Check if subscription is active."""
        return self.status == SubscriptionStatus.ACTIVE
