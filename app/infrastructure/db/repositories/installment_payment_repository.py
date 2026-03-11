"""Installment Payment repository implementation."""

from datetime import datetime, timedelta
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.entities.installment_payment import (
    InstallmentPayment,
    InstallmentPaymentItem,
    PaymentStatus,
)
from app.infrastructure.db.models import (
    InstallmentPaymentItemModel,
    InstallmentPaymentModel,
)


class InstallmentPaymentRepository:
    """Repository for InstallmentPayment entity persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, payment_id: UUID) -> Optional[InstallmentPayment]:
        """Get payment by ID with items eagerly loaded."""
        result = await self._session.execute(
            select(InstallmentPaymentModel)
            .options(selectinload(InstallmentPaymentModel.items))
            .where(InstallmentPaymentModel.id == payment_id)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_by_pix_transaction_id(
        self, pix_transaction_id: str
    ) -> Optional[InstallmentPayment]:
        """Get payment by Pix transaction ID for reconciliation."""
        result = await self._session.execute(
            select(InstallmentPaymentModel)
            .options(selectinload(InstallmentPaymentModel.items))
            .where(
                InstallmentPaymentModel.pix_transaction_id == pix_transaction_id
            )
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_pending_for_subscription(
        self, subscription_id: UUID
    ) -> List[InstallmentPayment]:
        """Check for pending payments involving a specific subscription.

        Used to prevent duplicate payment creation.
        """
        result = await self._session.execute(
            select(InstallmentPaymentModel)
            .options(selectinload(InstallmentPaymentModel.items))
            .join(InstallmentPaymentItemModel)
            .where(
                InstallmentPaymentItemModel.subscription_id == subscription_id,
                InstallmentPaymentModel.status == PaymentStatus.PENDING.value,
            )
        )
        models = result.unique().scalars().all()
        return [self._to_entity(m) for m in models]

    async def get_by_user_id(
        self,
        user_id: UUID,
        status: Optional[PaymentStatus] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[InstallmentPayment]:
        """Get payments for a user, ordered by creation date descending."""
        query = (
            select(InstallmentPaymentModel)
            .options(selectinload(InstallmentPaymentModel.items))
            .where(InstallmentPaymentModel.user_id == user_id)
        )
        if status:
            query = query.where(
                InstallmentPaymentModel.status == status.value
            )
        query = (
            query.order_by(InstallmentPaymentModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(query)
        models = result.unique().scalars().all()
        return [self._to_entity(m) for m in models]

    async def expire_stale_payments(self, user_id: UUID) -> int:
        """Bulk-expire pending payments that have exceeded their expiration window.

        Uses a single UPDATE statement for efficiency. Only targets payments
        belonging to ``user_id`` to keep the scope narrow (lazy per-user).

        Args:
            user_id: Scope the expiration to this user's payments.

        Returns:
            Number of payments expired.
        """
        now = datetime.utcnow()
        # Subquery approach: status=pending AND created_at + expiration_minutes < now
        # SQLite and PostgreSQL both support datetime arithmetic differently.
        # We materialise the cutoff per-row using interval math workaround.
        # Safe approach: fetch IDs, then bulk update.
        result = await self._session.execute(
            select(
                InstallmentPaymentModel.id,
                InstallmentPaymentModel.created_at,
                InstallmentPaymentModel.expiration_minutes,
            ).where(
                InstallmentPaymentModel.user_id == user_id,
                InstallmentPaymentModel.status == PaymentStatus.PENDING.value,
            )
        )
        rows = result.all()
        expired_ids = []
        for row in rows:
            created = row.created_at
            # Strip tz info for comparison — DB stores naive UTC
            if created.tzinfo is not None:
                created = created.replace(tzinfo=None)
            if now >= created + timedelta(minutes=row.expiration_minutes):
                expired_ids.append(row.id)

        if not expired_ids:
            return 0

        await self._session.execute(
            update(InstallmentPaymentModel)
            .where(InstallmentPaymentModel.id.in_(expired_ids))
            .values(
                status=PaymentStatus.EXPIRED.value,
                updated_at=now,
            )
        )
        await self._session.flush()
        return len(expired_ids)

    async def save(self, payment: InstallmentPayment) -> InstallmentPayment:
        """Save payment with all items (create or update)."""
        model = self._to_model(payment)
        merged = await self._session.merge(model)
        # Merge items
        for item in payment.items:
            item_model = self._item_to_model(item)
            await self._session.merge(item_model)
        await self._session.flush()
        # Re-fetch with items
        return await self.get_by_id(merged.id)  # type: ignore

    def _to_entity(self, model: InstallmentPaymentModel) -> InstallmentPayment:
        """Map ORM model to domain entity."""
        items = [
            InstallmentPaymentItem(
                id=item.id,
                payment_id=item.payment_id,
                subscription_id=item.subscription_id,
                subscription_name=item.subscription_name,
                plan_title=item.plan_title,
                amount_cents=item.amount_cents,
                installment_number=item.installment_number,
            )
            for item in model.items
        ]
        return InstallmentPayment(
            id=model.id,
            user_id=model.user_id,
            status=PaymentStatus(model.status),
            total_amount_cents=model.total_amount_cents,
            pix_qr_code_data=model.pix_qr_code_data,
            pix_transaction_id=model.pix_transaction_id,
            expiration_minutes=model.expiration_minutes,
            items=items,
            created_at=model.created_at,
            updated_at=model.updated_at,
            confirmed_at=model.confirmed_at,
        )

    def _to_model(self, entity: InstallmentPayment) -> InstallmentPaymentModel:
        """Map domain entity to ORM model (without items)."""
        return InstallmentPaymentModel(
            id=entity.id,
            user_id=entity.user_id,
            status=entity.status.value,
            total_amount_cents=entity.total_amount_cents,
            pix_qr_code_data=entity.pix_qr_code_data,
            pix_transaction_id=entity.pix_transaction_id,
            expiration_minutes=entity.expiration_minutes,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
            confirmed_at=entity.confirmed_at,
        )

    def _item_to_model(
        self, item: InstallmentPaymentItem
    ) -> InstallmentPaymentItemModel:
        """Map item entity to ORM model."""
        return InstallmentPaymentItemModel(
            id=item.id,
            payment_id=item.payment_id,
            subscription_id=item.subscription_id,
            subscription_name=item.subscription_name,
            plan_title=item.plan_title,
            amount_cents=item.amount_cents,
            installment_number=item.installment_number,
        )
