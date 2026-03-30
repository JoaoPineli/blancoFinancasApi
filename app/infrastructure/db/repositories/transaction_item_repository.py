"""TransactionItem repository implementation."""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.transaction_item import TransactionItem
from app.infrastructure.db.models import TransactionItemModel


class TransactionItemRepository:
    """Repository for TransactionItem entity persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, item_id: UUID) -> Optional[TransactionItem]:
        result = await self._session.execute(
            select(TransactionItemModel).where(TransactionItemModel.id == item_id)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_by_transaction_id(self, transaction_id: UUID) -> List[TransactionItem]:
        result = await self._session.execute(
            select(TransactionItemModel).where(
                TransactionItemModel.transaction_id == transaction_id
            )
        )
        models = result.scalars().all()
        return [self._to_entity(m) for m in models]

    async def save(self, item: TransactionItem) -> TransactionItem:
        model = self._to_model(item)
        merged = await self._session.merge(model)
        await self._session.flush()
        return self._to_entity(merged)

    def _to_entity(self, model: TransactionItemModel) -> TransactionItem:
        return TransactionItem(
            id=model.id,
            transaction_id=model.transaction_id,
            subscription_id=model.subscription_id,
            subscription_name=model.subscription_name,
            plan_title=model.plan_title,
            amount_cents=model.amount_cents,
            installment_number=model.installment_number,
        )

    def _to_model(self, entity: TransactionItem) -> TransactionItemModel:
        return TransactionItemModel(
            id=entity.id,
            transaction_id=entity.transaction_id,
            subscription_id=entity.subscription_id,
            subscription_name=entity.subscription_name,
            plan_title=entity.plan_title,
            amount_cents=entity.amount_cents,
            installment_number=entity.installment_number,
        )
