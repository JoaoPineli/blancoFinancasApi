"""Admin endpoints for platform administration."""

from datetime import datetime
from io import BytesIO
from typing import List
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from app.api.v1.dependencies import CurrentAdmin, DbSession
from app.api.v1.schemas.user import UserListResponse, UserResponse, UserStatusRequest
from app.api.v1.schemas.finance import (
    ApproveWithdrawalRequest,
    PixWebhookPayload,
    RejectWithdrawalRequest,
    TransactionListResponse,
    TransactionResponse,
)
from app.api.v1.schemas.invitation import InviteUserRequest, InviteUserResponse
from app.api.v1.schemas.plan import (
    CreatePlanRequest,
    PlanListResponse,
    PlanResponse,
    PlanSummaryResponse,
    UpdatePlanRequest,
)
from app.application.dtos.finance import ApproveWithdrawalInput
from app.application.dtos.invitation import InviteUserInput
from app.application.dtos.plan import CreatePlanInput, UpdatePlanInput
from app.application.services.deposit_service import CreateDepositService
from app.application.services.installment_payment_service import (
    InstallmentPaymentService,
)
from app.application.services.invitation_service import InvitationService
from app.application.services.plan_service import PlanService
from app.application.services.withdrawal_service import WithdrawalService
from app.domain.entities.audit_log import AuditAction, AuditLog
from app.domain.entities.user import UserStatus
from app.domain.exceptions import (
    AuthorizationError,
    UserNotFoundError,
    UserAlreadyExistsError,
    PlanNotFoundError,
    InvalidWithdrawalError,
    TransactionNotFoundError,
)
from app.infrastructure.db.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.db.repositories.installment_payment_repository import (
    InstallmentPaymentRepository,
)
from app.infrastructure.db.repositories.user_repository import UserRepository
from app.infrastructure.db.repositories.transaction_repository import TransactionRepository
from app.infrastructure.email.exceptions import EmailError
from app.infrastructure.email.sendgrid_client import SendGridClient
from app.infrastructure.exports.excel_generator import ExcelReportGenerator

router = APIRouter()


