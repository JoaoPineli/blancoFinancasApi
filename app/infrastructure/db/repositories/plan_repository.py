"""Plan repository implementation."""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.plan import Plan
from app.infrastructure.db.models import PlanModel


class PlanRepository:
    """Repository for Plan entity persistence.

    Handles persistence and retrieval of Plan entities.
    Maps between ORM models and domain entities.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with database session."""
        self._session = session

    async def get_by_id(self, plan_id: UUID, include_deleted: bool = False) -> Optional[Plan]:
        """Get plan by ID.

        Args:
            plan_id: The plan's UUID.
            include_deleted: If True, return the plan even if soft deleted.

        Returns:
            Plan entity if found, None otherwise.
        """
        query = select(PlanModel).where(PlanModel.id == plan_id)
        if not include_deleted:
            query = query.where(PlanModel.deleted_at.is_(None))
        result = await self._session.execute(query)
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_all(
        self,
        active: Optional[bool] = None,
        title_search: Optional[str] = None,
        include_deleted: bool = False,
    ) -> List[Plan]:
        """Get all plans with optional filtering.

        Args:
            active: Filter by plan active flag.
            title_search: Filter by title (case-insensitive partial match).
            include_deleted: If True, include soft deleted plans.

        Returns:
            List of Plan entities matching the filters.
        """
        query = select(PlanModel)

        # Exclude deleted plans by default
        if not include_deleted:
            query = query.where(PlanModel.deleted_at.is_(None))

        if active is not None:
            query = query.where(PlanModel.active.is_(active))
        if title_search:
            query = query.where(PlanModel.title.ilike(f"%{title_search}%"))

        query = query.order_by(PlanModel.created_at.desc())

        result = await self._session.execute(query)
        models = result.scalars().all()
        return [self._to_entity(model) for model in models]

    async def get_active_plans(self) -> List[Plan]:
        """Get all active plans.

        Returns:
            List of active Plan entities.
        """
        return await self.get_all(active=True)

    async def save(self, plan: Plan) -> Plan:
        """Save plan (create or update).

        Args:
            plan: The Plan entity to persist.

        Returns:
            The persisted Plan entity.
        """
        model = self._to_model(plan)
        merged = await self._session.merge(model)
        await self._session.flush()
        return self._to_entity(merged)

    def _to_entity(self, model: PlanModel) -> Plan:
        """Map ORM model to domain entity.

        Args:
            model: The SQLAlchemy model.

        Returns:
            The corresponding Plan domain entity.
        """
        return Plan(
            id=model.id,
            title=model.title,
            description=model.description,
            min_value_cents=model.min_value_cents,
            max_value_cents=model.max_value_cents,
            min_duration_months=model.min_duration_months,
            max_duration_months=model.max_duration_months,
            admin_tax_value_cents=model.admin_tax_value_cents,
            insurance_percent=model.insurance_percent,
            guarantee_fund_percent_1=model.guarantee_fund_percent_1,
            guarantee_fund_percent_2=model.guarantee_fund_percent_2,
            guarantee_fund_threshold_cents=model.guarantee_fund_threshold_cents,
            active=model.active,
            created_at=model.created_at,
            updated_at=model.updated_at,
            deleted_at=model.deleted_at,
        )

    def _to_model(self, entity: Plan) -> PlanModel:
        """Map domain entity to ORM model.

        Args:
            entity: The Plan domain entity.

        Returns:
            The corresponding SQLAlchemy model.
        """
        return PlanModel(
            id=entity.id,
            title=entity.title,
            description=entity.description,
            min_value_cents=entity.min_value_cents,
            max_value_cents=entity.max_value_cents,
            min_duration_months=entity.min_duration_months,
            max_duration_months=entity.max_duration_months,
            admin_tax_value_cents=entity.admin_tax_value_cents,
            insurance_percent=entity.insurance_percent,
            guarantee_fund_percent_1=entity.guarantee_fund_percent_1,
            guarantee_fund_percent_2=entity.guarantee_fund_percent_2,
            guarantee_fund_threshold_cents=entity.guarantee_fund_threshold_cents,
            active=entity.active,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
            deleted_at=entity.deleted_at,
        )
