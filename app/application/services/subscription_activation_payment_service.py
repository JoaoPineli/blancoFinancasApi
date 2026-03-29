"""Subscription Activation Payment service.

Handles the one-time Pix payment that activates a subscription.
Covers: admin tax + insurance (one-time). Monthly installments do NOT repeat these.
"""

from datetime import date, datetime
from typing import Optional
from uuid import UUID, uuid4

import zoneinfo

from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos.subscription_activation_payment import (
    ActivationPaymentDTO,
    CreateActivationPaymentInput,
)
from app.domain.constants import calculate_pix_fee
from app.domain.entities.audit_log import AuditAction, AuditLog
from app.domain.entities.subscription import SubscriptionStatus
from app.domain.entities.subscription_activation_payment import (
    ActivationPaymentStatus,
    SubscriptionActivationPayment,
)
from app.domain.exceptions import (
    InvalidSubscriptionError,
    PaymentNotFoundError,
    SubscriptionNotFoundError,
)
from app.infrastructure.db.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.db.repositories.subscription_activation_payment_repository import (
    SubscriptionActivationPaymentRepository,
)
from app.infrastructure.db.repositories.subscription_repository import (
    SubscriptionRepository,
)
from app.infrastructure.payment.pix_gateway import PixGatewayAdapter

_DEFAULT_TZ = zoneinfo.ZoneInfo("America/Sao_Paulo")


