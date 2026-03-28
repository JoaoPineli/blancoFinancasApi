"""Notification entity - Domain model for admin notifications."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional
from uuid import UUID, uuid4


class NotificationType(Enum):
    """Notification type enumeration."""

    WITHDRAWAL_REQUESTED = "withdrawal_requested"


@dataclass
class Notification:
    """Notification entity for admin alerts.

    Persisted to the database. Currently used for withdrawal requests.
    All notifications are global (admin-facing), not per-user.
    """

    id: UUID
    notification_type: NotificationType
    title: str
    message: str
    is_read: bool
    target_id: Optional[UUID]
    target_type: Optional[str]
    data: Dict[str, Any]
    created_at: datetime
    read_at: Optional[datetime] = None

    @classmethod
    def create_withdrawal_requested(
        cls,
        target_id: UUID,
        client_name: str,
        plan_title: str,
        amount_cents: int,
    ) -> Notification:
        """Factory method for withdrawal request notifications."""
        amount_brl = amount_cents / 100
        return cls(
            id=uuid4(),
            notification_type=NotificationType.WITHDRAWAL_REQUESTED,
            title="Nova solicitação de retirada",
            message=(
                f"{client_name} solicitou retirada de "
                f"R$ {amount_brl:,.2f} do plano {plan_title}"
            ),
            is_read=False,
            target_id=target_id,
            target_type="transaction",
            data={
                "client_name": client_name,
                "plan_title": plan_title,
                "amount_cents": amount_cents,
            },
            created_at=datetime.utcnow(),
        )
