"""Principal Deposit entity - Domain model for per-installment principal tracking.

Each confirmed SUBSCRIPTION_INSTALLMENT_PAYMENT TransactionItem produces one
PrincipalDeposit. The deposited_at date is the anchor for poupança anniversary
yield calculation.

Idempotency design:
  last_yield_run_date tracks the last date the yield job ran for this deposit.
  Delta = calculate_yield(deposited_at → today) - calculate_yield(deposited_at → last_yield_run_date)
  Running the job twice on the same date produces delta = 0 → no double-credit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional
from uuid import UUID, uuid4


@dataclass
class PrincipalDeposit:
    """Tracks the investment portion of a single confirmed installment.

    principal_cents is the investment_amount after InstallmentCalculator breakdown
    (i.e., the amount that actually earns poupança yield, excluding fundo/fees).
    """

    id: UUID
    user_id: UUID
    subscription_id: UUID
    transaction_item_id: UUID  # UNIQUE — one deposit per transaction item
    installment_number: int
    principal_cents: int  # investment_amount from InstallmentCalculator
    deposited_at: date  # confirmation date — poupança anniversary anchor
    last_yield_run_date: Optional[date]  # None = never processed
    created_at: datetime = field(default_factory=datetime.utcnow)

    @classmethod
    def create(
        cls,
        user_id: UUID,
        subscription_id: UUID,
        transaction_item_id: UUID,
        installment_number: int,
        principal_cents: int,
        deposited_at: date,
    ) -> "PrincipalDeposit":
        """Factory method to create a new principal deposit record."""
        return cls(
            id=uuid4(),
            user_id=user_id,
            subscription_id=subscription_id,
            transaction_item_id=transaction_item_id,
            installment_number=installment_number,
            principal_cents=principal_cents,
            deposited_at=deposited_at,
            last_yield_run_date=None,
            created_at=datetime.utcnow(),
        )
