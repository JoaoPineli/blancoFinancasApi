"""Transaction repository implementation."""

from datetime import datetime, timedelta
from typing import List, Optional
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.entities.transaction import (
    InstallmentType,
    Transaction,
    TransactionStatus,
    TransactionType,
)
from app.domain.entities.transaction_item import TransactionItem
from app.infrastructure.db.models import TransactionItemModel, TransactionModel


class TransactionRepository:
    """Repository for Transaction entity persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, transaction_id: UUID) -> Optional[Transaction]:
        """Get transaction by ID (without items)."""
        result = await self._session.execute(
            select(TransactionModel).where(TransactionModel.id == transaction_id)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_by_id_with_items(self, transaction_id: UUID) -> Optional[Transaction]:
        """Get transaction by ID with items eagerly loaded."""
        result = await self._session.execute(
            select(TransactionModel)
            .options(selectinload(TransactionModel.items))
            .where(TransactionModel.id == transaction_id)
        )
        model = result.scalar_one_or_none()
        return self._to_entity_with_items(model) if model else None

    async def get_by_pix_transaction_id(
        self, pix_transaction_id: str
    ) -> Optional[Transaction]:
        """Get transaction by Pix transaction ID for reconciliation."""
        result = await self._session.execute(
            select(TransactionModel).where(
                TransactionModel.pix_transaction_id == pix_transaction_id
            )
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_by_pix_transaction_id_with_items(
        self, pix_transaction_id: str
    ) -> Optional[Transaction]:
        """Get transaction by Pix ID with items eagerly loaded."""
        result = await self._session.execute(
            select(TransactionModel)
            .options(selectinload(TransactionModel.items))
            .where(TransactionModel.pix_transaction_id == pix_transaction_id)
        )
        model = result.scalar_one_or_none()
        return self._to_entity_with_items(model) if model else None

    async def get_pending_for_subscription(
        self,
        subscription_id: UUID,
        transaction_type: TransactionType,
    ) -> List[Transaction]:
        """Get pending payment transactions involving a specific subscription.

        Used to prevent duplicate payment creation.
        """
        result = await self._session.execute(
            select(TransactionModel)
            .options(selectinload(TransactionModel.items))
            .join(TransactionItemModel)
            .where(
                TransactionItemModel.subscription_id == subscription_id,
                TransactionModel.transaction_type == transaction_type.value,
                TransactionModel.status == TransactionStatus.PENDING.value,
            )
        )
        models = result.unique().scalars().all()
        return [self._to_entity_with_items(m) for m in models]

    async def get_by_user_id(
        self,
        user_id: UUID,
        transaction_type: Optional[TransactionType] = None,
        status: Optional[TransactionStatus] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Transaction]:
        """Get transactions for a user."""
        query = select(TransactionModel).where(TransactionModel.user_id == user_id)

        if transaction_type:
            query = query.where(TransactionModel.transaction_type == transaction_type.value)
        if status:
            query = query.where(TransactionModel.status == status.value)

        query = query.order_by(TransactionModel.created_at.desc())
        query = query.limit(limit).offset(offset)

        result = await self._session.execute(query)
        models = result.scalars().all()
        return [self._to_entity(model) for model in models]

    async def get_by_user_id_with_items(
        self,
        user_id: UUID,
        transaction_type: Optional[TransactionType] = None,
        status: Optional[TransactionStatus] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Transaction]:
        """Get transactions for a user with items eagerly loaded."""
        query = (
            select(TransactionModel)
            .options(selectinload(TransactionModel.items))
            .where(TransactionModel.user_id == user_id)
        )

        if transaction_type:
            query = query.where(TransactionModel.transaction_type == transaction_type.value)
        if status:
            query = query.where(TransactionModel.status == status.value)

        query = query.order_by(TransactionModel.created_at.desc())
        query = query.limit(limit).offset(offset)

        result = await self._session.execute(query)
        models = result.unique().scalars().all()
        return [self._to_entity_with_items(m) for m in models]

    async def get_by_contract_id(
        self,
        contract_id: UUID,
        transaction_type: Optional[TransactionType] = None,
    ) -> List[Transaction]:
        """Get transactions for a contract."""
        query = select(TransactionModel).where(TransactionModel.contract_id == contract_id)

        if transaction_type:
            query = query.where(TransactionModel.transaction_type == transaction_type.value)

        query = query.order_by(TransactionModel.created_at.asc())
        result = await self._session.execute(query)
        models = result.scalars().all()
        return [self._to_entity(model) for model in models]

    async def get_pending_deposits(self) -> List[Transaction]:
        """Get all pending deposits for reconciliation."""
        result = await self._session.execute(
            select(TransactionModel)
            .where(TransactionModel.transaction_type == TransactionType.DEPOSIT.value)
            .where(TransactionModel.status == TransactionStatus.PENDING.value)
        )
        models = result.scalars().all()
        return [self._to_entity(model) for model in models]

    async def get_yield_sum_by_subscription(self, subscription_id: UUID) -> int:
        """Return total confirmed yield credited for a subscription (cents)."""
        result = await self._session.execute(
            select(func.coalesce(func.sum(TransactionModel.amount_cents), 0))
            .where(TransactionModel.subscription_id == subscription_id)
            .where(TransactionModel.transaction_type == TransactionType.YIELD.value)
            .where(TransactionModel.status == TransactionStatus.CONFIRMED.value)
        )
        return int(result.scalar())

    async def get_confirmed_yield_sum_for_user_in_range(
        self, user_id: UUID, start: datetime, end: datetime
    ) -> int:
        """Return total confirmed yield for a user within [start, end) (cents)."""
        result = await self._session.execute(
            select(func.coalesce(func.sum(TransactionModel.amount_cents), 0))
            .where(TransactionModel.user_id == user_id)
            .where(TransactionModel.transaction_type == TransactionType.YIELD.value)
            .where(TransactionModel.status == TransactionStatus.CONFIRMED.value)
            .where(TransactionModel.confirmed_at >= start)
            .where(TransactionModel.confirmed_at < end)
        )
        return int(result.scalar())

    async def expire_stale_payments(
        self,
        user_id: UUID,
        transaction_type: TransactionType,
    ) -> int:
        """Bulk-expire pending payment transactions that exceeded their expiration window.

        Args:
            user_id: Scope the expiration to this user's transactions.
            transaction_type: Which payment type to expire.

        Returns:
            Number of transactions expired.
        """
        now = datetime.utcnow()
        result = await self._session.execute(
            select(
                TransactionModel.id,
                TransactionModel.created_at,
                TransactionModel.expiration_minutes,
            ).where(
                TransactionModel.user_id == user_id,
                TransactionModel.transaction_type == transaction_type.value,
                TransactionModel.status == TransactionStatus.PENDING.value,
                TransactionModel.expiration_minutes.isnot(None),
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
            update(TransactionModel)
            .where(TransactionModel.id.in_(expired_ids))
            .values(status=TransactionStatus.EXPIRED.value, updated_at=now)
        )
        await self._session.flush()
        return len(expired_ids)

    async def expire_all_stale_payments(
        self,
        transaction_types: Optional[List[TransactionType]] = None,
    ) -> int:
        """Bulk-expire all pending payment transactions globally that exceeded their expiration window.

        Unlike expire_stale_payments (scoped to a single user), this method
        operates across all users and is intended for scheduled batch jobs.

        Args:
            transaction_types: Limit expiration to specific types. None applies to all.

        Returns:
            Number of transactions expired.
        """
        now = datetime.utcnow()
        query = select(
            TransactionModel.id,
            TransactionModel.created_at,
            TransactionModel.expiration_minutes,
        ).where(
            TransactionModel.status == TransactionStatus.PENDING.value,
            TransactionModel.expiration_minutes.isnot(None),
        )
        if transaction_types:
            query = query.where(
                TransactionModel.transaction_type.in_([t.value for t in transaction_types])
            )

        result = await self._session.execute(query)
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
            update(TransactionModel)
            .where(TransactionModel.id.in_(expired_ids))
            .values(status=TransactionStatus.EXPIRED.value, updated_at=now)
        )
        await self._session.flush()
        return len(expired_ids)

    async def save(self, transaction: Transaction) -> Transaction:
        """Save transaction (create or update)."""
        model = self._to_model(transaction)
        merged = await self._session.merge(model)
        await self._session.flush()
        return self._to_entity(merged)

    async def save_with_items(
        self, transaction: Transaction, items: List[TransactionItem]
    ) -> Transaction:
        """Save transaction and all its items atomically."""
        model = self._to_model(transaction)
        await self._session.merge(model)
        for item in items:
            item_model = TransactionItemModel(
                id=item.id,
                transaction_id=item.transaction_id,
                subscription_id=item.subscription_id,
                subscription_name=item.subscription_name,
                plan_title=item.plan_title,
                amount_cents=item.amount_cents,
                installment_number=item.installment_number,
            )
            await self._session.merge(item_model)
        await self._session.flush()
        return await self.get_by_id_with_items(transaction.id)  # type: ignore[return-value]

    async def delete(self, transaction_id: UUID) -> bool:
        """Delete transaction by ID."""
        result = await self._session.execute(
            select(TransactionModel).where(TransactionModel.id == transaction_id)
        )
        model = result.scalar_one_or_none()
        if model:
            await self._session.delete(model)
            return True
        return False

    def _to_entity(self, model: TransactionModel) -> Transaction:
        """Map ORM model to domain entity (without items)."""
        return Transaction(
            id=model.id,
            user_id=model.user_id,
            contract_id=model.contract_id,
            subscription_id=model.subscription_id,
            transaction_type=TransactionType(model.transaction_type),
            status=TransactionStatus(model.status),
            amount_cents=model.amount_cents,
            installment_number=model.installment_number,
            installment_type=InstallmentType(model.installment_type)
            if model.installment_type
            else None,
            pix_key=model.pix_key,
            pix_key_type=model.pix_key_type,
            pix_transaction_id=model.pix_transaction_id,
            bank_account=model.bank_account,
            description=model.description,
            rejection_reason=model.rejection_reason,
            created_at=model.created_at,
            updated_at=model.updated_at,
            confirmed_at=model.confirmed_at,
            pix_qr_code_data=model.pix_qr_code_data,
            pix_qr_code_base64=model.pix_qr_code_base64,
            expiration_minutes=model.expiration_minutes,
            pix_transaction_fee_cents=model.pix_transaction_fee_cents or 0,
            admin_tax_cents=model.admin_tax_cents,
            insurance_cents=model.insurance_cents,
        )

    def _to_entity_with_items(self, model: TransactionModel) -> Transaction:
        """Map ORM model to domain entity including items."""
        tx = self._to_entity(model)
        tx.items = [
            TransactionItem(
                id=i.id,
                transaction_id=i.transaction_id,
                subscription_id=i.subscription_id,
                subscription_name=i.subscription_name,
                plan_title=i.plan_title,
                amount_cents=i.amount_cents,
                installment_number=i.installment_number,
            )
            for i in model.items
        ]
        return tx

    def _to_model(self, entity: Transaction) -> TransactionModel:
        """Map domain entity to ORM model."""
        return TransactionModel(
            id=entity.id,
            user_id=entity.user_id,
            contract_id=entity.contract_id,
            subscription_id=entity.subscription_id,
            transaction_type=entity.transaction_type.value,
            status=entity.status.value,
            amount_cents=entity.amount_cents,
            installment_number=entity.installment_number,
            installment_type=entity.installment_type.value if entity.installment_type else None,
            pix_key=entity.pix_key,
            pix_key_type=entity.pix_key_type,
            pix_transaction_id=entity.pix_transaction_id,
            bank_account=entity.bank_account,
            description=entity.description,
            rejection_reason=entity.rejection_reason,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
            confirmed_at=entity.confirmed_at,
            pix_qr_code_data=entity.pix_qr_code_data,
            pix_qr_code_base64=entity.pix_qr_code_base64,
            expiration_minutes=entity.expiration_minutes,
            pix_transaction_fee_cents=entity.pix_transaction_fee_cents,
            admin_tax_cents=entity.admin_tax_cents,
            insurance_cents=entity.insurance_cents,
        )
