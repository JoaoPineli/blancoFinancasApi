"""Subscription endpoints for user plan subscriptions."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.api.v1.dependencies import CurrentUser, DbSession
from app.api.v1.schemas.subscription import (
    CalculateCostRequest,
    CostResponse,
    CreateSubscriptionRequest,
    RecommendationResponse,
    RecommendSubscriptionRequest,
    SubscriptionListResponse,
    SubscriptionResponse,
)
from app.application.dtos.subscription import (
    CalculateCostInput,
    CreateSubscriptionInput,
    RecommendSubscriptionInput,
)
from app.application.services.subscription_service import SubscriptionService
from app.domain.exceptions import (
    InvalidSubscriptionError,
    NoViablePlanError,
    PlanNotFoundError,
)

router = APIRouter()


@router.get(
    "",
    response_model=SubscriptionListResponse,
    summary="List user subscriptions",
)
async def list_subscriptions(
    session: DbSession,
    current_user: CurrentUser,
) -> SubscriptionListResponse:
    """List all subscriptions for the authenticated user.

    Users can only see their own subscriptions (authorization enforced
    by using current_user.id).
    """
    service = SubscriptionService(session)
    results = await service.list_user_subscriptions(current_user.id)

    return SubscriptionListResponse(
        subscriptions=[
            SubscriptionResponse(
                id=str(r.id),
                user_id=str(r.user_id),
                plan_id=str(r.plan_id),
                plan_title=r.plan_title,
                target_amount_cents=r.target_amount_cents,
                deposit_count=r.deposit_count,
                monthly_amount_cents=r.monthly_amount_cents,
                admin_tax_value_cents=r.admin_tax_value_cents,
                insurance_percent=r.insurance_percent,
                guarantee_fund_percent=r.guarantee_fund_percent,
                total_cost_cents=r.total_cost_cents,
                status=r.status,
                created_at=r.created_at,
            )
            for r in results
        ],
        total=len(results),
    )


@router.post(
    "/recommend",
    response_model=RecommendationResponse,
    summary="Get plan recommendation",
)
async def recommend_subscription(
    request: RecommendSubscriptionRequest,
    session: DbSession,
    current_user: CurrentUser,
) -> RecommendationResponse:
    """Get a plan recommendation based on target amount and preference.

    Requires authentication. Uses existing plan parameters and domain
    services for cost calculation.
    """
    service = SubscriptionService(session)

    try:
        input_data = RecommendSubscriptionInput(
            target_amount_cents=request.target_amount_cents,
            preference=request.preference,
        )
        result = await service.recommend(input_data)

        return RecommendationResponse(
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
    except NoViablePlanError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=e.message,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post(
    "/calculate-cost",
    response_model=CostResponse,
    summary="Calculate subscription cost",
)
async def calculate_cost(
    request: CalculateCostRequest,
    session: DbSession,
    current_user: CurrentUser,
) -> CostResponse:
    """Calculate cost breakdown for specific subscription parameters.

    Used when user adjusts deposit_count or monthly_amount in the UI.
    Requires authentication. No financial calculations on frontend.
    """
    service = SubscriptionService(session)

    try:
        input_data = CalculateCostInput(
            plan_id=UUID(request.plan_id),
            target_amount_cents=request.target_amount_cents,
            deposit_count=request.deposit_count,
            monthly_amount_cents=request.monthly_amount_cents,
        )
        result = await service.calculate_cost(input_data)

        return CostResponse(
            total_cost_cents=result.total_cost_cents,
            admin_tax_value_cents=result.admin_tax_value_cents,
            insurance_cost_cents=result.insurance_cost_cents,
            guarantee_fund_cost_cents=result.guarantee_fund_cost_cents,
            guarantee_fund_percent=result.guarantee_fund_percent,
            monthly_amount_cents=result.monthly_amount_cents,
            deposit_count=result.deposit_count,
        )
    except PlanNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=e.message,
        )
    except InvalidSubscriptionError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=e.message,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post(
    "",
    response_model=SubscriptionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a subscription",
)
async def create_subscription(
    request: CreateSubscriptionRequest,
    session: DbSession,
    current_user: CurrentUser,
) -> SubscriptionResponse:
    """Create a new subscription for the authenticated user.

    Authorization: the user_id is always set from the authenticated user's
    token, ensuring users can only create subscriptions for themselves.
    """
    service = SubscriptionService(session)

    try:
        input_data = CreateSubscriptionInput(
            user_id=current_user.id,
            plan_id=UUID(request.plan_id),
            target_amount_cents=request.target_amount_cents,
            deposit_count=request.deposit_count,
            monthly_amount_cents=request.monthly_amount_cents,
        )
        result = await service.create_subscription(input_data)

        return SubscriptionResponse(
            id=str(result.id),
            user_id=str(result.user_id),
            plan_id=str(result.plan_id),
            plan_title=result.plan_title,
            target_amount_cents=result.target_amount_cents,
            deposit_count=result.deposit_count,
            monthly_amount_cents=result.monthly_amount_cents,
            admin_tax_value_cents=result.admin_tax_value_cents,
            insurance_percent=result.insurance_percent,
            guarantee_fund_percent=result.guarantee_fund_percent,
            total_cost_cents=result.total_cost_cents,
            status=result.status,
            created_at=result.created_at,
        )
    except PlanNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=e.message,
        )
    except InvalidSubscriptionError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=e.message,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
