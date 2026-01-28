"""Contract repository implementation."""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.contract import Contract, ContractStatus
from app.infrastructure.db.models import ContractModel


class ContractRepository:
    """Repository for Contract entity persistence."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with database session."""
        self._session = session

    async def get_by_id(self, contract_id: UUID) -> Optional[Contract]:
        """Get contract by ID."""
        result = await self._session.execute(
            select(ContractModel).where(ContractModel.id == contract_id)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_by_user_id(
        self,
        user_id: UUID,
        status: Optional[ContractStatus] = None,
    ) -> List[Contract]:
        """Get contracts for a user."""
        query = select(ContractModel).where(ContractModel.user_id == user_id)

        if status:
            query = query.where(ContractModel.status == status.value)

        result = await self._session.execute(query)
        models = result.scalars().all()
        return [self._to_entity(model) for model in models]

    async def get_active_contract(self, user_id: UUID) -> Optional[Contract]:
        """Get active contract for a user."""
        result = await self._session.execute(
            select(ContractModel)
            .where(ContractModel.user_id == user_id)
            .where(ContractModel.status == ContractStatus.ACTIVE.value)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def save(self, contract: Contract) -> Contract:
        """Save contract (create or update)."""
        model = self._to_model(contract)
        merged = await self._session.merge(model)
        await self._session.flush()
        return self._to_entity(merged)

    async def delete(self, contract_id: UUID) -> bool:
        """Delete contract by ID."""
        result = await self._session.execute(
            select(ContractModel).where(ContractModel.id == contract_id)
        )
        model = result.scalar_one_or_none()
        if model:
            await self._session.delete(model)
            return True
        return False

    def _to_entity(self, model: ContractModel) -> Contract:
        """Map ORM model to domain entity."""
        return Contract(
            id=model.id,
            user_id=model.user_id,
            plan_id=model.plan_id,
            status=ContractStatus(model.status),
            pdf_storage_path=model.pdf_storage_path,
            accepted_at=model.accepted_at,
            start_date=model.start_date,
            end_date=model.end_date,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    def _to_model(self, entity: Contract) -> ContractModel:
        """Map domain entity to ORM model."""
        return ContractModel(
            id=entity.id,
            user_id=entity.user_id,
            plan_id=entity.plan_id,
            status=entity.status.value,
            pdf_storage_path=entity.pdf_storage_path,
            accepted_at=entity.accepted_at,
            start_date=entity.start_date,
            end_date=entity.end_date,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )
