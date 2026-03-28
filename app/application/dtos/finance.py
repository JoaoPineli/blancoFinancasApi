"""Finance DTOs."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID


@dataclass
class WalletDTO:
    """Wallet data transfer object."""

    id: UUID
    user_id: UUID
    balance_cents: int
    total_invested_cents: int
    total_yield_cents: int
    fundo_garantidor_cents: int


@dataclass
class TransactionDTO:
    """Transaction data transfer object."""

    id: UUID
    user_id: UUID
    contract_id: Optional[UUID]
    transaction_type: str
    status: str
    amount_cents: int
    installment_number: Optional[int]
    installment_type: Optional[str]
    pix_key: Optional[str]
    pix_transaction_id: Optional[str]
    bank_account: Optional[str]
    description: Optional[str]
    created_at: datetime
    confirmed_at: Optional[datetime]


@dataclass
class CreateDepositInput:
    """Input for creating a deposit."""

    user_id: UUID
    contract_id: UUID
    amount_cents: int
    installment_number: int


@dataclass
class CreateDepositResult:
    """Result of deposit creation."""

    transaction_id: UUID
    pix_qr_code_data: str
    amount_cents: int
    expiration_minutes: int


@dataclass
class CreateWithdrawalInput:
    """Input for creating a withdrawal request."""

    user_id: UUID
    amount_cents: int
    bank_account: str
    description: Optional[str] = None


@dataclass
class ApproveWithdrawalInput:
    """Input for approving a withdrawal."""

    transaction_id: UUID
    admin_id: UUID


# ------------------------------------------------------------------
# Installment Payment DTOs
# ------------------------------------------------------------------


@dataclass
class PayableInstallmentDTO:
    """A single payable installment derived from an active subscription."""

    subscription_id: UUID
    subscription_name: str
    plan_title: str
    installment_number: int
    total_installments: int
    amount_cents: int
    due_date: str  # ISO date
    is_overdue: bool
    status: str  # "overdue", "due_today", "upcoming"
    pending_payment_id: Optional[UUID] = None  # existing pending payment, if any


@dataclass
class PayableInstallmentsResult:
    """Result of listing payable installments."""

    installments: List[PayableInstallmentDTO]
    total: int


@dataclass
class CreateInstallmentPaymentInput:
    """Input for creating a grouped installment payment."""

    user_id: UUID
    subscription_ids: List[UUID]


@dataclass
class InstallmentPaymentItemDTO:
    """DTO for a single item within an installment payment."""

    id: UUID
    subscription_id: UUID
    subscription_name: str
    plan_title: str
    amount_cents: int
    installment_number: int


@dataclass
class InstallmentPaymentDTO:
    """DTO for a grouped installment payment."""

    id: UUID
    user_id: UUID
    status: str
    total_amount_cents: int
    pix_qr_code_data: Optional[str]
    pix_transaction_id: Optional[str]
    expiration_minutes: int
    items: List[InstallmentPaymentItemDTO]
    created_at: datetime
    updated_at: datetime
    confirmed_at: Optional[datetime]


# ------------------------------------------------------------------
# Withdrawal / Plan closure DTOs
# ------------------------------------------------------------------


@dataclass
class WithdrawableSubscriptionDTO:
    """A subscription eligible for value withdrawal."""

    subscription_id: UUID
    subscription_name: str
    plan_title: str
    status: str
    is_early_termination: bool
    withdrawable_amount_cents: int
    deposits_paid: int
    deposit_count: int
    created_at: str  # ISO format


@dataclass
class WithdrawableSubscriptionsResult:
    """Result of listing withdrawable subscriptions."""

    subscriptions: List[WithdrawableSubscriptionDTO]
    total: int


@dataclass
class RequestPlanWithdrawalInput:
    """Input for requesting a plan withdrawal."""

    user_id: UUID
    subscription_id: UUID


@dataclass
class PlanWithdrawalDTO:
    """DTO for a plan withdrawal request."""

    subscription_id: UUID
    subscription_name: str
    plan_title: str
    status: str
    amount_cents: int
    is_early_termination: bool
    created_at: datetime


# ------------------------------------------------------------------
# History DTOs
# ------------------------------------------------------------------


@dataclass
class HistoryEventDTO:
    """A single event in the user's financial history."""

    id: UUID
    event_type: str  # "installment_payment", "plan_withdrawal"
    status: str
    amount_cents: int
    description: str
    plan_titles: List[str]
    subscription_ids: List[str]
    created_at: datetime
    confirmed_at: Optional[datetime] = None


@dataclass
class HistoryResult:
    """Result of listing financial history."""

    events: List[HistoryEventDTO]
    total: int
