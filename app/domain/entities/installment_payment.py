"""InstallmentPayment entity - Domain model for grouped installment payments.

Represents a single Pix payment that covers one or more subscription
installments. Every cent entering the platform is explicitly tied to
specific installments via InstallmentPaymentItem records.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import List, Optional
from uuid import UUID, uuid4


class PaymentStatus(Enum):
    """Payment status enumeration."""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    EXPIRED = "expired"


@dataclass
class InstallmentPaymentItem:
    """A single installment included in a grouped payment.

    Stores snapshot data at creation time for auditability.
    Each item links a payment to a specific subscription installment.
    """

    id: UUID
    payment_id: UUID
    subscription_id: UUID
    subscription_name: str  # snapshot for display
    plan_title: str  # snapshot for display
    amount_cents: int
    installment_number: int  # which installment of this subscription

    def __post_init__(self) -> None:
        if self.amount_cents <= 0:
            raise ValueError("Item amount must be positive")
        if self.installment_number < 1:
            raise ValueError("Installment number must be at least 1")


@dataclass
class InstallmentPayment:
    """Entity representing a grouped Pix payment for subscription installments.

    Invariant: total_amount_cents MUST equal the sum of item amounts.
    No free-form amount is accepted; every cent is tied to specific installments.
    """

    id: UUID
    user_id: UUID
    status: PaymentStatus
    total_amount_cents: int
    pix_qr_code_data: Optional[str]
    pix_transaction_id: Optional[str]
    expiration_minutes: int
    items: List[InstallmentPaymentItem]
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    confirmed_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        self._validate_invariants()

    def _validate_invariants(self) -> None:
        if self.total_amount_cents <= 0:
            raise ValueError("Total amount must be positive")
        if not self.items:
            raise ValueError("Payment must contain at least one item")
        items_total = sum(item.amount_cents for item in self.items)
        if items_total != self.total_amount_cents:
            raise ValueError(
                f"Total amount ({self.total_amount_cents}) does not match "
                f"sum of items ({items_total})"
            )

    @classmethod
    def create(
        cls,
        user_id: UUID,
        items_data: List[dict],
        pix_qr_code_data: str,
        expiration_minutes: int = 30,
    ) -> InstallmentPayment:
        """Factory method to create a new installment payment.

        Args:
            user_id: UUID of the user making the payment.
            items_data: List of dicts with keys: subscription_id, subscription_name,
                        plan_title, amount_cents, installment_number.
            pix_qr_code_data: Pix QR code payload.
            expiration_minutes: QR code expiration in minutes.

        Returns:
            A new InstallmentPayment in PENDING status.

        Raises:
            ValueError: If items_data is empty or any invariant is violated.
        """
        if not items_data:
            raise ValueError("Must select at least one installment")

        payment_id = uuid4()
        now = datetime.utcnow()

        items = [
            InstallmentPaymentItem(
                id=uuid4(),
                payment_id=payment_id,
                subscription_id=item["subscription_id"],
                subscription_name=item["subscription_name"],
                plan_title=item["plan_title"],
                amount_cents=item["amount_cents"],
                installment_number=item["installment_number"],
            )
            for item in items_data
        ]

        total = sum(item.amount_cents for item in items)

        return cls(
            id=payment_id,
            user_id=user_id,
            status=PaymentStatus.PENDING,
            total_amount_cents=total,
            pix_qr_code_data=pix_qr_code_data,
            pix_transaction_id=None,
            expiration_minutes=expiration_minutes,
            items=items,
            created_at=now,
            updated_at=now,
            confirmed_at=None,
        )

    def confirm(self, pix_transaction_id: str) -> bool:
        """Confirm the payment after Pix verification.

        Idempotent: returns False if already confirmed.

        Args:
            pix_transaction_id: Pix transaction ID from gateway.

        Returns:
            True if status was changed, False if already confirmed.

        Raises:
            ValueError: If payment is in a terminal state (cancelled/failed/expired).
        """
        if self.status == PaymentStatus.CONFIRMED:
            return False  # idempotent

        if self.status != PaymentStatus.PENDING:
            raise ValueError(
                f"Cannot confirm payment in {self.status.value} status"
            )

        self.status = PaymentStatus.CONFIRMED
        self.pix_transaction_id = pix_transaction_id
        self.confirmed_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()
        return True

    def cancel(self) -> None:
        """Cancel the payment."""
        if self.status != PaymentStatus.PENDING:
            raise ValueError(
                f"Cannot cancel payment in {self.status.value} status"
            )
        self.status = PaymentStatus.CANCELLED
        self.updated_at = datetime.utcnow()

    def fail(self) -> None:
        """Mark payment as failed."""
        if self.status != PaymentStatus.PENDING:
            raise ValueError(
                f"Cannot fail payment in {self.status.value} status"
            )
        self.status = PaymentStatus.FAILED
        self.updated_at = datetime.utcnow()

    def expire(self) -> None:
        """Mark payment as expired."""
        if self.status != PaymentStatus.PENDING:
            raise ValueError(
                f"Cannot expire payment in {self.status.value} status"
            )
        self.status = PaymentStatus.EXPIRED
        self.updated_at = datetime.utcnow()

    def is_pending(self) -> bool:
        """Check if payment is pending."""
        return self.status == PaymentStatus.PENDING

    def is_confirmed(self) -> bool:
        """Check if payment is confirmed."""
        return self.status == PaymentStatus.CONFIRMED

    def is_stale(self, now: Optional[datetime] = None) -> bool:
        """Check if a pending payment has exceeded its expiration window.

        Non-pending payments are never stale.
        Uses UTC comparison. ``created_at`` is assumed UTC.

        Args:
            now: Current UTC time. Defaults to ``datetime.now(timezone.utc)``.

        Returns:
            True if pending and older than ``expiration_minutes``.
        """
        if self.status != PaymentStatus.PENDING:
            return False
        if now is None:
            now = datetime.now(timezone.utc)
        # created_at may be naive (utcnow) — treat as UTC
        created = self.created_at.replace(tzinfo=timezone.utc) if self.created_at.tzinfo is None else self.created_at
        return now >= created + timedelta(minutes=self.expiration_minutes)
