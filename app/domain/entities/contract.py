"""Contract entity - Domain model for user contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4


class ContractStatus(Enum):
    """Contract status enumeration."""

    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass
class Contract:
    """Contract entity representing a user-plan agreement.

    A contract binds a user to a specific plan and tracks:
    - Contract acceptance
    - PDF document storage reference
    - Start and end dates
    - Status transitions
    """

    id: UUID
    user_id: UUID
    plan_id: UUID
    status: ContractStatus
    pdf_storage_path: Optional[str]
    accepted_at: Optional[datetime]
    start_date: Optional[datetime]
    end_date: Optional[datetime]
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    @classmethod
    def create(
        cls,
        user_id: UUID,
        plan_id: UUID,
    ) -> Contract:
        """Factory method to create a new Contract in pending status."""
        now = datetime.utcnow()
        return cls(
            id=uuid4(),
            user_id=user_id,
            plan_id=plan_id,
            status=ContractStatus.PENDING,
            pdf_storage_path=None,
            accepted_at=None,
            start_date=None,
            end_date=None,
            created_at=now,
            updated_at=now,
        )

    def accept(self, pdf_storage_path: str, duration_months: int) -> None:
        """Accept the contract and set start/end dates.

        Args:
            pdf_storage_path: Path where the signed PDF is stored
            duration_months: Duration of the plan in months
        """
        if self.status != ContractStatus.PENDING:
            raise ValueError(f"Cannot accept contract in {self.status.value} status")

        now = datetime.utcnow()
        self.status = ContractStatus.ACTIVE
        self.pdf_storage_path = pdf_storage_path
        self.accepted_at = now
        self.start_date = now

        # Calculate end date based on duration
        year = now.year + (now.month + duration_months - 1) // 12
        month = (now.month + duration_months - 1) % 12 + 1
        day = min(now.day, 28)  # Safe day to avoid month overflow
        self.end_date = datetime(year, month, day)
        self.updated_at = now

    def complete(self) -> None:
        """Mark contract as completed."""
        if self.status != ContractStatus.ACTIVE:
            raise ValueError(f"Cannot complete contract in {self.status.value} status")

        self.status = ContractStatus.COMPLETED
        self.updated_at = datetime.utcnow()

    def cancel(self) -> None:
        """Cancel the contract."""
        if self.status == ContractStatus.COMPLETED:
            raise ValueError("Cannot cancel a completed contract")

        self.status = ContractStatus.CANCELLED
        self.updated_at = datetime.utcnow()

    def is_active(self) -> bool:
        """Check if contract is active."""
        return self.status == ContractStatus.ACTIVE

    def is_pending(self) -> bool:
        """Check if contract is pending acceptance."""
        return self.status == ContractStatus.PENDING