@router.post(
    "/invite",
    response_model=InviteUserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Invite a new user",
)
async def invite_user(
    request: InviteUserRequest,
    session: DbSession,
    current_admin: CurrentAdmin,
) -> InviteUserResponse:
    """Invite a new user to the platform.

    Creates a user with INVITED status and sends an activation email.
    The user cannot authenticate until they complete the activation
    process using the link sent in the email.

    The activation token is NEVER exposed in the API response.

    Admin only endpoint.
    """
    email_sender = SendGridClient()
    service = InvitationService(session, email_sender)

    try:
        input_data = InviteUserInput(
            name=request.name,
            email=request.email,
            plan_id=request.plan_id,
        )
        result = await service.invite_user(input_data, admin_id=current_admin.id)

        return InviteUserResponse(
            user_id=str(result.user_id),
            email=result.email,
            name=result.name,
        )
    except UserAlreadyExistsError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )
    except PlanNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plan not found",
        )
    except EmailError:
        # Email delivery failed - invitation is NOT persisted
        # Generic message to avoid leaking information
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to send invitation email. Please try again later.",
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get(
    "/users",
    response_model=UserListResponse,
    summary="List all users",
)
async def list_users(
    session: DbSession,
    current_admin: CurrentAdmin,
    status_filter: str | None = Query(None, pattern="^(active|inactive|defaulting|invited)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> UserListResponse:
    """List all users with optional filtering.

    Admin only endpoint.
    """
    user_repo = UserRepository(session)

    # Convert status filter
    user_status = UserStatus(status_filter) if status_filter else None

    offset = (page - 1) * page_size
    users = await user_repo.get_all(
        status=user_status,
        limit=page_size,
        offset=offset,
    )

    return UserListResponse(
        users=[
            UserResponse(
                id=str(c.id),
                cpf=c.cpf.formatted if c.cpf else None,
                email=c.email.value,
                name=c.name,
                role=c.role.value,
                status=c.status.value,
                phone=c.phone,
                created_at=c.created_at,
            )
            for c in users
        ],
        total=len(users),
        page=page,
        page_size=page_size,
    )


@router.patch(
    "/users/{user_id}/status",
    response_model=UserResponse,
    summary="Change user status",
)
async def change_user_status(
    user_id: str,
    request: UserStatusRequest,
    session: DbSession,
    current_admin: CurrentAdmin,
) -> UserResponse:
    """Change a user's status.

    Admin only endpoint. Creates audit log.
    """
    user_repo = UserRepository(session)
    audit_repo = AuditLogRepository(session)

    user = await user_repo.get_by_id(UUID(user_id))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    old_status = user.status.value
    new_status = UserStatus(request.status)
    # Update status

    if new_status == UserStatus.ACTIVE:
        user.activate()
    elif new_status == UserStatus.INACTIVE:
        user.deactivate()
    elif new_status == UserStatus.DEFAULTING:
        user.mark_as_defaulting()

    await user_repo.save(user)

    # Create audit log
    audit = AuditLog.create(
        action=AuditAction.USER_STATUS_CHANGED,
        actor_id=current_admin.id,
        target_id=user.id,
        target_type="user",
        details={
            "old_status": old_status,
            "new_status": new_status.value,
        },
    )
    await audit_repo.save(audit)

    return UserResponse(
        id=str(user.id),
        cpf=user.cpf.formatted if user.cpf else None,
        email=user.email.value,
        name=user.name,
        role=user.role.value,
        status=user.status.value,
        phone=user.phone,
        created_at=user.created_at,
    )


@router.get(
    "/withdrawals/pending",
    response_model=TransactionListResponse,
    summary="Get pending withdrawals",
)
async def get_pending_withdrawals(
    session: DbSession,
    current_admin: CurrentAdmin,
) -> TransactionListResponse:
    """Get all pending withdrawal requests.

    Admin only endpoint.
    """
    from app.domain.entities.transaction import TransactionStatus, TransactionType

    transaction_repo = TransactionRepository(session)

    # Manual query for all pending withdrawals
    from sqlalchemy import select
    from app.infrastructure.db.models import TransactionModel

    result = await session.execute(
        select(TransactionModel)
        .where(TransactionModel.transaction_type == TransactionType.WITHDRAWAL.value)
        .where(TransactionModel.status == TransactionStatus.PENDING.value)
        .order_by(TransactionModel.created_at.desc())
    )
    models = result.scalars().all()

    return TransactionListResponse(
        transactions=[
            TransactionResponse(
                id=str(m.id),
                user_id=str(m.user_id),
                contract_id=str(m.contract_id) if m.contract_id else None,
                transaction_type=m.transaction_type,
                status=m.status,
                amount_cents=m.amount_cents,
                installment_number=m.installment_number,
                installment_type=m.installment_type,
                pix_key=m.pix_key,
                pix_transaction_id=m.pix_transaction_id,
                bank_account=m.bank_account,
                description=m.description,
                created_at=m.created_at,
                confirmed_at=m.confirmed_at,
            )
            for m in models
        ],
        total=len(models),
    )


@router.post(
    "/withdrawals/approve",
    response_model=TransactionResponse,
    summary="Approve a withdrawal",
)
async def approve_withdrawal(
    request: ApproveWithdrawalRequest,
    session: DbSession,
    current_admin: CurrentAdmin,
) -> TransactionResponse:
    """Approve a pending withdrawal request.

    Admin only endpoint. Creates audit log.
    """
    service = WithdrawalService(session)

    try:
        input_data = ApproveWithdrawalInput(
            transaction_id=UUID(request.transaction_id),
            admin_id=current_admin.id,
        )
        result = await service.approve_withdrawal(input_data)

        return TransactionResponse(
            id=str(result.id),
            user_id=str(result.user_id),
            contract_id=str(result.contract_id) if result.contract_id else None,
            transaction_type=result.transaction_type,
            status=result.status,
            amount_cents=result.amount_cents,
            installment_number=result.installment_number,
            installment_type=result.installment_type,
            pix_key=result.pix_key,
            pix_transaction_id=result.pix_transaction_id,
            bank_account=result.bank_account,
            description=result.description,
            created_at=result.created_at,
            confirmed_at=result.confirmed_at,
        )
    except TransactionNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=e.message,
        )
    except InvalidWithdrawalError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=e.message,
        )


