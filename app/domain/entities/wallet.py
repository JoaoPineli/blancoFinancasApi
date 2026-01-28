"""Wallet entity - Domain model for users wallets."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4

from app.domain.exceptions import InsufficientBalanceError
from app.domain.value_objects.money import Money


@dataclass
class Wallet:
    """Wallet entity representing a user's balance.

    Encapsulates balance operations with invariant validation.
    All monetary values stored in cents.
    """

    id: UUID
    user_id: UUID
    balance_cents: int  # Available balance in cents
    total_invested_cents: int  # Total amount invested (deposits)
    total_yield_cents: int  # Total yield earned
    fundo_garantidor_cents: int  # Fundo Garantidor retention
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    @classmethod
    def create(cls, user_id: UUID) -> Wallet:
        """Factory method to create a new empty Wallet."""
        now = datetime.utcnow()
        return cls(
            id=uuid4(),
            user_id=user_id,
            balance_cents=0,
            total_invested_cents=0,
            total_yield_cents=0,
            fundo_garantidor_cents=0,
            created_at=now,
            updated_at=now,
        )

    def credit(self, amount: Money) -> None:
        """Credit amount to balance (deposit or yield).

        Args:
            amount: Money to add to balance
        """
        self.balance_cents += amount.cents
        self.updated_at = datetime.utcnow()

    def credit_investment(self, amount: Money) -> None:
        """Credit an investment amount.

        Args:
            amount: Investment amount to credit
        """
        self.credit(amount)
        self.total_invested_cents += amount.cents

    def credit_yield(self, amount: Money) -> None:
        """Credit yield amount.

        Args:
            amount: Yield amount to credit
        """
        self.credit(amount)
        self.total_yield_cents += amount.cents

    def debit(self, amount: Money) -> None:
        """Debit amount from balance (withdrawal).

        Args:
            amount: Money to deduct from balance

        Raises:
            InsufficientBalanceError: If withdrawal exceeds balance
        """
        if amount.cents > self.balance_cents:
            raise InsufficientBalanceError(
                requested=str(amount),
                available=str(self.balance),
            )
        self.balance_cents -= amount.cents
        self.updated_at = datetime.utcnow()

    def add_fundo_garantidor(self, amount: Money) -> None:
        """Add to Fundo Garantidor retention.

        Args:
            amount: Fundo Garantidor amount to add
        """
        self.fundo_garantidor_cents += amount.cents
        self.updated_at = datetime.utcnow()

    @property
    def balance(self) -> Money:
        """Get current balance as Money."""
        return Money.from_cents(self.balance_cents)

    @property
    def total_invested(self) -> Money:
        """Get total invested as Money."""
        return Money.from_cents(self.total_invested_cents)

    @property
    def total_yield(self) -> Money:
        """Get total yield as Money."""
        return Money.from_cents(self.total_yield_cents)

    @property
    def fundo_garantidor(self) -> Money:
        """Get Fundo Garantidor as Money."""
        return Money.from_cents(self.fundo_garantidor_cents)

    def can_withdraw(self, amount: Money) -> bool:
        """Check if withdrawal amount is available.

        Args:
            amount: Amount to check

        Returns:
            True if balance is sufficient
        """
        return amount.cents <= self.balance_cents
