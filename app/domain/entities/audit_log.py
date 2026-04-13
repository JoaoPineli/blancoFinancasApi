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
    USER_REGISTERED = "user_registered"
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

    # Yield batch actions
    YIELD_BATCH_PROCESSED = "yield_batch_processed"

    # Subscription activation payment actions
    SUBSCRIPTION_ACTIVATION_PAYMENT_CREATED = "subscription_activation_payment_created"
    SUBSCRIPTION_ACTIVATION_PAYMENT_CONFIRMED = "subscription_activation_payment_confirmed"
    SUBSCRIPTION_ACTIVATED = "subscription_activated"

    # Admin actions
    PLAN_CREATED = "plan_created"
    PLAN_UPDATED = "plan_updated"
    PLAN_DELETED = "plan_deleted"
    ADMIN_LOGIN = "admin_login"

    # Webhook events
    WEBHOOK_RECEIVED = "webhook_received"
    WEBHOOK_SIGNATURE_VALID = "webhook_signature_valid"
    WEBHOOK_SIGNATURE_INVALID = "webhook_signature_invalid"
    WEBHOOK_AMOUNT_MISMATCH = "webhook_amount_mismatch"
    WEBHOOK_PAYMENT_CONFIRMED = "webhook_payment_confirmed"
    WEBHOOK_PAYMENT_FAILED = "webhook_payment_failed"
    WEBHOOK_PAYMENT_EXPIRED = "webhook_payment_expired"
    WEBHOOK_UNKNOWN_TRANSACTION = "webhook_unknown_transaction"


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