class SubscriptionActivationPaymentService:
    """Service for subscription activation payment operations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._payment_repo = SubscriptionActivationPaymentRepository(session)
        self._subscription_repo = SubscriptionRepository(session)
        self._audit_repo = AuditLogRepository(session)
        self._pix_gateway = PixGatewayAdapter()

    async def create_or_get_pending(
        self, input_data: CreateActivationPaymentInput
    ) -> ActivationPaymentDTO:
        """Create a new activation payment or return an existing pending one.

        Idempotent: if a pending payment already exists for this subscription,
        returns it without creating a new one.

        Args:
            input_data: user_id and subscription_id.

        Returns:
            ActivationPaymentDTO with Pix QR code data.

        Raises:
            SubscriptionNotFoundError: If subscription not found or not owned.
            InvalidSubscriptionError: If subscription is not INACTIVE.
        """
        # Expire stale payments for user
        expired = await self._payment_repo.expire_stale_payments(input_data.user_id)
        if expired:
            await self._session.commit()

        # Get and validate subscription
        sub = await self._subscription_repo.get_by_id(input_data.subscription_id)
        if not sub or sub.user_id != input_data.user_id:
            raise SubscriptionNotFoundError(str(input_data.subscription_id))

        if sub.status != SubscriptionStatus.INACTIVE:
            raise InvalidSubscriptionError(
                f"Subscription is not in INACTIVE status (current: {sub.status.value})"
            )

        # Check for existing pending payment (idempotency)
        existing = await self._payment_repo.get_pending_for_subscription(
            input_data.subscription_id
        )
        if existing:
            return self._to_dto(existing)

        # Calculate amounts
        admin_tax_cents = sub.admin_tax_value_cents
        insurance_cents = int(
            (Decimal(sub.monthly_amount_cents) * sub.insurance_percent / Decimal(100))
            .quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
        base_cents = admin_tax_cents + insurance_cents
        pix_fee_cents = calculate_pix_fee(base_cents)
        total_cents = base_cents + pix_fee_cents

        # Generate Pix
        temp_id = uuid4()
        pix_payload = self._pix_gateway.create_payment(
            internal_transaction_id=temp_id,
            amount_cents=total_cents,
            description="Blanco Financas - Ativacao de plano",
        )

        # Create domain entity
        payment = SubscriptionActivationPayment.create(
            user_id=input_data.user_id,
            subscription_id=input_data.subscription_id,
            admin_tax_cents=admin_tax_cents,
            insurance_cents=insurance_cents,
            pix_transaction_fee_cents=pix_fee_cents,
            pix_qr_code_data=pix_payload.qr_code_data,
            expiration_minutes=pix_payload.expiration_minutes,
        )
        payment.pix_transaction_id = pix_payload.transaction_id

        # Persist
        saved = await self._payment_repo.save(payment)

        # Audit
        audit = AuditLog.create(
            action=AuditAction.SUBSCRIPTION_ACTIVATION_PAYMENT_CREATED,
            actor_id=input_data.user_id,
            target_id=saved.id,
            target_type="subscription_activation_payment",
            details={
                "subscription_id": str(input_data.subscription_id),
                "admin_tax_cents": admin_tax_cents,
                "insurance_cents": insurance_cents,
                "pix_fee_cents": pix_fee_cents,
                "total_amount_cents": total_cents,
            },
        )
        await self._audit_repo.save(audit)
        await self._session.commit()

        return self._to_dto(saved)

    async def get_payment(
        self, payment_id: UUID, user_id: UUID
    ) -> ActivationPaymentDTO:
        """Get an activation payment by ID with ownership check.

        Args:
            payment_id: Payment UUID.
            user_id: Authenticated user UUID for ownership validation.

        Returns:
            ActivationPaymentDTO.

        Raises:
            PaymentNotFoundError: If not found or not owned by user.
        """
        payment = await self._payment_repo.get_by_id(payment_id)
        if not payment or payment.user_id != user_id:
            raise PaymentNotFoundError(str(payment_id))

        # Lazy-expire if stale
        if payment.is_stale():
            payment.expire()
            await self._payment_repo.save(payment)
            await self._session.commit()

        return self._to_dto(payment)

    async def get_payment_for_subscription(
        self, subscription_id: UUID, user_id: UUID
    ) -> ActivationPaymentDTO:
        """Get the pending or latest activation payment for a subscription.

        Args:
            subscription_id: Subscription UUID.
            user_id: Authenticated user UUID for ownership validation.

        Returns:
            ActivationPaymentDTO.

        Raises:
            SubscriptionNotFoundError: If subscription not found or not owned.
            PaymentNotFoundError: If no activation payment exists.
        """
        sub = await self._subscription_repo.get_by_id(subscription_id)
        if not sub or sub.user_id != user_id:
            raise SubscriptionNotFoundError(str(subscription_id))

        # Lazy expire stale payments
        expired = await self._payment_repo.expire_stale_payments(user_id)
        if expired:
            await self._session.commit()

        payment = await self._payment_repo.get_pending_for_subscription(subscription_id)
        if not payment:
            raise PaymentNotFoundError(str(subscription_id))

        return self._to_dto(payment)

    async def confirm_payment(
        self, payment_id: UUID, pix_transaction_id: str
    ) -> ActivationPaymentDTO:
        """Confirm an activation payment and activate the subscription.

        Idempotent: if already confirmed, returns current state.

        Args:
            payment_id: Payment UUID.
            pix_transaction_id: Pix transaction ID from gateway.

        Returns:
            Updated ActivationPaymentDTO.

        Raises:
            PaymentNotFoundError: If payment not found.
        """
        payment = await self._payment_repo.get_by_id(payment_id)
        if not payment:
            raise PaymentNotFoundError(str(payment_id))

        # Idempotent: already confirmed
        changed = payment.confirm(pix_transaction_id)
        if not changed:
            return self._to_dto(payment)

        today = self._today_local()

        # Activate the subscription
        sub = await self._subscription_repo.get_by_id(payment.subscription_id)
        if sub and sub.status == SubscriptionStatus.INACTIVE:
            sub.activate(sub.deposit_day_of_month, today)
            await self._subscription_repo.save(sub)

        # Save payment
        saved = await self._payment_repo.save(payment)

        # Audit: payment confirmed
        audit_payment = AuditLog.create(
            action=AuditAction.SUBSCRIPTION_ACTIVATION_PAYMENT_CONFIRMED,
            actor_id=payment.user_id,
            target_id=saved.id,
            target_type="subscription_activation_payment",
            details={
                "pix_transaction_id": pix_transaction_id,
                "total_amount_cents": payment.total_amount_cents,
                "subscription_id": str(payment.subscription_id),
            },
        )
        await self._audit_repo.save(audit_payment)

        # Audit: subscription activated
        if sub:
            audit_sub = AuditLog.create(
                action=AuditAction.SUBSCRIPTION_ACTIVATED,
                actor_id=payment.user_id,
                target_id=sub.id,
                target_type="subscription",
                details={
                    "activation_payment_id": str(saved.id),
                    "next_due_date": sub.next_due_date.isoformat() if sub.next_due_date else None,
                },
            )
            await self._audit_repo.save(audit_sub)

        await self._session.commit()

        return self._to_dto(saved)

    def _to_dto(self, payment: SubscriptionActivationPayment) -> ActivationPaymentDTO:
        """Map entity to DTO."""
        return ActivationPaymentDTO(
            id=payment.id,
            user_id=payment.user_id,
            subscription_id=payment.subscription_id,
            status=payment.status.value,
            admin_tax_cents=payment.admin_tax_cents,
            insurance_cents=payment.insurance_cents,
            pix_transaction_fee_cents=payment.pix_transaction_fee_cents,
            total_amount_cents=payment.total_amount_cents,
            pix_qr_code_data=payment.pix_qr_code_data,
            pix_transaction_id=payment.pix_transaction_id,
            expiration_minutes=payment.expiration_minutes,
            created_at=payment.created_at,
            updated_at=payment.updated_at,
            confirmed_at=payment.confirmed_at,
        )

    @staticmethod
    def _today_local() -> date:
        """Return current calendar date in the default timezone."""
        return datetime.now(_DEFAULT_TZ).date()
