"""Finance DTOs."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional
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
