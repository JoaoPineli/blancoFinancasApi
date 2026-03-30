"""Principal Deposit repository implementation."""

from datetime import date
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.principal_deposit import PrincipalDeposit
from app.infrastructure.db.models import PrincipalDepositModel


class PrincipalDepositRepository:
    """Repository for PrincipalDeposit entity persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, deposit_id: UUID) -> Optional[PrincipalDeposit]:
        """Get principal deposit by ID."""
        result = await self._session.execute(
            select(PrincipalDepositModel).where(PrincipalDepositModel.id == deposit_id)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_by_item_id(
        self, transaction_item_id: UUID
    ) -> Optional[PrincipalDeposit]:
        """Get principal deposit by transaction item ID (unique)."""
        result = await self._session.execute(
            select(PrincipalDepositModel).where(
                PrincipalDepositModel.transaction_item_id == transaction_item_id
            )
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_pending_yield_processing(
        self, before_date: date
    ) -> List[PrincipalDeposit]:
        """Get all deposits that need yield processing.

        Returns deposits where:
        - last_yield_run_date is NULL (never processed), OR
        - last_yield_run_date < before_date (processed before the target date)
        """
        result = await self._session.execute(
            select(PrincipalDepositModel)
            .where(
                (PrincipalDepositModel.last_yield_run_date == None)  # noqa: E711
                | (PrincipalDepositModel.last_yield_run_date < before_date)
            )
            .order_by(PrincipalDepositModel.deposited_at.asc())
        )
        models = result.scalars().all()
        return [self._to_entity(m) for m in models]

    async def get_by_user_id(self, user_id: UUID) -> List[PrincipalDeposit]:
        """Get all principal deposits for a user."""
        result = await self._session.execute(
            select(PrincipalDepositModel)
            .where(PrincipalDepositModel.user_id == user_id)
            .order_by(PrincipalDepositModel.deposited_at.asc())
        )
        models = result.scalars().all()
        return [self._to_entity(m) for m in models]

    async def save(self, deposit: PrincipalDeposit) -> PrincipalDeposit:
        """Save principal deposit (create or update)."""
        model = self._to_model(deposit)
        merged = await self._session.merge(model)
        await self._session.flush()
        return self._to_entity(merged)

    def _to_entity(self, model: PrincipalDepositModel) -> PrincipalDeposit:
        """Map ORM model to domain entity."""
        return PrincipalDeposit(
            id=model.id,
            user_id=model.user_id,
            subscription_id=model.subscription_id,
            transaction_item_id=model.transaction_item_id,
            installment_number=model.installment_number,
            principal_cents=model.principal_cents,
            deposited_at=model.deposited_at
            if isinstance(model.deposited_at, date)
            else model.deposited_at.date(),
            last_yield_run_date=model.last_yield_run_date
            if model.last_yield_run_date is None
            or isinstance(model.last_yield_run_date, date)
            else model.last_yield_run_date.date(),
            created_at=model.created_at,
        )

    def _to_model(self, entity: PrincipalDeposit) -> PrincipalDepositModel:
        """Map domain entity to ORM model."""
        return PrincipalDepositModel(
            id=entity.id,
            user_id=entity.user_id,
            subscription_id=entity.subscription_id,
            transaction_item_id=entity.transaction_item_id,
            installment_number=entity.installment_number,
            principal_cents=entity.principal_cents,
            deposited_at=entity.deposited_at,
            last_yield_run_date=entity.last_yield_run_date,
            created_at=entity.created_at,
        )
