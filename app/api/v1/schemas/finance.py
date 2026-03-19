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


# ------------------------------------------------------------------
# Installment Payment Schemas
# ------------------------------------------------------------------


class PayableInstallmentResponse(BaseModel):
    """Response schema for a single payable installment."""

    subscription_id: str = Field(..., description="Subscription UUID")
    subscription_name: str = Field(..., description="Subscription name")
    plan_title: str = Field(..., description="Plan title")
    installment_number: int = Field(..., description="Current installment number")
    total_installments: int = Field(..., description="Total installments in plan")
    amount_cents: int = Field(..., description="Installment amount in cents")
    due_date: str = Field(..., description="Due date (ISO format)")
    is_overdue: bool = Field(..., description="Whether the installment is overdue")
    status: str = Field(..., description="Status: overdue, due_today, upcoming")
    pending_payment_id: Optional[str] = Field(
        None, description="UUID of existing pending payment, if any"
    )


class PayableInstallmentsListResponse(BaseModel):
    """Response schema for list of payable installments."""

    installments: list[PayableInstallmentResponse] = Field(
        ..., description="List of payable installments"
    )
    total: int = Field(..., description="Total count")


class CreateInstallmentPaymentRequest(BaseModel):
    """Request schema for creating a grouped installment payment."""

    subscription_ids: list[str] = Field(
        ..., min_length=1, description="UUIDs of subscriptions to pay"
    )


class InstallmentPaymentItemResponse(BaseModel):
    """Response schema for a single item within an installment payment."""

    id: str = Field(..., description="Item UUID")
    subscription_id: str = Field(..., description="Subscription UUID")
    subscription_name: str = Field(..., description="Subscription name snapshot")
    plan_title: str = Field(..., description="Plan title snapshot")
    amount_cents: int = Field(..., description="Item amount in cents")
    installment_number: int = Field(..., description="Installment number")


class InstallmentPaymentResponse(BaseModel):
    """Response schema for a grouped installment payment."""

    id: str = Field(..., description="Payment UUID")
    user_id: str = Field(..., description="User UUID")
    status: str = Field(..., description="Payment status")
    total_amount_cents: int = Field(..., description="Total amount in cents")
    pix_qr_code_data: Optional[str] = Field(None, description="Pix QR Code payload")
    pix_transaction_id: Optional[str] = Field(None, description="Pix transaction ID")
    expiration_minutes: int = Field(..., description="QR Code expiration in minutes")
    items: list[InstallmentPaymentItemResponse] = Field(
        ..., description="Payment items"
    )
    created_at: str = Field(..., description="Creation date (ISO format)")
    updated_at: str = Field(..., description="Last update date (ISO format)")
    confirmed_at: Optional[str] = Field(None, description="Confirmation date (ISO format)")


# ------------------------------------------------------------------
# Withdrawal / Plan Closure Schemas
# ------------------------------------------------------------------


class WithdrawableSubscriptionResponse(BaseModel):
    """Response schema for a subscription eligible for withdrawal."""

    subscription_id: str = Field(..., description="Subscription UUID")
    subscription_name: str = Field(..., description="Subscription name")
    plan_title: str = Field(..., description="Plan title")
    status: str = Field(..., description="Subscription status")
    is_early_termination: bool = Field(
        ..., description="Whether this is an early termination"
    )
    withdrawable_amount_cents: int = Field(
        ..., description="Amount available for withdrawal in cents"
    )
    deposits_paid: int = Field(..., description="Number of deposits paid")
    deposit_count: int = Field(..., description="Total number of deposits")
    created_at: str = Field(..., description="Subscription creation date (ISO format)")


class WithdrawableSubscriptionsListResponse(BaseModel):
    """Response schema for list of withdrawable subscriptions."""

    subscriptions: list[WithdrawableSubscriptionResponse] = Field(
        ..., description="List of withdrawable subscriptions"
    )
    total: int = Field(..., description="Total count")


class RequestPlanWithdrawalRequest(BaseModel):
    """Request schema for requesting a plan withdrawal."""

    subscription_id: str = Field(..., description="Subscription UUID")


class PlanWithdrawalResponse(BaseModel):
    """Response schema for a plan withdrawal request."""

    subscription_id: str = Field(..., description="Subscription UUID")
    subscription_name: str = Field(..., description="Subscription name")
    plan_title: str = Field(..., description="Plan title")
    status: str = Field(..., description="Withdrawal status")
    amount_cents: int = Field(..., description="Withdrawal amount in cents")
    is_early_termination: bool = Field(
        ..., description="Whether this was an early termination"
    )
    created_at: str = Field(..., description="Date (ISO format)")


# ------------------------------------------------------------------
# History Schemas
# ------------------------------------------------------------------


class HistoryEventResponse(BaseModel):
    """Response schema for a single event in financial history."""

    id: str = Field(..., description="Event UUID")
    event_type: str = Field(
        ..., description="Event type: installment_payment or plan_withdrawal"
    )
    status: str = Field(..., description="Event status")
    amount_cents: int = Field(..., description="Amount in cents")
    description: str = Field(..., description="Human-readable description")
    plan_titles: list[str] = Field(
        default_factory=list, description="Associated plan titles"
    )
    created_at: str = Field(..., description="Date (ISO format)")
    confirmed_at: Optional[str] = Field(None, description="Confirmation date (ISO format)")


class HistoryListResponse(BaseModel):
    """Response schema for financial history."""

    events: list[HistoryEventResponse] = Field(
        ..., description="List of history events"
    )
    total: int = Field(..., description="Total count")


# ------------------------------------------------------------------
# Yield Processing Schemas (admin)
# ------------------------------------------------------------------


class ProcessYieldsRequest(BaseModel):
    """Optional request body for the yield processing admin endpoint.

    If target_date is omitted, the server uses the current date (UTC).
    """

    target_date: Optional[str] = Field(
        None,
        description="ISO date (YYYY-MM-DD) to use as calculation reference. "
        "Defaults to today (UTC) if not provided.",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    )


class ProcessYieldsResponse(BaseModel):
    """Response schema for the yield processing admin endpoint."""

    calculation_date: str = Field(..., description="Date used as yield reference (ISO)")
    deposits_evaluated: int = Field(..., description="Total deposits examined")
    deposits_credited: int = Field(..., description="Deposits that received new yield")
    total_yield_cents: int = Field(..., description="Total yield credited in cents")


# ------------------------------------------------------------------
# Dashboard Schema
# ------------------------------------------------------------------


class DashboardResponse(BaseModel):
    """Response schema for the client financial dashboard."""

    total_balance_cents: int = Field(..., description="Total wallet balance in cents")
    yield_this_month_cents: int = Field(
        ..., description="Confirmed yield credited in the current UTC month (cents)"
    )
    reference_month: str = Field(..., description="Reference month in YYYY-MM format (UTC)")
