"""Transaction entity - Domain model for financial transactions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, List, Optional
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from app.domain.entities.transaction_item import TransactionItem

from app.domain.exceptions import InvalidTransactionStatusError


class TransactionType(Enum):
    """Transaction type enumeration."""

    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    YIELD = "yield"
    FEE = "fee"
    FUNDO_GARANTIDOR = "fundo_garantidor"
    SUBSCRIPTION_INSTALLMENT_PAYMENT = "subscription_installment_payment"
    SUBSCRIPTION_ACTIVATION_PAYMENT = "subscription_activation_payment"


class TransactionStatus(Enum):
    """Transaction status enumeration."""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    EXPIRED = "expired"


class InstallmentType(Enum):
    """Installment type for deposits."""

    FIRST = "first"  # First installment (Fees + Insurance + Fundo)
    SUBSEQUENT = "subsequent"  # Subsequent installments (Investment + Fundo)


@dataclass
class Transaction:
    """Transaction entity representing a financial operation.

    Tracks deposits, withdrawals, yields, fees, and Fundo Garantidor.
    All monetary values stored in cents.
    """

    id: UUID
    user_id: UUID
    contract_id: Optional[UUID]
    subscription_id: Optional[UUID]
    transaction_type: TransactionType
    status: TransactionStatus
    amount_cents: int
    installment_number: Optional[int]
    installment_type: Optional[InstallmentType]
    pix_key: Optional[str]
    pix_key_type: Optional[str]
    pix_transaction_id: Optional[str]
    bank_account: Optional[str]
    description: Optional[str]
    rejection_reason: Optional[str]
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    confirmed_at: Optional[datetime] = None
    # Payment-flow fields (used by SUBSCRIPTION_INSTALLMENT_PAYMENT and SUBSCRIPTION_ACTIVATION_PAYMENT)
    pix_qr_code_data: Optional[str] = None
    pix_qr_code_base64: Optional[str] = None
    expiration_minutes: Optional[int] = None
    pix_transaction_fee_cents: int = 0
    # Activation-payment breakdown snapshots (SUBSCRIPTION_ACTIVATION_PAYMENT only)
    admin_tax_cents: Optional[int] = None
    insurance_cents: Optional[int] = None
    # Items are loaded on demand (not always present)
    items: List["TransactionItem"] = field(default_factory=list)

    @classmethod
    def create_deposit(
        cls,
        user_id: UUID,
        contract_id: UUID,
        amount_cents: int,
        installment_number: int,
        installment_type: InstallmentType,
        pix_key: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Transaction:
        """Factory method to create a deposit transaction."""
        now = datetime.utcnow()
        return cls(
            id=uuid4(),
            user_id=user_id,
            contract_id=contract_id,
            subscription_id=None,
            transaction_type=TransactionType.DEPOSIT,
            status=TransactionStatus.PENDING,
            amount_cents=amount_cents,
            installment_number=installment_number,
            installment_type=installment_type,
            pix_key=pix_key,
            pix_key_type=None,
            pix_transaction_id=None,
            bank_account=None,
            description=description,
            rejection_reason=None,
            created_at=now,
            updated_at=now,
        )

    @classmethod
    def create_withdrawal(
        cls,
        user_id: UUID,
        amount_cents: int,
        bank_account: str,
        description: Optional[str] = None,
        pix_key: Optional[str] = None,
        pix_key_type: Optional[str] = None,
        subscription_id: Optional[UUID] = None,
    ) -> Transaction:
        """Factory method to create a withdrawal transaction."""
        now = datetime.utcnow()
        return cls(
            id=uuid4(),
            user_id=user_id,
            contract_id=None,
            subscription_id=subscription_id,
            transaction_type=TransactionType.WITHDRAWAL,
            status=TransactionStatus.PENDING,
            amount_cents=amount_cents,
            installment_number=None,
            installment_type=None,
            pix_key=pix_key,
            pix_key_type=pix_key_type,
            pix_transaction_id=None,
            bank_account=bank_account,
            description=description,
            rejection_reason=None,
            created_at=now,
            updated_at=now,
        )

    @classmethod
    def create_yield(
        cls,
        user_id: UUID,
        amount_cents: int,
        description: str,
        contract_id: Optional[UUID] = None,
        subscription_id: Optional[UUID] = None,
    ) -> Transaction:
        """Factory method to create a yield transaction."""
        now = datetime.utcnow()
        return cls(
            id=uuid4(),
            user_id=user_id,
            contract_id=contract_id,
            subscription_id=subscription_id,
            transaction_type=TransactionType.YIELD,
            status=TransactionStatus.CONFIRMED,  # Yields are auto-confirmed
            amount_cents=amount_cents,
            installment_number=None,
            installment_type=None,
            pix_key=None,
            pix_key_type=None,
            pix_transaction_id=None,
            bank_account=None,
            description=description,
            rejection_reason=None,
            created_at=now,
            updated_at=now,
            confirmed_at=now,
        )

    @classmethod
    def create_fundo_garantidor(
        cls,
        user_id: UUID,
        contract_id: UUID,
        amount_cents: int,
        installment_number: int,
    ) -> Transaction:
        """Factory method to create a Fundo Garantidor transaction."""
        now = datetime.utcnow()
        return cls(
            id=uuid4(),
            user_id=user_id,
            contract_id=contract_id,
            subscription_id=None,
            transaction_type=TransactionType.FUNDO_GARANTIDOR,
            status=TransactionStatus.CONFIRMED,
            amount_cents=amount_cents,
            installment_number=installment_number,
            installment_type=None,
            pix_key=None,
            pix_key_type=None,
            pix_transaction_id=None,
            bank_account=None,
            description=f"Fundo Garantidor - Parcela {installment_number}",
            rejection_reason=None,
            created_at=now,
            updated_at=now,
            confirmed_at=now,
        )

    @classmethod
    def create_installment_payment(
        cls,
        user_id: UUID,
        total_amount_cents: int,
        pix_qr_code_data: str,
        expiration_minutes: int,
        pix_transaction_fee_cents: int = 0,
        pix_transaction_id: Optional[str] = None,
    ) -> "Transaction":
        """Factory for a grouped subscription installment payment."""
        now = datetime.utcnow()
        return cls(
            id=uuid4(),
            user_id=user_id,
            contract_id=None,
            subscription_id=None,
            transaction_type=TransactionType.SUBSCRIPTION_INSTALLMENT_PAYMENT,
            status=TransactionStatus.PENDING,
            amount_cents=total_amount_cents,
            installment_number=None,
            installment_type=None,
            pix_key=None,
            pix_key_type=None,
            pix_transaction_id=pix_transaction_id,
            bank_account=None,
            description=None,
            rejection_reason=None,
            created_at=now,
            updated_at=now,
            confirmed_at=None,
            pix_qr_code_data=pix_qr_code_data,
            expiration_minutes=expiration_minutes,
            pix_transaction_fee_cents=pix_transaction_fee_cents,
        )

    @classmethod
    def create_activation_payment(
        cls,
        user_id: UUID,
        subscription_id: UUID,
        admin_tax_cents: int,
        insurance_cents: int,
        pix_transaction_fee_cents: int,
        pix_qr_code_data: str,
        expiration_minutes: int,
        pix_transaction_id: Optional[str] = None,
    ) -> "Transaction":
        """Factory for a one-time subscription activation payment."""
        now = datetime.utcnow()
        total = admin_tax_cents + insurance_cents + pix_transaction_fee_cents
        return cls(
            id=uuid4(),
            user_id=user_id,
            contract_id=None,
            subscription_id=subscription_id,
            transaction_type=TransactionType.SUBSCRIPTION_ACTIVATION_PAYMENT,
            status=TransactionStatus.PENDING,
            amount_cents=total,
            installment_number=None,
            installment_type=None,
            pix_key=None,
            pix_key_type=None,
            pix_transaction_id=pix_transaction_id,
            bank_account=None,
            description=None,
            rejection_reason=None,
            created_at=now,
            updated_at=now,
            confirmed_at=None,
            pix_qr_code_data=pix_qr_code_data,
            expiration_minutes=expiration_minutes,
            pix_transaction_fee_cents=pix_transaction_fee_cents,
            admin_tax_cents=admin_tax_cents,
            insurance_cents=insurance_cents,
        )

    def confirm(self, pix_transaction_id: Optional[str] = None) -> None:
        """Confirm the transaction.

        Args:
            pix_transaction_id: Pix transaction ID from payment gateway
        """
        if self.status != TransactionStatus.PENDING:
            raise InvalidTransactionStatusError(
                self.status.value, TransactionStatus.CONFIRMED.value
            )

        self.status = TransactionStatus.CONFIRMED
        self.confirmed_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()
        if pix_transaction_id:
            self.pix_transaction_id = pix_transaction_id

    def confirm_payment(self, pix_transaction_id: str) -> bool:
        """Idempotent confirm for payment transactions.

        Returns:
            True if status was changed to CONFIRMED.
            False if already CONFIRMED (idempotent).
        Raises:
            ValueError if in a terminal non-confirmed state.
        """
        if self.status == TransactionStatus.CONFIRMED:
            return False
        if self.status != TransactionStatus.PENDING:
            raise ValueError(
                f"Cannot confirm payment in {self.status.value} status"
            )
        self.status = TransactionStatus.CONFIRMED
        self.pix_transaction_id = pix_transaction_id
        self.confirmed_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()
        return True

    def expire(self) -> None:
        """Mark payment as expired."""
        if self.status != TransactionStatus.PENDING:
            raise ValueError(
                f"Cannot expire transaction in {self.status.value} status"
            )
        self.status = TransactionStatus.EXPIRED
        self.updated_at = datetime.utcnow()

    def is_stale(self, now: Optional[datetime] = None) -> bool:
        """Check if a pending payment has exceeded its expiration window."""
        if self.status != TransactionStatus.PENDING:
            return False
        if self.expiration_minutes is None:
            return False
        if now is None:
            now = datetime.now(timezone.utc)
        created = (
            self.created_at.replace(tzinfo=timezone.utc)
            if self.created_at.tzinfo is None
            else self.created_at
        )
        return now >= created + timedelta(minutes=self.expiration_minutes)

    def cancel(self) -> None:
        """Cancel the transaction."""
        if self.status != TransactionStatus.PENDING:
            raise InvalidTransactionStatusError(
                self.status.value, TransactionStatus.CANCELLED.value
            )

        self.status = TransactionStatus.CANCELLED
        self.updated_at = datetime.utcnow()

    def reject_with_reason(self, reason: str) -> None:
        """Cancel the transaction with an admin rejection reason."""
        self.rejection_reason = reason
        self.cancel()

    def fail(self) -> None:
        """Mark transaction as failed."""
        if self.status != TransactionStatus.PENDING:
            raise InvalidTransactionStatusError(
                self.status.value, TransactionStatus.FAILED.value
            )

        self.status = TransactionStatus.FAILED
        self.updated_at = datetime.utcnow()

    def is_pending(self) -> bool:
        """Check if transaction is pending."""
        return self.status == TransactionStatus.PENDING

    def is_confirmed(self) -> bool:
        """Check if transaction is confirmed."""
        return self.status == TransactionStatus.CONFIRMED

    @property
    def amount(self) -> Decimal:
        """Get amount as decimal."""
        return Decimal(self.amount_cents) / Decimal(100)
