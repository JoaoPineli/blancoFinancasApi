"""Transaction repository implementation."""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.transaction import (
    InstallmentType,
    Transaction,
    TransactionStatus,
    TransactionType,
)
from app.infrastructure.db.models import TransactionModel


class TransactionRepository:
    """Repository for Transaction entity persistence."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with database session."""
        self._session = session

    async def get_by_id(self, transaction_id: UUID) -> Optional[Transaction]:
        """Get transaction by ID."""
        result = await self._session.execute(
            select(TransactionModel).where(TransactionModel.id == transaction_id)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

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

    async def save(self, transaction: Transaction) -> Transaction:
        """Save transaction (create or update)."""
        model = self._to_model(transaction)
        merged = await self._session.merge(model)
        await self._session.flush()
        return self._to_entity(merged)

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
        """Map ORM model to domain entity."""
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
            pix_transaction_id=model.pix_transaction_id,
            bank_account=model.bank_account,
            description=model.description,
            created_at=model.created_at,
            updated_at=model.updated_at,
            confirmed_at=model.confirmed_at,
        )

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
            pix_transaction_id=entity.pix_transaction_id,
            bank_account=entity.bank_account,
            description=entity.description,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
            confirmed_at=entity.confirmed_at,
        )
