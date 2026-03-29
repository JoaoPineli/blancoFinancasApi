"""SubscriptionActivationPayment entity.

Represents a one-time Pix payment charged at subscription activation.
Covers: admin tax + insurance. Monthly installments do NOT repeat these.
A PIX transaction fee (0.99%) is added on top and tracked for auditability.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4


class ActivationPaymentStatus(Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    EXPIRED = "expired"


@dataclass
class SubscriptionActivationPayment:
    id: UUID
    user_id: UUID
    subscription_id: UUID
    status: ActivationPaymentStatus
    admin_tax_cents: int         # snapshot of plan admin tax
    insurance_cents: int         # insurance = monthly_amount * insurance_percent / 100
    pix_transaction_fee_cents: int  # 0.99% of (admin_tax + insurance)
    total_amount_cents: int      # admin_tax + insurance + pix_fee
    pix_qr_code_data: Optional[str]
    pix_transaction_id: Optional[str]
    expiration_minutes: int
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    confirmed_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        self._validate_invariants()

    def _validate_invariants(self) -> None:
        if self.admin_tax_cents < 0:
            raise ValueError("admin_tax_cents cannot be negative")
        if self.insurance_cents < 0:
            raise ValueError("insurance_cents cannot be negative")
        if self.pix_transaction_fee_cents < 0:
            raise ValueError("pix_transaction_fee_cents cannot be negative")
        expected = self.admin_tax_cents + self.insurance_cents + self.pix_transaction_fee_cents
        if self.total_amount_cents != expected:
            raise ValueError(
                f"total_amount_cents ({self.total_amount_cents}) must equal "
                f"admin_tax + insurance + pix_fee ({expected})"
            )
        if self.total_amount_cents <= 0:
            raise ValueError("total_amount_cents must be positive")

    @classmethod
    def create(
        cls,
        user_id: UUID,
        subscription_id: UUID,
        admin_tax_cents: int,
        insurance_cents: int,
        pix_transaction_fee_cents: int,
        pix_qr_code_data: str,
        expiration_minutes: int = 30,
    ) -> SubscriptionActivationPayment:
        now = datetime.utcnow()
        total = admin_tax_cents + insurance_cents + pix_transaction_fee_cents
        return cls(
            id=uuid4(),
            user_id=user_id,
            subscription_id=subscription_id,
            status=ActivationPaymentStatus.PENDING,
            admin_tax_cents=admin_tax_cents,
            insurance_cents=insurance_cents,
            pix_transaction_fee_cents=pix_transaction_fee_cents,
            total_amount_cents=total,
            pix_qr_code_data=pix_qr_code_data,
            pix_transaction_id=None,
            expiration_minutes=expiration_minutes,
            created_at=now,
            updated_at=now,
            confirmed_at=None,
        )

    def confirm(self, pix_transaction_id: str) -> bool:
        """Idempotent confirm. Returns True if status changed."""
        if self.status == ActivationPaymentStatus.CONFIRMED:
            return False
        if self.status != ActivationPaymentStatus.PENDING:
            raise ValueError(f"Cannot confirm payment in {self.status.value} status")
        self.status = ActivationPaymentStatus.CONFIRMED
        self.pix_transaction_id = pix_transaction_id
        self.confirmed_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()
        return True

    def cancel(self) -> None:
        if self.status != ActivationPaymentStatus.PENDING:
            raise ValueError(f"Cannot cancel payment in {self.status.value} status")
        self.status = ActivationPaymentStatus.CANCELLED
        self.updated_at = datetime.utcnow()

    def fail(self) -> None:
        if self.status != ActivationPaymentStatus.PENDING:
            raise ValueError(f"Cannot fail payment in {self.status.value} status")
        self.status = ActivationPaymentStatus.FAILED
        self.updated_at = datetime.utcnow()

    def expire(self) -> None:
        if self.status != ActivationPaymentStatus.PENDING:
            raise ValueError(f"Cannot expire payment in {self.status.value} status")
        self.status = ActivationPaymentStatus.EXPIRED
        self.updated_at = datetime.utcnow()

    def is_pending(self) -> bool:
        return self.status == ActivationPaymentStatus.PENDING

    def is_confirmed(self) -> bool:
        return self.status == ActivationPaymentStatus.CONFIRMED

    def is_stale(self, now: Optional[datetime] = None) -> bool:
        if self.status != ActivationPaymentStatus.PENDING:
            return False
        if now is None:
            now = datetime.now(timezone.utc)
        created = self.created_at.replace(tzinfo=timezone.utc) if self.created_at.tzinfo is None else self.created_at
        return now >= created + timedelta(minutes=self.expiration_minutes)
