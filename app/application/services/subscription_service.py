"""Subscription service for managing user plan subscriptions."""

from typing import List
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos.subscription import (
    CalculateCostInput,
    CostResultDTO,
    CreateSubscriptionInput,
    RecommendationResultDTO,
    RecommendSubscriptionInput,
    SubscriptionResult,
)
from app.domain.entities.audit_log import AuditAction, AuditLog
from app.domain.entities.subscription import UserPlanSubscription
from app.domain.exceptions import (
    InvalidSubscriptionError,
    NoViablePlanError,
    PlanNotFoundError,
    SubscriptionNotFoundError,
)
from app.domain.services.plan_recommendation_service import (
    PlanRecommendationService,
    RecommendationPreference,
)
from app.infrastructure.db.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.db.repositories.plan_repository import PlanRepository
from app.infrastructure.db.repositories.subscription_repository import (
    SubscriptionRepository,
)


class SubscriptionService:
    """Service for managing user plan subscriptions.

    Orchestrates:
    - Listing user subscriptions
    - Plan recommendation
    - Cost calculation
    - Subscription creation

    All financial calculations are delegated to domain services.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize service with database session."""
        self._session = session
        self._subscription_repo = SubscriptionRepository(session)
        self._plan_repo = PlanRepository(session)
        self._audit_repo = AuditLogRepository(session)
        self._recommendation_service = PlanRecommendationService()

    async def list_user_subscriptions(
        self, user_id: UUID
    ) -> List[SubscriptionResult]:
        """List all subscriptions for a user.

        Args:
            user_id: The user's UUID.

        Returns:
            List of SubscriptionResult DTOs.
        """
        subscriptions = await self._subscription_repo.get_by_user_id(user_id)

        results = []
        for sub in subscriptions:
            # Fetch plan title for display
            plan = await self._plan_repo.get_by_id(sub.plan_id, include_deleted=True)
            plan_title = plan.title if plan else "Plano removido"
            results.append(self._to_result(sub, plan_title))

        return results

    async def recommend(
        self, input_data: RecommendSubscriptionInput
    ) -> RecommendationResultDTO:
        """Get plan recommendation based on target amount and preference.

        Args:
            input_data: Recommendation input with target_amount and preference.

        Returns:
            RecommendationResultDTO with the best plan + parameters.

        Raises:
            NoViablePlanError: If no plan can accommodate the target amount.
            ValueError: If input is invalid.
        """
        # Validate preference
        try:
            preference = RecommendationPreference(input_data.preference)
        except ValueError:
            raise ValueError(
                f"Invalid preference: {input_data.preference}. "
                "Must be FEWER_PAYMENTS or LOWER_MONTHLY_AMOUNT"
            )

        # Fetch all active plans
        plans = await self._plan_repo.get_active_plans()

        if not plans:
            raise NoViablePlanError(input_data.target_amount_cents)

        # Delegate to domain service
        result = self._recommendation_service.recommend(
            plans=plans,
            target_amount_cents=input_data.target_amount_cents,
            preference=preference,
        )

        if result is None:
            raise NoViablePlanError(input_data.target_amount_cents)

        return RecommendationResultDTO(
            plan_id=result.plan_id,
            plan_title=result.plan_title,
            deposit_count=result.deposit_count,
            monthly_amount_cents=result.monthly_amount_cents,
            total_cost_cents=result.total_cost_cents,
            admin_tax_value_cents=result.admin_tax_value_cents,
            insurance_cost_cents=result.insurance_cost_cents,
            guarantee_fund_cost_cents=result.guarantee_fund_cost_cents,
            guarantee_fund_percent=result.guarantee_fund_percent,
            min_duration_months=result.min_duration_months,
            max_duration_months=result.max_duration_months,
            min_value_cents=result.min_value_cents,
            max_value_cents=result.max_value_cents,
        )

    async def calculate_cost(
        self, input_data: CalculateCostInput
    ) -> CostResultDTO:
        """Calculate cost breakdown for specific subscription parameters.

        Used when the user adjusts deposit_count or monthly_amount
        in the subscription modal.

        Args:
            input_data: Cost calculation input.

        Returns:
            CostResultDTO with detailed cost breakdown.

        Raises:
            PlanNotFoundError: If plan doesn't exist.
            InvalidSubscriptionError: If parameters violate plan limits.
        """
        plan = await self._plan_repo.get_by_id(input_data.plan_id)
        if not plan:
            raise PlanNotFoundError(str(input_data.plan_id))

        # Validate parameters against plan limits
        validation_error = self._recommendation_service.validate_params_against_plan(
            plan=plan,
            target_amount_cents=input_data.target_amount_cents,
            deposit_count=input_data.deposit_count,
        )
        if validation_error:
            raise InvalidSubscriptionError(validation_error)

        # Calculate cost using domain service
        cost = self._recommendation_service.calculate_cost(
            plan=plan,
            deposit_count=input_data.deposit_count,
            monthly_amount_cents=input_data.monthly_amount_cents,
        )

        return CostResultDTO(
            total_cost_cents=cost.total_cost_cents,
            admin_tax_value_cents=cost.admin_tax_value_cents,
            insurance_cost_cents=cost.insurance_cost_cents,
            guarantee_fund_cost_cents=cost.guarantee_fund_cost_cents,
            guarantee_fund_percent=cost.guarantee_fund_percent,
            monthly_amount_cents=cost.monthly_amount_cents,
            deposit_count=cost.deposit_count,
        )

    async def create_subscription(
        self,
        input_data: CreateSubscriptionInput,
    ) -> SubscriptionResult:
        """Create a new subscription for a user.

        Validates parameters against plan limits, calculates cost,
        and persists the subscription with fee snapshots.

        Args:
            input_data: Subscription creation input.

        Returns:
            The created SubscriptionResult.

        Raises:
            PlanNotFoundError: If plan doesn't exist or is inactive.
            InvalidSubscriptionError: If parameters violate plan limits.
        """
        # Fetch and validate plan
        plan = await self._plan_repo.get_by_id(input_data.plan_id)
        if not plan:
            raise PlanNotFoundError(str(input_data.plan_id))

        if not plan.is_active():
            raise InvalidSubscriptionError("Plan is not active")

        # Validate parameters against plan limits
        validation_error = self._recommendation_service.validate_params_against_plan(
            plan=plan,
            target_amount_cents=input_data.target_amount_cents,
            deposit_count=input_data.deposit_count,
        )
        if validation_error:
            raise InvalidSubscriptionError(validation_error)

        # Calculate cost using domain service
        cost = self._recommendation_service.calculate_cost(
            plan=plan,
            deposit_count=input_data.deposit_count,
            monthly_amount_cents=input_data.monthly_amount_cents,
        )

        # Create domain entity with fee snapshots
        subscription = UserPlanSubscription.create(
            user_id=input_data.user_id,
            plan_id=input_data.plan_id,
            target_amount_cents=input_data.target_amount_cents,
            deposit_count=input_data.deposit_count,
            monthly_amount_cents=input_data.monthly_amount_cents,
            admin_tax_value_cents=cost.admin_tax_value_cents,
            insurance_percent=plan.insurance_percent,
            guarantee_fund_percent=cost.guarantee_fund_percent,
            total_cost_cents=cost.total_cost_cents,
        )

        # Persist
        saved = await self._subscription_repo.save(subscription)

        # Audit log
        audit = AuditLog.create(
            action=AuditAction.SUBSCRIPTION_CREATED,
            actor_id=input_data.user_id,
            target_id=saved.id,
            target_type="subscription",
            details={
                "plan_id": str(input_data.plan_id),
                "target_amount_cents": input_data.target_amount_cents,
                "deposit_count": input_data.deposit_count,
                "monthly_amount_cents": input_data.monthly_amount_cents,
                "total_cost_cents": cost.total_cost_cents,
            },
        )
        await self._audit_repo.save(audit)

        await self._session.commit()

        return self._to_result(saved, plan.title)

    def _to_result(
        self, subscription: UserPlanSubscription, plan_title: str
    ) -> SubscriptionResult:
        """Convert subscription entity to result DTO.

        Args:
            subscription: The domain entity.
            plan_title: Title of the associated plan.

        Returns:
            SubscriptionResult DTO.
        """
        return SubscriptionResult(
            id=subscription.id,
            user_id=subscription.user_id,
            plan_id=subscription.plan_id,
            plan_title=plan_title,
            target_amount_cents=subscription.target_amount_cents,
            deposit_count=subscription.deposit_count,
            monthly_amount_cents=subscription.monthly_amount_cents,
            admin_tax_value_cents=subscription.admin_tax_value_cents,
            insurance_percent=subscription.insurance_percent,
            guarantee_fund_percent=subscription.guarantee_fund_percent,
            total_cost_cents=subscription.total_cost_cents,
            status=subscription.status.value,
            created_at=subscription.created_at.isoformat(),
        )
