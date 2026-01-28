"""Finance schemas."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class WalletResponse(BaseModel):
    """Response schema for wallet data."""

    id: str = Field(..., description="Wallet UUID")
    user_id: str = Field(..., description="User UUID")
    balance_cents: int = Field(..., description="Available balance in cents")
    total_invested_cents: int = Field(..., description="Total invested in cents")
    total_yield_cents: int = Field(..., description="Total yield earned in cents")
    fundo_garantidor_cents: int = Field(..., description="Fundo Garantidor in cents")


class TransactionResponse(BaseModel):
    """Response schema for transaction data."""

    id: str = Field(..., description="Transaction UUID")
    user_id: str = Field(..., description="User UUID")
    contract_id: Optional[str] = Field(None, description="Contract UUID")
    transaction_type: str = Field(..., description="Transaction type")
    status: str = Field(..., description="Transaction status")
    amount_cents: int = Field(..., description="Amount in cents")
    installment_number: Optional[int] = Field(None, description="Installment number")
    installment_type: Optional[str] = Field(None, description="Installment type")
    pix_key: Optional[str] = Field(None, description="Pix key")
    pix_transaction_id: Optional[str] = Field(None, description="Pix transaction ID")
    bank_account: Optional[str] = Field(None, description="Bank account")
    description: Optional[str] = Field(None, description="Description")
    created_at: datetime = Field(..., description="Creation date")
    confirmed_at: Optional[datetime] = Field(None, description="Confirmation date")


class TransactionListResponse(BaseModel):
    """Response schema for transaction list."""

    transactions: list[TransactionResponse] = Field(..., description="List of transactions")
    total: int = Field(..., description="Total count")


class CreateDepositRequest(BaseModel):
    """Request schema for creating a deposit."""

    contract_id: str = Field(..., description="Contract UUID")
    amount_cents: int = Field(..., gt=0, description="Amount in cents")
    installment_number: int = Field(..., gt=0, description="Installment number")


class CreateDepositResponse(BaseModel):
    """Response schema for deposit creation."""

    transaction_id: str = Field(..., description="Transaction UUID")
    pix_qr_code_data: str = Field(..., description="Pix QR Code payload data")
    amount_cents: int = Field(..., description="Amount in cents")
    expiration_minutes: int = Field(..., description="QR Code expiration in minutes")


class CreateWithdrawalRequest(BaseModel):
    """Request schema for creating a withdrawal."""

    amount_cents: int = Field(..., gt=0, description="Amount in cents")
    bank_account: str = Field(..., min_length=5, max_length=100, description="Bank account info")
    description: Optional[str] = Field(None, max_length=500, description="Description")


class ApproveWithdrawalRequest(BaseModel):
    """Request schema for approving a withdrawal."""

    transaction_id: str = Field(..., description="Transaction UUID")


class RejectWithdrawalRequest(BaseModel):
    """Request schema for rejecting a withdrawal."""

    transaction_id: str = Field(..., description="Transaction UUID")
    reason: str = Field(..., min_length=5, max_length=500, description="Rejection reason")


class PixWebhookPayload(BaseModel):
    """Webhook payload from Pix gateway."""

    pix_id: str = Field(..., description="Pix transaction ID")
    amount: float = Field(..., description="Amount in reais")
    status: str = Field(..., description="Payment status")
    payer_cpf: Optional[str] = Field(None, description="Payer CPF")
    payer_name: Optional[str] = Field(None, description="Payer name")
    timestamp: str = Field(..., description="Event timestamp ISO format")