@router.post(
    "/withdrawals/reject",
    response_model=TransactionResponse,
    summary="Reject a withdrawal",
)
async def reject_withdrawal(
    request: RejectWithdrawalRequest,
    session: DbSession,
    current_admin: CurrentAdmin,
) -> TransactionResponse:
    """Reject a pending withdrawal request.

    Admin only endpoint. Creates audit log.
    """
    service = WithdrawalService(session)

    try:
        result = await service.reject_withdrawal(
            transaction_id=UUID(request.transaction_id),
            admin_id=current_admin.id,
            reason=request.reason,
        )

        return TransactionResponse(
            id=str(result.id),
            user_id=str(result.user_id),
            contract_id=str(result.contract_id) if result.contract_id else None,
            transaction_type=result.transaction_type,
            status=result.status,
            amount_cents=result.amount_cents,
            installment_number=result.installment_number,
            installment_type=result.installment_type,
            pix_key=result.pix_key,
            pix_transaction_id=result.pix_transaction_id,
            bank_account=result.bank_account,
            description=result.description,
            created_at=result.created_at,
            confirmed_at=result.confirmed_at,
        )
    except TransactionNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=e.message,
        )
    except InvalidWithdrawalError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=e.message,
        )


@router.post(
    "/installment-payments/{payment_id}/confirm",
    status_code=status.HTTP_200_OK,
    summary="Manually confirm an installment payment (testing)",
)
async def admin_confirm_installment_payment(
    payment_id: str,
    session: DbSession,
    current_admin: CurrentAdmin,
) -> dict:
    """Manually confirm an installment payment.

    Admin-only endpoint for testing purposes. Simulates a successful
    Pix confirmation without going through the payment gateway.
    """
    from app.domain.exceptions import InvalidPaymentError, PaymentNotFoundError

    service = InstallmentPaymentService(session)

    try:
        pix_tx_id = f"admin-manual-{payment_id[:8]}"
        result = await service.confirm_payment(
            payment_id=UUID(payment_id),
            pix_transaction_id=pix_tx_id,
        )
        return {
            "status": "confirmed",
            "payment_id": str(result.id),
            "total_amount_cents": result.total_amount_cents,
            "items_count": len(result.items),
        }
    except PaymentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Payment {payment_id} not found",
        )
    except InvalidPaymentError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=e.message,
        )


@router.post(
    "/webhooks/pix",
    status_code=status.HTTP_200_OK,
    summary="Pix payment webhook",
)
async def pix_webhook(
    payload: PixWebhookPayload,
    session: DbSession,
) -> dict:
    """Handle Pix payment webhook from gateway.

    Reconciles incoming payments with pending transactions
    and installment payments.
    """
    transaction_repo = TransactionRepository(session)
    installment_payment_repo = InstallmentPaymentRepository(session)

    # 1. Try legacy transaction reconciliation
    transaction = await transaction_repo.get_by_pix_transaction_id(payload.pix_id)

    if transaction:
        if payload.status == "confirmed":
            service = CreateDepositService(session)
            await service.confirm_deposit(
                transaction_id=transaction.id,
                pix_transaction_id=payload.pix_id,
            )
            return {"status": "confirmed", "transaction_id": str(transaction.id)}
        elif payload.status == "failed":
            transaction.fail()
            await transaction_repo.save(transaction)
            return {"status": "failed", "transaction_id": str(transaction.id)}
        return {"status": "ignored", "pix_status": payload.status}

    # 2. Try installment payment reconciliation
    installment_payment = await installment_payment_repo.get_by_pix_transaction_id(
        payload.pix_id
    )

    if installment_payment:
        if payload.status == "confirmed":
            service = InstallmentPaymentService(session)
            await service.confirm_payment(
                payment_id=installment_payment.id,
                pix_transaction_id=payload.pix_id,
            )
            return {
                "status": "confirmed",
                "installment_payment_id": str(installment_payment.id),
            }
        elif payload.status == "failed":
            installment_payment.fail()
            await installment_payment_repo.save(installment_payment)
            await session.commit()
            return {
                "status": "failed",
                "installment_payment_id": str(installment_payment.id),
            }
        return {"status": "ignored", "pix_status": payload.status}

    # 3. Unknown payment
    return {"status": "unknown_transaction", "pix_id": payload.pix_id}


