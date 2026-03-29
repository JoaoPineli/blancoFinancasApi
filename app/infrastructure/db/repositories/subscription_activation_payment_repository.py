"""Subscription Activation Payment repository implementation."""

from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.subscription_activation_payment import (
    ActivationPaymentStatus,
    SubscriptionActivationPayment,
)
from app.infrastructure.db.models import SubscriptionActivationPaymentModel


class SubscriptionActivationPaymentRepository:
    """Repository for SubscriptionActivationPayment entity persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(
        self, payment_id: UUID
    ) -> Optional[SubscriptionActivationPayment]:
        """Get activation payment by ID."""
        result = await self._session.execute(
            select(SubscriptionActivationPaymentModel).where(
                SubscriptionActivationPaymentModel.id == payment_id
            )
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_by_pix_transaction_id(
        self, pix_transaction_id: str
    ) -> Optional[SubscriptionActivationPayment]:
        """Get activation payment by Pix transaction ID for reconciliation."""
        result = await self._session.execute(
            select(SubscriptionActivationPaymentModel).where(
                SubscriptionActivationPaymentModel.pix_transaction_id == pix_transaction_id
            )
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_pending_for_subscription(
        self, subscription_id: UUID
    ) -> Optional[SubscriptionActivationPayment]:
        """Get the existing pending activation payment for a subscription.

        Returns None if there is no pending payment.
        """
        result = await self._session.execute(
            select(SubscriptionActivationPaymentModel)
            .where(
                SubscriptionActivationPaymentModel.subscription_id == subscription_id,
                SubscriptionActivationPaymentModel.status == ActivationPaymentStatus.PENDING.value,
            )
            .order_by(SubscriptionActivationPaymentModel.created_at.desc())
            .limit(1)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def expire_stale_payments(self, user_id: UUID) -> int:
        """Bulk-expire pending activation payments that have exceeded their expiration window.

        Args:
            user_id: Scope the expiration to this user's payments.

        Returns:
            Number of payments expired.
        """
        now = datetime.utcnow()
        result = await self._session.execute(
            select(
                SubscriptionActivationPaymentModel.id,
                SubscriptionActivationPaymentModel.created_at,
                SubscriptionActivationPaymentModel.expiration_minutes,
            ).where(
                SubscriptionActivationPaymentModel.user_id == user_id,
                SubscriptionActivationPaymentModel.status == ActivationPaymentStatus.PENDING.value,
            )
        )
        rows = result.all()
        expired_ids = []
        for row in rows:
            created = row.created_at
            if created.tzinfo is not None:
                created = created.replace(tzinfo=None)
            if now >= created + timedelta(minutes=row.expiration_minutes):
                expired_ids.append(row.id)

        if not expired_ids:
            return 0

        await self._session.execute(
            update(SubscriptionActivationPaymentModel)
            .where(SubscriptionActivationPaymentModel.id.in_(expired_ids))
            .values(
                status=ActivationPaymentStatus.EXPIRED.value,
                updated_at=now,
            )
        )
        await self._session.flush()
        return len(expired_ids)

    async def save(
        self, payment: SubscriptionActivationPayment
    ) -> SubscriptionActivationPayment:
        """Save activation payment (create or update)."""
        model = self._to_model(payment)
        merged = await self._session.merge(model)
        await self._session.flush()
        return self._to_entity(merged)

    def _to_entity(
        self, model: SubscriptionActivationPaymentModel
    ) -> SubscriptionActivationPayment:
        """Map ORM model to domain entity."""
        return SubscriptionActivationPayment(
            id=model.id,
            user_id=model.user_id,
            subscription_id=model.subscription_id,
            status=ActivationPaymentStatus(model.status),
            admin_tax_cents=model.admin_tax_cents,
            insurance_cents=model.insurance_cents,
            pix_transaction_fee_cents=model.pix_transaction_fee_cents,
            total_amount_cents=model.total_amount_cents,
            pix_qr_code_data=model.pix_qr_code_data,
            pix_transaction_id=model.pix_transaction_id,
            expiration_minutes=model.expiration_minutes,
            created_at=model.created_at,
            updated_at=model.updated_at,
            confirmed_at=model.confirmed_at,
        )

    def _to_model(
        self, entity: SubscriptionActivationPayment
    ) -> SubscriptionActivationPaymentModel:
        """Map domain entity to ORM model."""
        return SubscriptionActivationPaymentModel(
            id=entity.id,
            user_id=entity.user_id,
            subscription_id=entity.subscription_id,
            status=entity.status.value,
            admin_tax_cents=entity.admin_tax_cents,
            insurance_cents=entity.insurance_cents,
            pix_transaction_fee_cents=entity.pix_transaction_fee_cents,
            total_amount_cents=entity.total_amount_cents,
            pix_qr_code_data=entity.pix_qr_code_data,
            pix_transaction_id=entity.pix_transaction_id,
            expiration_minutes=entity.expiration_minutes,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
            confirmed_at=entity.confirmed_at,
        )
