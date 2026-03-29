"""User Plan Subscription entity - Domain model for user plan subscriptions.

A user can have zero, one, or many subscriptions, including multiple
subscriptions to the same plan. Each subscription stores a snapshot of
the chosen parameters and applicable fees at creation time.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from datetime import datetime, date
from decimal import Decimal
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

# Allowed deposit days-of-month (business rule)
ALLOWED_DEPOSIT_DAYS: frozenset[int] = frozenset({1, 5, 10, 15, 20, 25})


class SubscriptionStatus(Enum):
    """Subscription status enumeration."""

    INACTIVE = "inactive"
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

    # Cosmetic user-given name for this subscription
    name: str

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

    # Payment tracking
    deposits_paid: int = 0

    # Deposit due-date fields
    deposit_day_of_month: int = 1
    next_due_date: Optional[date] = None
    has_overdue_deposit: bool = False
    overdue_marked_at: Optional[datetime] = None

    # Whether the activation fees (admin_tax + insurance) were already paid
    # via a one-time activation payment. When True, all installments are
    # treated as "subsequent" (investment + fundo only).
    covers_activation_fees: bool = False

    status: SubscriptionStatus = SubscriptionStatus.INACTIVE
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
        if self.deposit_day_of_month not in ALLOWED_DEPOSIT_DAYS:
            raise ValueError(
                f"deposit_day_of_month must be one of {sorted(ALLOWED_DEPOSIT_DAYS)}"
            )
        # next_due_date can be None for INACTIVE subscriptions

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
        name: str = "",
        deposit_day_of_month: int = 1,
    ) -> UserPlanSubscription:
        """Factory method to create a new subscription.

        Creates the subscription in INACTIVE status. The subscription must be
        activated via activate() after the one-time activation payment is confirmed.

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
            name: Cosmetic user-given name for this subscription.
            deposit_day_of_month: Fixed day-of-month for deposits.

        Returns:
            A new UserPlanSubscription in INACTIVE status.

        Raises:
            ValueError: If any invariant is violated.
        """
        now = datetime.utcnow()

        return cls(
            id=uuid4(),
            user_id=user_id,
            plan_id=plan_id,
            name=name,
            target_amount_cents=target_amount_cents,
            deposit_count=deposit_count,
            monthly_amount_cents=monthly_amount_cents,
            admin_tax_value_cents=admin_tax_value_cents,
            insurance_percent=insurance_percent,
            guarantee_fund_percent=guarantee_fund_percent,
            total_cost_cents=total_cost_cents,
            deposits_paid=0,
            deposit_day_of_month=deposit_day_of_month,
            next_due_date=None,
            has_overdue_deposit=False,
            overdue_marked_at=None,
            covers_activation_fees=True,
            status=SubscriptionStatus.INACTIVE,
            created_at=now,
            updated_at=now,
        )

    # ------------------------------------------------------------------
    # Activation
    # ------------------------------------------------------------------

    def activate(self, deposit_day_of_month: int, today_local: date) -> None:
        """Activate the subscription after payment of the activation fee.

        Computes the first next_due_date and transitions status to ACTIVE.

        Args:
            deposit_day_of_month: Day of month for monthly deposits.
            today_local: Current calendar date in user timezone.

        Raises:
            ValueError: If subscription is not INACTIVE.
        """
        from app.domain.services.due_date_service import DueDateService

        if self.status != SubscriptionStatus.INACTIVE:
            raise ValueError(
                f"Cannot activate subscription in status {self.status.value}"
            )
        self.deposit_day_of_month = deposit_day_of_month
        self.next_due_date = DueDateService.compute_next_due_date(
            deposit_day_of_month, today_local
        )
        self.status = SubscriptionStatus.ACTIVE
        self.updated_at = datetime.utcnow()

    # ------------------------------------------------------------------
    # Deposit due-date mutation methods
    # ------------------------------------------------------------------

    def set_deposit_day(self, day: int, today_local: date) -> None:
        """Change the deposit day-of-month and recompute next_due_date.

        Args:
            day: New day-of-month (must be in ALLOWED_DEPOSIT_DAYS).
            today_local: Current calendar date in user timezone.

        Raises:
            ValueError: If day is not in the allowed set.
        """
        from app.domain.services.due_date_service import DueDateService

        if day not in ALLOWED_DEPOSIT_DAYS:
            raise ValueError(
                f"deposit_day_of_month must be one of {sorted(ALLOWED_DEPOSIT_DAYS)}"
            )
        self.deposit_day_of_month = day
        self.next_due_date = DueDateService.compute_next_due_date(day, today_local)
        self.updated_at = datetime.utcnow()

    def mark_overdue(self, now_utc: Optional[datetime] = None) -> bool:
        """Lazily mark this subscription as overdue.

        Only sets the flag if it is not already set (idempotent).

        Args:
            now_utc: Current UTC timestamp. Defaults to utcnow().

        Returns:
            True if the flag was actually changed (first time), False otherwise.
        """
        if self.has_overdue_deposit:
            return False
        self.has_overdue_deposit = True
        self.overdue_marked_at = now_utc or datetime.utcnow()
        self.updated_at = datetime.utcnow()
        return True

    def clear_overdue_and_advance(self, today_local: date) -> None:
        """Clear overdue flag and advance next_due_date after payment.

        Args:
            today_local: Current calendar date in user timezone.
        """
        from app.domain.services.due_date_service import DueDateService

        self.has_overdue_deposit = False
        self.overdue_marked_at = None
        self.next_due_date = DueDateService.advance_due_date(
            self.deposit_day_of_month, self.next_due_date
        )
        self.updated_at = datetime.utcnow()

    def record_deposit_paid(self, today_local: date) -> None:
        """Record a successful deposit payment for this subscription.

        Increments deposits_paid, clears overdue flag, advances due date.
        If all deposits are paid, marks subscription as completed.

        Args:
            today_local: Current calendar date in user timezone.

        Raises:
            ValueError: If subscription is not active or all deposits are already paid.
        """
        if self.status != SubscriptionStatus.ACTIVE:
            raise ValueError(
                f"Cannot record payment for subscription in status {self.status.value}"
            )
        if self.deposits_paid >= self.deposit_count:
            raise ValueError("All deposits already paid for this subscription")

        self.deposits_paid += 1
        self.clear_overdue_and_advance(today_local)

        if self.deposits_paid >= self.deposit_count:
            self.status = SubscriptionStatus.COMPLETED
            self.updated_at = datetime.utcnow()

    @property
    def current_installment_number(self) -> int:
        """The installment number that should be paid next (1-based)."""
        return self.deposits_paid + 1

    @property
    def is_fully_paid(self) -> bool:
        """Whether all installments have been paid."""
        return self.deposits_paid >= self.deposit_count

    @property
    def total_deposited_cents(self) -> int:
        """Total amount deposited based on payments recorded."""
        return self.deposits_paid * self.monthly_amount_cents

    def cancel(self) -> None:
        """Cancel the subscription.

        Raises:
            ValueError: If subscription is not active or inactive.
        """
        if self.status not in (SubscriptionStatus.ACTIVE, SubscriptionStatus.INACTIVE):
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
