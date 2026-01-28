"""Plan repository implementation."""

from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.plan import Plan, PlanStatus, PlanType
from app.infrastructure.db.models import PlanModel


class PlanRepository:
    """Repository for Plan entity persistence."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with database session."""
        self._session = session

    async def get_by_id(self, plan_id: UUID) -> Optional[Plan]:
        """Get plan by ID."""
        result = await self._session.execute(
            select(PlanModel).where(PlanModel.id == plan_id)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_all(
        self,
        status: Optional[PlanStatus] = None,
        plan_type: Optional[PlanType] = None,
    ) -> List[Plan]:
        """Get all plans with optional filtering."""
        query = select(PlanModel)

        if status:
            query = query.where(PlanModel.status == status.value)
        if plan_type:
            query = query.where(PlanModel.plan_type == plan_type.value)

        result = await self._session.execute(query)
        models = result.scalars().all()
        return [self._to_entity(model) for model in models]

    async def get_active_plans(self) -> List[Plan]:
        """Get all active plans."""
        return await self.get_all(status=PlanStatus.ACTIVE)

    async def save(self, plan: Plan) -> Plan:
        """Save plan (create or update)."""
        model = self._to_model(plan)
        merged = await self._session.merge(model)
        await self._session.flush()
        return self._to_entity(merged)

    async def delete(self, plan_id: UUID) -> bool:
        """Delete plan by ID."""
        result = await self._session.execute(
            select(PlanModel).where(PlanModel.id == plan_id)
        )
        model = result.scalar_one_or_none()
        if model:
            await self._session.delete(model)
            return True
        return False

    def _to_entity(self, model: PlanModel) -> Plan:
        """Map ORM model to domain entity."""
        return Plan(
            id=model.id,
            name=model.name,
            plan_type=PlanType(model.plan_type),
            description=model.description,
            monthly_installment_cents=model.monthly_installment_cents,
            duration_months=model.duration_months,
            fundo_garantidor_percentage=model.fundo_garantidor_percentage,
            status=PlanStatus(model.status),
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    def _to_model(self, entity: Plan) -> PlanModel:
        """Map domain entity to ORM model."""
        return PlanModel(
            id=entity.id,
            name=entity.name,
            plan_type=entity.plan_type.value,
            description=entity.description,
            monthly_installment_cents=entity.monthly_installment_cents,
            duration_months=entity.duration_months,
            fundo_garantidor_percentage=entity.fundo_garantidor_percentage,
            status=entity.status.value,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )
