"""Subscription service for managing user plan subscriptions."""

from datetime import date, datetime, timezone
from typing import List
from uuid import UUID

import zoneinfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos.subscription import (
    CalculateCostInput,
    CostResultDTO,
    CreateSubscriptionInput,
    DashboardDueStatus,
    DuePlanInfo,
    RecommendationResultDTO,
    RecommendSubscriptionInput,
    SubscriptionResult,
    UpdateDepositDayInput,
    UpdateNameInput,
)
from app.domain.entities.audit_log import AuditAction, AuditLog
from app.domain.entities.subscription import ALLOWED_DEPOSIT_DAYS, UserPlanSubscription
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
from app.infrastructure.db.repositories.transaction_repository import TransactionRepository

# Default timezone when user.timezone is absent
_DEFAULT_TZ = zoneinfo.ZoneInfo("America/Sao_Paulo")


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
        self._transaction_repo = TransactionRepository(session)
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
            plan = await self._plan_repo.get_by_id(sub.plan_id, include_deleted=True)
            plan_title = plan.title if plan else "Plano removido"
            yield_cents = await self._transaction_repo.get_yield_sum_by_subscription(sub.id)
            results.append(self._to_result(sub, plan_title, yield_cents))

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

        # Create domain entity with fee snapshots (starts as INACTIVE)
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
            name=input_data.name,
            deposit_day_of_month=input_data.deposit_day_of_month,
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
        self, subscription: UserPlanSubscription, plan_title: str, yield_cents: int = 0
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
            name=subscription.name,
            target_amount_cents=subscription.target_amount_cents,
            deposit_count=subscription.deposit_count,
            monthly_amount_cents=subscription.monthly_amount_cents,
            admin_tax_value_cents=subscription.admin_tax_value_cents,
            insurance_percent=subscription.insurance_percent,
            guarantee_fund_percent=subscription.guarantee_fund_percent,
            total_cost_cents=subscription.total_cost_cents,
            deposit_day_of_month=subscription.deposit_day_of_month,
            next_due_date=subscription.next_due_date.isoformat() if subscription.next_due_date else None,
            has_overdue_deposit=subscription.has_overdue_deposit,
            covers_activation_fees=subscription.covers_activation_fees,
            status=subscription.status.value,
            created_at=subscription.created_at.isoformat(),
            accumulated_cents=subscription.total_deposited_cents,
            deposits_paid=subscription.deposits_paid,
            yield_cents=yield_cents,
        )

    # ------------------------------------------------------------------
    # Deposit day update
    # ------------------------------------------------------------------

    async def update_deposit_day(
        self, input_data: UpdateDepositDayInput
    ) -> SubscriptionResult:
        """Update the deposit day-of-month for a subscription.

        Recomputes next_due_date based on the new day.

        Args:
            input_data: Contains subscription_id, user_id, deposit_day_of_month.

        Returns:
            Updated SubscriptionResult.

        Raises:
            SubscriptionNotFoundError: If subscription not found or not owned.
            InvalidSubscriptionError: If day is not allowed or sub not active.
        """
        subscription = await self._subscription_repo.get_by_id(
            input_data.subscription_id
        )
        if not subscription or subscription.user_id != input_data.user_id:
            raise SubscriptionNotFoundError(str(input_data.subscription_id))

        if not subscription.is_active():
            raise InvalidSubscriptionError("Subscription is not active")

        if input_data.deposit_day_of_month not in ALLOWED_DEPOSIT_DAYS:
            raise InvalidSubscriptionError(
                f"deposit_day_of_month must be one of {sorted(ALLOWED_DEPOSIT_DAYS)}"
            )

        today_local = self._today_local()
        subscription.set_deposit_day(input_data.deposit_day_of_month, today_local)

        saved = await self._subscription_repo.save(subscription)

        plan = await self._plan_repo.get_by_id(saved.plan_id, include_deleted=True)
        plan_title = plan.title if plan else "Plano removido"
        yield_cents = await self._transaction_repo.get_yield_sum_by_subscription(saved.id)

        await self._session.commit()
        return self._to_result(saved, plan_title, yield_cents)

    # ------------------------------------------------------------------
    # Name update
    # ------------------------------------------------------------------

    async def update_name(
        self, input_data: UpdateNameInput
    ) -> SubscriptionResult:
        """Update the cosmetic name of a subscription.

        Args:
            input_data: Contains subscription_id, user_id, name.

        Returns:
            Updated SubscriptionResult.

        Raises:
            SubscriptionNotFoundError: If subscription not found or not owned.
        """
        subscription = await self._subscription_repo.get_by_id(
            input_data.subscription_id
        )
        if not subscription or subscription.user_id != input_data.user_id:
            raise SubscriptionNotFoundError(str(input_data.subscription_id))

        subscription.name = input_data.name

        saved = await self._subscription_repo.save(subscription)

        plan = await self._plan_repo.get_by_id(saved.plan_id, include_deleted=True)
        plan_title = plan.title if plan else "Plano removido"
        yield_cents = await self._transaction_repo.get_yield_sum_by_subscription(saved.id)

        await self._session.commit()
        return self._to_result(saved, plan_title, yield_cents)

    # ------------------------------------------------------------------
    # Dashboard lazy update
    # ------------------------------------------------------------------

    async def get_dashboard_due_status(
        self, user_id: UUID
    ) -> DashboardDueStatus:
        """Compute due/overdue status and lazily flag overdue subscriptions.

        Steps:
        1. Compute today_local in user timezone.
        2. Query subscriptions where next_due_date <= today_local.
        3. Partition into overdue (< today) and due_today (== today).
        4. Bulk-update DB flags for newly-overdue subscriptions.
        5. Return status DTO for the dashboard banner.

        Args:
            user_id: The authenticated user's UUID.

        Returns:
            DashboardDueStatus with overdue_plans and due_today_plans.
        """
        today_local = self._today_local()
        now_utc = datetime.now(timezone.utc)

        subs = await self._subscription_repo.get_active_due_or_overdue(
            user_id, today_local
        )

        overdue_plans: list[DuePlanInfo] = []
        due_today_plans: list[DuePlanInfo] = []

        for sub in subs:
            plan = await self._plan_repo.get_by_id(sub.plan_id, include_deleted=True)
            plan_title = plan.title if plan else "Plano removido"
            info = DuePlanInfo(
                subscription_id=str(sub.id),
                plan_title=plan_title,
                name=sub.name,
                next_due_date=sub.next_due_date.isoformat(),
            )
            if sub.next_due_date < today_local:
                overdue_plans.append(info)
            else:
                due_today_plans.append(info)

        # Lazy bulk update: flag newly overdue rows
        if overdue_plans:
            await self._subscription_repo.bulk_mark_overdue(
                user_id, today_local, now_utc
            )

        return DashboardDueStatus(
            overdue_plans=overdue_plans,
            due_today_plans=due_today_plans,
        )

    # ------------------------------------------------------------------
    # Cancel subscription
    # ------------------------------------------------------------------

    async def cancel_subscription(
        self, subscription_id: UUID, user_id: UUID
    ) -> SubscriptionResult:
        """Cancel an inactive subscription.

        Only subscriptions in INACTIVE status (not yet activated) can be
        cancelled through this method.

        Args:
            subscription_id: UUID of the subscription.
            user_id: For authorization check.

        Returns:
            Updated SubscriptionResult with CANCELLED status.

        Raises:
            SubscriptionNotFoundError: If not found / not owned.
            InvalidSubscriptionError: If subscription is not inactive.
        """
        from app.domain.entities.subscription import SubscriptionStatus

        subscription = await self._subscription_repo.get_by_id(subscription_id)
        if not subscription or subscription.user_id != user_id:
            raise SubscriptionNotFoundError(str(subscription_id))

        if subscription.status != SubscriptionStatus.INACTIVE:
            raise InvalidSubscriptionError(
                "Apenas planos inativos (não ativados) podem ser cancelados diretamente."
            )

        subscription.cancel()
        saved = await self._subscription_repo.save(subscription)

        audit = AuditLog.create(
            action=AuditAction.SUBSCRIPTION_CANCELLED,
            actor_id=user_id,
            target_id=saved.id,
            target_type="subscription",
            details={"reason": "user_requested"},
        )
        await self._audit_repo.save(audit)

        await self._session.commit()

        plan = await self._plan_repo.get_by_id(saved.plan_id, include_deleted=True)
        plan_title = plan.title if plan else "Plano removido"
        yield_cents = await self._transaction_repo.get_yield_sum_by_subscription(saved.id)

        return self._to_result(saved, plan_title, yield_cents)

    # ------------------------------------------------------------------
    # Payment recording helper
    # ------------------------------------------------------------------

    async def record_payment_for_subscription(
        self, subscription_id: UUID, user_id: UUID
    ) -> SubscriptionResult:
        """Clear overdue flag and advance next_due_date after payment.

        Must be called when a deposit for this subscription is confirmed.

        Args:
            subscription_id: UUID of the subscription.
            user_id: For authorization check.

        Returns:
            Updated SubscriptionResult.

        Raises:
            SubscriptionNotFoundError: If not found / not owned.
        """
        subscription = await self._subscription_repo.get_by_id(subscription_id)
        if not subscription or subscription.user_id != user_id:
            raise SubscriptionNotFoundError(str(subscription_id))

        today_local = self._today_local()
        subscription.clear_overdue_and_advance(today_local)

        saved = await self._subscription_repo.save(subscription)

        plan = await self._plan_repo.get_by_id(saved.plan_id, include_deleted=True)
        plan_title = plan.title if plan else "Plano removido"
        yield_cents = await self._transaction_repo.get_yield_sum_by_subscription(saved.id)

        await self._session.commit()
        return self._to_result(saved, plan_title, yield_cents)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _today_local() -> date:
        """Return current calendar date in the default timezone.

        Uses America/Sao_Paulo. If per-user timezones are added later,
        this method should accept the user entity and read user.timezone.
        """
        return datetime.now(_DEFAULT_TZ).date()
