"""Audit Log entity - Domain model for audit trail."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional
from uuid import UUID, uuid4


class AuditAction(Enum):
    """Audit action types."""

    # User actions
    USER_CREATED = "user_created"
    USER_UPDATED = "user_updated"
    USER_STATUS_CHANGED = "user_status_changed"
    USER_INVITED = "user_invited"
    USER_ACTIVATED = "user_activated"

    # Contract actions
    CONTRACT_CREATED = "contract_created"
    CONTRACT_ACCEPTED = "contract_accepted"
    CONTRACT_COMPLETED = "contract_completed"
    CONTRACT_CANCELLED = "contract_cancelled"

    # Transaction actions
    DEPOSIT_CREATED = "deposit_created"
    DEPOSIT_CONFIRMED = "deposit_confirmed"
    WITHDRAWAL_REQUESTED = "withdrawal_requested"
    WITHDRAWAL_APPROVED = "withdrawal_approved"
    WITHDRAWAL_REJECTED = "withdrawal_rejected"
    YIELD_CREDITED = "yield_credited"

    # Subscription actions
    SUBSCRIPTION_CREATED = "subscription_created"
    SUBSCRIPTION_CANCELLED = "subscription_cancelled"
    SUBSCRIPTION_COMPLETED = "subscription_completed"

    # Installment payment actions
    INSTALLMENT_PAYMENT_CREATED = "installment_payment_created"
    INSTALLMENT_PAYMENT_CONFIRMED = "installment_payment_confirmed"

    # Plan withdrawal actions
    PLAN_WITHDRAWAL_REQUESTED = "plan_withdrawal_requested"

    # Admin actions
    PLAN_CREATED = "plan_created"
    PLAN_UPDATED = "plan_updated"
    PLAN_DELETED = "plan_deleted"
    ADMIN_LOGIN = "admin_login"


@dataclass
class AuditLog:
    """Audit log entity for tracking critical actions.

    Immutable record of who did what and when.
    """

    id: UUID
    action: AuditAction
    actor_id: UUID  # User who performed the action
    target_id: Optional[UUID]  # Entity affected by the action
    target_type: Optional[str]  # Type of entity (user, contract, transaction)
    details: Dict[str, Any]  # Additional context
    ip_address: Optional[str]
    created_at: datetime = field(default_factory=datetime.utcnow)

    @classmethod
    def create(
        cls,
        action: AuditAction,
        actor_id: UUID,
        target_id: Optional[UUID] = None,
        target_type: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
    ) -> AuditLog:
        """Factory method to create an audit log entry."""
        return cls(
            id=uuid4(),
            action=action,
            actor_id=actor_id,
            target_id=target_id,
            target_type=target_type,
            details=details or {},
            ip_address=ip_address,
            created_at=datetime.utcnow(),
        )