@router.get(
    "/reports/cash-flow",
    summary="Download cash flow report",
)
async def download_cash_flow_report(
    session: DbSession,
    current_admin: CurrentAdmin,
    start_date: str = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: str = Query(..., description="End date (YYYY-MM-DD)"),
) -> StreamingResponse:
    """Generate and download cash flow Excel report.

    Admin only endpoint.
    """
    from sqlalchemy import select
    from app.infrastructure.db.models import TransactionModel, UserModel

    # Parse dates
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59)

    # Query transactions with user info
    result = await session.execute(
        select(TransactionModel, UserModel.name)
        .join(UserModel, TransactionModel.user_id == UserModel.id)
        .where(TransactionModel.created_at >= start)
        .where(TransactionModel.created_at <= end)
        .order_by(TransactionModel.created_at.desc())
    )
    rows = result.all()

    # Format for report
    transactions = [
        {
            "date": t.created_at,
            "type": t.transaction_type,
            "user_name": name,
            "description": t.description or "",
            "amount": t.amount_cents,
            "status": t.status,
        }
        for t, name in rows
    ]

    # Generate Excel
    generator = ExcelReportGenerator()
    buffer = generator.generate_cash_flow_report(transactions, start, end)

    filename = f"fluxo_caixa_{start_date}_{end_date}.xlsx"
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get(
    "/reports/reconciliation",
    summary="Download reconciliation report",
)
async def download_reconciliation_report(
    session: DbSession,
    current_admin: CurrentAdmin,
) -> StreamingResponse:
    """Generate and download reconciliation Excel report.

    Admin only endpoint.
    """
    from sqlalchemy import select
    from app.domain.entities.transaction import TransactionType
    from app.infrastructure.db.models import TransactionModel, UserModel

    # Query deposit transactions with user info
    result = await session.execute(
        select(TransactionModel, UserModel.name)
        .join(UserModel, TransactionModel.user_id == UserModel.id)
        .where(TransactionModel.transaction_type == TransactionType.DEPOSIT.value)
        .order_by(TransactionModel.created_at.desc())
        .limit(500)
    )
    rows = result.all()

    # Format for reconciliation report
    transactions = []
    for t, name in rows:
        reconciliation_status = "conciliado" if t.pix_transaction_id else "pendente"
        if t.status == "confirmed" and not t.pix_transaction_id:
            reconciliation_status = "divergente"

        transactions.append({
            "transaction_id": t.id,
            "pix_transaction_id": t.pix_transaction_id,
            "date": t.created_at,
            "user_name": name,
            "expected_amount": t.amount_cents,
            "received_amount": t.amount_cents if t.status == "confirmed" else None,
            "reconciliation_status": reconciliation_status,
            "notes": "",
        })

    # Generate Excel
    generator = ExcelReportGenerator()
    buffer = generator.generate_reconciliation_report(transactions)

    filename = f"conciliacao_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ============================================================================
# Plan Management Endpoints (Admin Only)
# ============================================================================


@router.get(
    "/plans",
    response_model=PlanListResponse,
    summary="List all plans",
)
async def list_plans(
    session: DbSession,
    current_admin: CurrentAdmin,
    search: str | None = Query(None, max_length=100, description="Search by plan title"),
) -> PlanListResponse:
    """List all plans with optional title search.

    Admin only endpoint.
    """
    service = PlanService(session)
    plans = await service.list_plans(title_search=search)

    return PlanListResponse(
        plans=[
            PlanResponse(
                id=str(p.id),
                title=p.title,
                description=p.description,
                min_value_cents=p.min_value_cents,
                max_value_cents=p.max_value_cents,
                min_duration_months=p.min_duration_months,
                max_duration_months=p.max_duration_months,
                admin_tax_value_cents=p.admin_tax_value_cents,
                insurance_percent=p.insurance_percent,
                guarantee_fund_percent_1=p.guarantee_fund_percent_1,
                guarantee_fund_percent_2=p.guarantee_fund_percent_2,
                guarantee_fund_threshold_cents=p.guarantee_fund_threshold_cents,
                active=p.active,
            )
            for p in plans
        ],
        total=len(plans),
    )

