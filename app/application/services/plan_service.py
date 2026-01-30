"""Plan management service for admin operations."""

from typing import List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos.plan import CreatePlanInput, PlanResult, UpdatePlanInput
from app.domain.entities.audit_log import AuditAction, AuditLog
from app.domain.entities.plan import Plan
from app.domain.exceptions import PlanNotFoundError
from app.infrastructure.db.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.db.repositories.plan_repository import PlanRepository


class PlanService:
    """Service for plan management operations.

    Handles creation, update, and listing of plans.
    All operations are admin-only and create audit logs.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize service with database session.

        Args:
            session: The async database session.
        """
        self._session = session
        self._plan_repo = PlanRepository(session)
        self._audit_repo = AuditLogRepository(session)

    async def list_plans(
        self,
        title_search: Optional[str] = None,
    ) -> List[PlanResult]:
        """List all plans with optional filtering.

        Args:
            title_search: Optional title search filter (case-insensitive).

        Returns:
            List of PlanResult DTOs.
        """
        plans = await self._plan_repo.get_all(title_search=title_search)
        return [self._to_result(plan) for plan in plans]

    async def create_plan(
        self,
        input_data: CreatePlanInput,
        admin_id: UUID,
    ) -> PlanResult:
        """Create a new plan.

        Args:
            input_data: Plan creation input data.
            admin_id: UUID of the admin creating the plan.

        Returns:
            The created PlanResult.

        Raises:
            ValueError: If plan data is invalid.
        """
        # Create domain entity (validation happens in entity)
        plan = Plan.create(
            title=input_data.title,
            description=input_data.description,
            min_value_cents=input_data.min_value_cents,
            max_value_cents=input_data.max_value_cents,
            min_duration_months=input_data.min_duration_months,
            max_duration_months=input_data.max_duration_months,
            admin_tax_value_cents=input_data.admin_tax_value_cents,
            insurance_percent=input_data.insurance_percent,
            guarantee_fund_percent_1=input_data.guarantee_fund_percent_1,
            guarantee_fund_percent_2=input_data.guarantee_fund_percent_2,
            guarantee_fund_threshold_cents=input_data.guarantee_fund_threshold_cents,
            active=input_data.active,
        )

        # Persist plan
        saved_plan = await self._plan_repo.save(plan)

        # Create audit log
        audit = AuditLog.create(
            action=AuditAction.PLAN_CREATED,
            actor_id=admin_id,
            target_id=saved_plan.id,
            target_type="plan",
            details={
                "title": saved_plan.title,
                "min_value_cents": saved_plan.min_value_cents,
                "max_value_cents": saved_plan.max_value_cents,
            },
        )
        await self._audit_repo.save(audit)

        await self._session.commit()

        return self._to_result(saved_plan)

    async def update_plan(
        self,
        input_data: UpdatePlanInput,
        admin_id: UUID,
    ) -> PlanResult:
        """Update an existing plan.

        This does NOT affect existing contracts.

        Args:
            input_data: Plan update input data.
            admin_id: UUID of the admin updating the plan.

        Returns:
            The updated PlanResult.

        Raises:
            PlanNotFoundError: If plan does not exist.
            ValueError: If plan data is invalid.
        """
        # Fetch existing plan
        plan = await self._plan_repo.get_by_id(input_data.plan_id)
        if not plan:
            raise PlanNotFoundError(str(input_data.plan_id))

        # Store old values for audit
        old_title = plan.title

        # Update entity (validation happens in entity)
        plan.update(
            title=input_data.title,
            description=input_data.description,
            min_value_cents=input_data.min_value_cents,
            max_value_cents=input_data.max_value_cents,
            min_duration_months=input_data.min_duration_months,
            max_duration_months=input_data.max_duration_months,
            admin_tax_value_cents=input_data.admin_tax_value_cents,
            insurance_percent=input_data.insurance_percent,
            guarantee_fund_percent_1=input_data.guarantee_fund_percent_1,
            guarantee_fund_percent_2=input_data.guarantee_fund_percent_2,
            guarantee_fund_threshold_cents=input_data.guarantee_fund_threshold_cents,
            active=input_data.active,
        )

        if input_data.active and not plan.active:
            plan.activate()
        elif not input_data.active and plan.active:
            plan.deactivate()

        # Persist changes
        saved_plan = await self._plan_repo.save(plan)

        # Create audit log
        audit = AuditLog.create(
            action=AuditAction.PLAN_UPDATED,
            actor_id=admin_id,
            target_id=saved_plan.id,
            target_type="plan",
            details={
                "old_title": old_title,
                "new_title": saved_plan.title,
            },
        )
        await self._audit_repo.save(audit)

        await self._session.commit()

        return self._to_result(saved_plan)

    async def get_plan(self, plan_id: UUID) -> PlanResult:
        """Get a single plan by ID.

        Args:
            plan_id: The plan's UUID.

        Returns:
            PlanResult DTO.

        Raises:
            PlanNotFoundError: If plan does not exist.
        """
        plan = await self._plan_repo.get_by_id(plan_id)
        if not plan:
            raise PlanNotFoundError(str(plan_id))
        return self._to_result(plan)

    async def delete_plan(
        self,
        plan_id: UUID,
        admin_id: UUID,
    ) -> None:
        """Soft delete a plan.

        Marks the plan as deleted by setting deleted_at timestamp.
        The plan is not removed from the database.

        Args:
            plan_id: UUID of the plan to delete.
            admin_id: UUID of the admin performing the deletion.

        Raises:
            PlanNotFoundError: If plan does not exist or is already deleted.
            ValueError: If plan is already deleted.
        """
        # Fetch existing plan (will not return if already deleted)
        plan = await self._plan_repo.get_by_id(plan_id)
        if not plan:
            raise PlanNotFoundError(str(plan_id))

        # Store title for audit
        plan_title = plan.title

        # Mark as deleted (domain entity validates)
        plan.soft_delete()

        # Persist changes
        await self._plan_repo.save(plan)

        # Create audit log
        audit = AuditLog.create(
            action=AuditAction.PLAN_DELETED,
            actor_id=admin_id,
            target_id=plan_id,
            target_type="plan",
            details={
                "title": plan_title,
            },
        )
        await self._audit_repo.save(audit)

        await self._session.commit()

    def _to_result(self, plan: Plan) -> PlanResult:
        """Convert Plan entity to PlanResult DTO.

        Args:
            plan: The Plan domain entity.

        Returns:
            PlanResult DTO.
        """
        return PlanResult(
            id=plan.id,
            title=plan.title,
            description=plan.description,
            min_value_cents=plan.min_value_cents,
            max_value_cents=plan.max_value_cents,
            min_duration_months=plan.min_duration_months,
            max_duration_months=plan.max_duration_months,
            admin_tax_value_cents=plan.admin_tax_value_cents,
            insurance_percent=plan.insurance_percent,
            guarantee_fund_percent_1=plan.guarantee_fund_percent_1,
            guarantee_fund_percent_2=plan.guarantee_fund_percent_2,
            guarantee_fund_threshold_cents=plan.guarantee_fund_threshold_cents,
            active=plan.active,
        )
