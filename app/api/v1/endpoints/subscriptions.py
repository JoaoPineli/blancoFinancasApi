"""Subscription endpoints for user plan subscriptions."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.api.v1.dependencies import CurrentUser, DbSession
from app.api.v1.schemas.subscription import (
    ActivationPaymentResponse,
    CalculateCostRequest,
    CostResponse,
    CreateSubscriptionRequest,
    DashboardDueStatusResponse,
    DuePlanInfoResponse,
    RecommendationResponse,
    RecommendSubscriptionRequest,
    SubscriptionListResponse,
    SubscriptionResponse,
    UpdateDepositDayRequest,
    UpdateNameRequest,
)
from app.application.dtos.subscription import (
    CalculateCostInput,
    CreateSubscriptionInput,
    RecommendSubscriptionInput,
    UpdateDepositDayInput,
    UpdateNameInput,
)
from app.application.dtos.finance import CreateActivationPaymentInput
from app.application.services.subscription_activation_payment_service import (
    SubscriptionActivationPaymentService,
)
from app.application.services.subscription_service import SubscriptionService
from app.domain.exceptions import (
    InvalidSubscriptionError,
    NoViablePlanError,
    PaymentNotFoundError,
    PlanNotFoundError,
    SubscriptionNotFoundError,
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
                name=r.name,
                target_amount_cents=r.target_amount_cents,
                deposit_count=r.deposit_count,
                monthly_amount_cents=r.monthly_amount_cents,
                admin_tax_value_cents=r.admin_tax_value_cents,
                insurance_percent=r.insurance_percent,
                guarantee_fund_percent=r.guarantee_fund_percent,
                total_cost_cents=r.total_cost_cents,
                deposit_day_of_month=r.deposit_day_of_month,
                next_due_date=r.next_due_date,
                has_overdue_deposit=r.has_overdue_deposit,
                status=r.status,
                covers_activation_fees=r.covers_activation_fees,
                created_at=r.created_at,
                accumulated_cents=r.accumulated_cents,
                deposits_paid=r.deposits_paid,
                yield_cents=r.yield_cents,
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
            name=request.name,
            deposit_day_of_month=request.deposit_day_of_month,
        )
        result = await service.create_subscription(input_data)

        return SubscriptionResponse(
            id=str(result.id),
            user_id=str(result.user_id),
            plan_id=str(result.plan_id),
            plan_title=result.plan_title,
            name=result.name,
            target_amount_cents=result.target_amount_cents,
            deposit_count=result.deposit_count,
            monthly_amount_cents=result.monthly_amount_cents,
            admin_tax_value_cents=result.admin_tax_value_cents,
            insurance_percent=result.insurance_percent,
            guarantee_fund_percent=result.guarantee_fund_percent,
            total_cost_cents=result.total_cost_cents,
            deposit_day_of_month=result.deposit_day_of_month,
            next_due_date=result.next_due_date,
            has_overdue_deposit=result.has_overdue_deposit,
            status=result.status,
            covers_activation_fees=result.covers_activation_fees,
            created_at=result.created_at,
            accumulated_cents=result.accumulated_cents,
            deposits_paid=result.deposits_paid,
            yield_cents=result.yield_cents,
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


@router.patch(
    "/{subscription_id}/deposit-day",
    response_model=SubscriptionResponse,
    summary="Update deposit day of month",
)
async def update_deposit_day(
    subscription_id: str,
    request: UpdateDepositDayRequest,
    session: DbSession,
    current_user: CurrentUser,
) -> SubscriptionResponse:
    """Change the deposit day-of-month for a subscription.

    Recomputes next_due_date to the next occurrence of the new day.
    Allowed values: 1, 5, 10, 15, 20, 25.
    """
    service = SubscriptionService(session)

    try:
        input_data = UpdateDepositDayInput(
            user_id=current_user.id,
            subscription_id=UUID(subscription_id),
            deposit_day_of_month=request.deposit_day_of_month,
        )
        result = await service.update_deposit_day(input_data)

        return SubscriptionResponse(
            id=str(result.id),
            user_id=str(result.user_id),
            plan_id=str(result.plan_id),
            plan_title=result.plan_title,
            name=result.name,
            target_amount_cents=result.target_amount_cents,
            deposit_count=result.deposit_count,
            monthly_amount_cents=result.monthly_amount_cents,
            admin_tax_value_cents=result.admin_tax_value_cents,
            insurance_percent=result.insurance_percent,
            guarantee_fund_percent=result.guarantee_fund_percent,
            total_cost_cents=result.total_cost_cents,
            deposit_day_of_month=result.deposit_day_of_month,
            next_due_date=result.next_due_date,
            has_overdue_deposit=result.has_overdue_deposit,
            status=result.status,
            covers_activation_fees=result.covers_activation_fees,
            created_at=result.created_at,
            accumulated_cents=result.accumulated_cents,
            deposits_paid=result.deposits_paid,
            yield_cents=result.yield_cents,
        )
    except SubscriptionNotFoundError as e:
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


@router.patch(
    "/{subscription_id}/name",
    response_model=SubscriptionResponse,
    summary="Update subscription name",
)
async def update_name(
    subscription_id: str,
    request: UpdateNameRequest,
    session: DbSession,
    current_user: CurrentUser,
) -> SubscriptionResponse:
    """Update the cosmetic name of a subscription."""
    service = SubscriptionService(session)

    try:
        input_data = UpdateNameInput(
            user_id=current_user.id,
            subscription_id=UUID(subscription_id),
            name=request.name,
        )
        result = await service.update_name(input_data)

        return SubscriptionResponse(
            id=str(result.id),
            user_id=str(result.user_id),
            plan_id=str(result.plan_id),
            plan_title=result.plan_title,
            name=result.name,
            target_amount_cents=result.target_amount_cents,
            deposit_count=result.deposit_count,
            monthly_amount_cents=result.monthly_amount_cents,
            admin_tax_value_cents=result.admin_tax_value_cents,
            insurance_percent=result.insurance_percent,
            guarantee_fund_percent=result.guarantee_fund_percent,
            total_cost_cents=result.total_cost_cents,
            deposit_day_of_month=result.deposit_day_of_month,
            next_due_date=result.next_due_date,
            has_overdue_deposit=result.has_overdue_deposit,
            status=result.status,
            covers_activation_fees=result.covers_activation_fees,
            created_at=result.created_at,
            accumulated_cents=result.accumulated_cents,
            deposits_paid=result.deposits_paid,
            yield_cents=result.yield_cents,
        )
    except SubscriptionNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=e.message,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get(
    "/dashboard/due-status",
    response_model=DashboardDueStatusResponse,
    summary="Get dashboard due/overdue status",
)
async def get_dashboard_due_status(
    session: DbSession,
    current_user: CurrentUser,
) -> DashboardDueStatusResponse:
    """Get due/overdue subscription status for the dashboard banner.

    Performs lazy update: flags newly-overdue subscriptions in the DB.
    Returns arrays of due-today and overdue plan info for the banner.
    """
    service = SubscriptionService(session)
    result = await service.get_dashboard_due_status(current_user.id)

    return DashboardDueStatusResponse(
        overdue_plans=[
            DuePlanInfoResponse(
                subscription_id=p.subscription_id,
                plan_title=p.plan_title,
                name=p.name,
                next_due_date=p.next_due_date,
            )
            for p in result.overdue_plans
        ],
        due_today_plans=[
            DuePlanInfoResponse(
                subscription_id=p.subscription_id,
                plan_title=p.plan_title,
                name=p.name,
                next_due_date=p.next_due_date,
            )
            for p in result.due_today_plans
        ],
    )


# ------------------------------------------------------------------
# Cancel subscription endpoint
# ------------------------------------------------------------------


@router.post(
    "/{subscription_id}/cancel",
    response_model=SubscriptionResponse,
    summary="Cancel an inactive subscription",
)
async def cancel_subscription(
    subscription_id: str,
    session: DbSession,
    current_user: CurrentUser,
) -> SubscriptionResponse:
    """Cancel an inactive (not yet activated) subscription.

    Only subscriptions in INACTIVE status can be cancelled through this
    endpoint. Active subscriptions must exit via the withdrawal flow.
    """
    service = SubscriptionService(session)
    try:
        result = await service.cancel_subscription(
            UUID(subscription_id), current_user.id
        )
        return SubscriptionResponse(
            id=str(result.id),
            user_id=str(result.user_id),
            plan_id=str(result.plan_id),
            plan_title=result.plan_title,
            name=result.name,
            target_amount_cents=result.target_amount_cents,
            deposit_count=result.deposit_count,
            monthly_amount_cents=result.monthly_amount_cents,
            admin_tax_value_cents=result.admin_tax_value_cents,
            insurance_percent=result.insurance_percent,
            guarantee_fund_percent=result.guarantee_fund_percent,
            total_cost_cents=result.total_cost_cents,
            deposit_day_of_month=result.deposit_day_of_month,
            next_due_date=result.next_due_date,
            has_overdue_deposit=result.has_overdue_deposit,
            status=result.status,
            covers_activation_fees=result.covers_activation_fees,
            created_at=result.created_at,
            accumulated_cents=result.accumulated_cents,
            deposits_paid=result.deposits_paid,
            yield_cents=result.yield_cents,
        )
    except SubscriptionNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
    except InvalidSubscriptionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# ------------------------------------------------------------------
# Subscription Activation Payment endpoints
# ------------------------------------------------------------------


@router.post(
    "/{subscription_id}/activation-payment",
    response_model=ActivationPaymentResponse,
    status_code=status.HTTP_200_OK,
    summary="Create or get pending activation payment",
)
async def create_activation_payment(
    subscription_id: str,
    session: DbSession,
    current_user: CurrentUser,
) -> ActivationPaymentResponse:
    """Create or return the existing pending activation payment for a subscription.

    This endpoint is idempotent: calling it multiple times returns the same
    pending payment rather than creating duplicates.

    The response includes the Pix QR code to pay the one-time activation fee
    (admin tax + insurance + 0.99% Pix transaction fee).
    """
    service = SubscriptionActivationPaymentService(session)
    try:
        result = await service.create_or_get_pending(
            CreateActivationPaymentInput(
                user_id=current_user.id,
                subscription_id=UUID(subscription_id),
            )
        )
        return _activation_payment_to_response(result)
    except SubscriptionNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
    except InvalidSubscriptionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/{subscription_id}/activation-payment",
    response_model=ActivationPaymentResponse,
    summary="Get current activation payment",
)
async def get_activation_payment(
    subscription_id: str,
    session: DbSession,
    current_user: CurrentUser,
) -> ActivationPaymentResponse:
    """Get the pending or latest activation payment for a subscription."""
    service = SubscriptionActivationPaymentService(session)
    try:
        result = await service.get_payment_for_subscription(
            subscription_id=UUID(subscription_id),
            user_id=current_user.id,
        )
        return _activation_payment_to_response(result)
    except SubscriptionNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
    except PaymentNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _activation_payment_to_response(dto) -> ActivationPaymentResponse:
    """Convert ActivationPaymentDTO to response schema."""
    return ActivationPaymentResponse(
        id=str(dto.id),
        user_id=str(dto.user_id),
        subscription_id=str(dto.subscription_id),
        status=dto.status,
        admin_tax_cents=dto.admin_tax_cents,
        insurance_cents=dto.insurance_cents,
        pix_transaction_fee_cents=dto.pix_transaction_fee_cents,
        total_amount_cents=dto.total_amount_cents,
        pix_qr_code_data=dto.pix_qr_code_data,
        pix_qr_code_base64=dto.pix_qr_code_base64,
        pix_transaction_id=dto.pix_transaction_id,
        expiration_minutes=dto.expiration_minutes,
        created_at=dto.created_at.isoformat(),
        updated_at=dto.updated_at.isoformat(),
        confirmed_at=dto.confirmed_at.isoformat() if dto.confirmed_at else None,
    )