@router.get(
        "/plans/summary",
    response_model=List[PlanSummaryResponse],
        summary="List plans summary",
)
async def list_plans_summary(
    session: DbSession,
    current_admin: CurrentAdmin,
) -> List[PlanSummaryResponse]:
    """List all plans with their IDs, titles, and active state.

    Admin only endpoint.
    """
    service = PlanService(session)
    plans = await service.list_plans()

    return [
        PlanSummaryResponse(
            id=str(p.id),
            title=p.title,
            active=p.active,
        )
        for p in plans
    ]


@router.post(
    "/plans",
    response_model=PlanResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new plan",
)
async def create_plan(
    request: CreatePlanRequest,
    session: DbSession,
    current_admin: CurrentAdmin,
) -> PlanResponse:
    """Create a new plan.

    Admin only endpoint. Creates audit log.
    """
    service = PlanService(session)

    try:
        input_data = CreatePlanInput(
            title=request.title,
            description=request.description,
            min_value_cents=request.min_value_cents,
            max_value_cents=request.max_value_cents,
            min_duration_months=request.min_duration_months,
            max_duration_months=request.max_duration_months,
            admin_tax_value_cents=request.admin_tax_value_cents,
            insurance_percent=request.insurance_percent,
            guarantee_fund_percent_1=request.guarantee_fund_percent_1,
            guarantee_fund_percent_2=request.guarantee_fund_percent_2,
            guarantee_fund_threshold_cents=request.guarantee_fund_threshold_cents,
            active=request.active,
        )
        result = await service.create_plan(input_data, admin_id=current_admin.id)

        return PlanResponse(
            id=str(result.id),
            title=result.title,
            description=result.description,
            min_value_cents=result.min_value_cents,
            max_value_cents=result.max_value_cents,
            min_duration_months=result.min_duration_months,
            max_duration_months=result.max_duration_months,
            admin_tax_value_cents=result.admin_tax_value_cents,
            insurance_percent=result.insurance_percent,
            guarantee_fund_percent_1=result.guarantee_fund_percent_1,
            guarantee_fund_percent_2=result.guarantee_fund_percent_2,
            guarantee_fund_threshold_cents=result.guarantee_fund_threshold_cents,
            active=result.active,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.put(
    "/plans/{plan_id}",
    response_model=PlanResponse,
    summary="Update a plan",
)
async def update_plan(
    plan_id: str,
    request: UpdatePlanRequest,
    session: DbSession,
    current_admin: CurrentAdmin,
) -> PlanResponse:
    """Update an existing plan.

    This does NOT affect existing contracts.
    Admin only endpoint. Creates audit log.
    """
    service = PlanService(session)

    try:
        input_data = UpdatePlanInput(
            plan_id=UUID(plan_id),
            title=request.title,
            active=request.active,
            description=request.description,
            min_value_cents=request.min_value_cents,
            max_value_cents=request.max_value_cents,
            min_duration_months=request.min_duration_months,
            max_duration_months=request.max_duration_months,
            admin_tax_value_cents=request.admin_tax_value_cents,
            insurance_percent=request.insurance_percent,
            guarantee_fund_percent_1=request.guarantee_fund_percent_1,
            guarantee_fund_percent_2=request.guarantee_fund_percent_2,
            guarantee_fund_threshold_cents=request.guarantee_fund_threshold_cents,
        )
        result = await service.update_plan(input_data, admin_id=current_admin.id)

        return PlanResponse(
            id=str(result.id),
            title=result.title,
            description=result.description,
            min_value_cents=result.min_value_cents,
            max_value_cents=result.max_value_cents,
            min_duration_months=result.min_duration_months,
            max_duration_months=result.max_duration_months,
            admin_tax_value_cents=result.admin_tax_value_cents,
            insurance_percent=result.insurance_percent,
            guarantee_fund_percent_1=result.guarantee_fund_percent_1,
            guarantee_fund_percent_2=result.guarantee_fund_percent_2,
            guarantee_fund_threshold_cents=result.guarantee_fund_threshold_cents,
            active=result.active,
        )
    except PlanNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plan not found",
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )