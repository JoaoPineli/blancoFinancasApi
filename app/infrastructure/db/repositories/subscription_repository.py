"""User Plan Subscription repository implementation."""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.subscription import SubscriptionStatus, UserPlanSubscription
from app.infrastructure.db.models import UserPlanSubscriptionModel


class SubscriptionRepository:
    """Repository for UserPlanSubscription entity persistence.

    Handles persistence and retrieval of subscription entities.
    Maps between ORM models and domain entities.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with database session."""
        self._session = session

    async def get_by_id(self, subscription_id: UUID) -> Optional[UserPlanSubscription]:
        """Get subscription by ID.

        Args:
            subscription_id: The subscription's UUID.

        Returns:
            UserPlanSubscription entity if found, None otherwise.
        """
        result = await self._session.execute(
            select(UserPlanSubscriptionModel).where(
                UserPlanSubscriptionModel.id == subscription_id
            )
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_by_user_id(self, user_id: UUID) -> List[UserPlanSubscription]:
        """Get all subscriptions for a user.

        Args:
            user_id: The user's UUID.

        Returns:
            List of UserPlanSubscription entities for the user.
        """
        result = await self._session.execute(
            select(UserPlanSubscriptionModel)
            .where(UserPlanSubscriptionModel.user_id == user_id)
            .order_by(UserPlanSubscriptionModel.created_at.desc())
        )
        models = result.scalars().all()
        return [self._to_entity(model) for model in models]

    async def get_active_by_user_id(self, user_id: UUID) -> List[UserPlanSubscription]:
        """Get all active subscriptions for a user.

        Args:
            user_id: The user's UUID.

        Returns:
            List of active UserPlanSubscription entities.
        """
        result = await self._session.execute(
            select(UserPlanSubscriptionModel)
            .where(UserPlanSubscriptionModel.user_id == user_id)
            .where(
                UserPlanSubscriptionModel.status == SubscriptionStatus.ACTIVE.value
            )
            .order_by(UserPlanSubscriptionModel.created_at.desc())
        )
        models = result.scalars().all()
        return [self._to_entity(model) for model in models]

    async def save(self, subscription: UserPlanSubscription) -> UserPlanSubscription:
        """Save subscription (create or update).

        Args:
            subscription: The UserPlanSubscription entity to persist.

        Returns:
            The persisted UserPlanSubscription entity.
        """
        model = self._to_model(subscription)
        merged = await self._session.merge(model)
        await self._session.flush()
        return self._to_entity(merged)

    def _to_entity(self, model: UserPlanSubscriptionModel) -> UserPlanSubscription:
        """Map ORM model to domain entity.

        Args:
            model: The SQLAlchemy model.

        Returns:
            The corresponding UserPlanSubscription domain entity.
        """
        return UserPlanSubscription(
            id=model.id,
            user_id=model.user_id,
            plan_id=model.plan_id,
            target_amount_cents=model.target_amount_cents,
            deposit_count=model.deposit_count,
            monthly_amount_cents=model.monthly_amount_cents,
            admin_tax_value_cents=model.admin_tax_value_cents,
            insurance_percent=model.insurance_percent,
            guarantee_fund_percent=model.guarantee_fund_percent,
            total_cost_cents=model.total_cost_cents,
            status=SubscriptionStatus(model.status),
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    def _to_model(self, entity: UserPlanSubscription) -> UserPlanSubscriptionModel:
        """Map domain entity to ORM model.

        Args:
            entity: The UserPlanSubscription domain entity.

        Returns:
            The corresponding SQLAlchemy model.
        """
        return UserPlanSubscriptionModel(
            id=entity.id,
            user_id=entity.user_id,
            plan_id=entity.plan_id,
            target_amount_cents=entity.target_amount_cents,
            deposit_count=entity.deposit_count,
            monthly_amount_cents=entity.monthly_amount_cents,
            admin_tax_value_cents=entity.admin_tax_value_cents,
            insurance_percent=entity.insurance_percent,
            guarantee_fund_percent=entity.guarantee_fund_percent,
            total_cost_cents=entity.total_cost_cents,
            status=entity.status.value,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )
