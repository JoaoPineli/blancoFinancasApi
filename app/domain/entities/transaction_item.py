"""TransactionItem entity — one line-item within a payment transaction.

Each SUBSCRIPTION_INSTALLMENT_PAYMENT or SUBSCRIPTION_ACTIVATION_PAYMENT
transaction has one or more TransactionItems linking it to specific
subscriptions and installment numbers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from uuid import UUID, uuid4


@dataclass
class TransactionItem:
    """A single subscription line-item within a payment transaction.

    For installment payments: one item per subscription being paid.
    For activation payments: one item per subscription (the activation fee).
    installment_number is None for activation items.
    """

    id: UUID
    transaction_id: UUID
    subscription_id: UUID
    subscription_name: str  # snapshot at creation time
    plan_title: str         # snapshot at creation time
    amount_cents: int
    installment_number: Optional[int]  # None for activation items

    def __post_init__(self) -> None:
        if self.amount_cents <= 0:
            raise ValueError("TransactionItem amount must be positive")

    @classmethod
    def create(
        cls,
        transaction_id: UUID,
        subscription_id: UUID,
        subscription_name: str,
        plan_title: str,
        amount_cents: int,
        installment_number: Optional[int] = None,
    ) -> "TransactionItem":
        return cls(
            id=uuid4(),
            transaction_id=transaction_id,
            subscription_id=subscription_id,
            subscription_name=subscription_name,
            plan_title=plan_title,
            amount_cents=amount_cents,
            installment_number=installment_number,
        )
