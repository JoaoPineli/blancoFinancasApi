"""Admin endpoints for platform administration."""

import hashlib
import hmac as _hmac
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from io import BytesIO
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from app.api.v1.dependencies import CurrentAdmin, DbSession
from app.api.v1.schemas.user import (
    AdminClientListResponse,
    AdminClientResponse,
    AdminClientStats,
    UserListResponse,
    UserResponse,
    UserStatusRequest,
)
from app.api.v1.schemas.finance import (
    AdminCashFlowEntryResponse,
    AdminCashFlowListResponse,
    AdminFinanceSummaryResponse,
    AdminReconciliationSummaryResponse,
    AdminWithdrawalListResponse,
    AdminWithdrawalResponse,
    ApproveWithdrawalRequest,
    MercadoPagoWebhookPayload,
    NotificationListResponse,
    NotificationResponse,
    PixWebhookPayload,
    ProcessYieldsRequest,
    ProcessYieldsResponse,
    RejectWithdrawalRequest,
    TransactionListResponse,
    TransactionResponse,
    UnreadCountResponse,
)
from app.api.v1.schemas.plan import (
    CreatePlanRequest,
    PlanListResponse,
    PlanResponse,
    PlanSummaryResponse,
    UpdatePlanRequest,
)
from app.application.dtos.finance import ApproveWithdrawalInput
from app.application.dtos.plan import CreatePlanInput, UpdatePlanInput
from app.application.services.deposit_service import CreateDepositService
from app.application.services.installment_payment_service import InstallmentPaymentService
from app.application.services.notification_service import NotificationService
from app.application.services.plan_service import PlanService
from app.application.services.withdrawal_service import WithdrawalService
from app.application.services.yield_service import YieldService
from app.domain.entities.audit_log import AuditAction, AuditLog
from app.domain.entities.transaction import TransactionStatus, TransactionType
from app.domain.entities.user import UserRole, UserStatus
from app.domain.exceptions import (
    AuthorizationError,
    InvalidWithdrawalError,
    PlanNotFoundError,
    TransactionNotFoundError,
    UserNotFoundError,
)
from app.infrastructure.bcb.exceptions import BCBUnavailableError
from app.infrastructure.db.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.db.repositories.transaction_repository import TransactionRepository
from app.infrastructure.db.repositories.user_repository import UserRepository
from app.infrastructure.exports.csv_generator import CsvReportGenerator
from app.infrastructure.exports.excel_generator import ExcelReportGenerator
from app.infrastructure.exports.pdf_report_generator import PdfReportGenerator

router = APIRouter()


@router.get(
    "/clients",
    response_model=AdminClientListResponse,
    summary="List clients with pagination, search and stats",
)
async def list_clients(
    session: DbSession,
    current_admin: CurrentAdmin,
    status_filter: str | None = Query(
        None, pattern="^(active|inactive|defaulting|registered)$"
    ),
    q: str | None = Query(None, max_length=200, description="Search by name, email or CPF"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> AdminClientListResponse:
    """List clients (role=client only) with pagination, search and real stats.

    total_invested_cents comes from wallet.total_invested_cents (0 if no wallet).
    stats counts are always for all clients regardless of current filter.
    Admin only.
    """
    from sqlalchemy import func, or_, select
    from app.infrastructure.db.models import UserModel, WalletModel

    def _apply_filters(query, *, include_role: bool = True):
        if include_role:
            query = query.where(UserModel.role == UserRole.CLIENT.value)
        if status_filter:
            query = query.where(UserModel.status == status_filter)
        if q and q.strip():
            q_like = f"%{q.strip().lower()}%"
            q_digits = "".join(c for c in q if c.isdigit())
            cpf_cond = UserModel.cpf.like(f"%{q_digits}%") if q_digits else None
            text_cond = or_(
                func.lower(UserModel.name).like(q_like),
                func.lower(UserModel.email).like(q_like),
            )
            query = query.where(or_(text_cond, cpf_cond) if cpf_cond is not None else text_cond)
        return query

    # Total count matching filter
    count_result = await session.execute(
        _apply_filters(select(func.count(UserModel.id)))
    )
    total = count_result.scalar() or 0

    # Per-status stats (all clients, ignoring search/status filter)
    stats_result = await session.execute(
        select(UserModel.status, func.count(UserModel.id))
        .where(UserModel.role == UserRole.CLIENT.value)
        .group_by(UserModel.status)
    )
    stats_map: dict[str, int] = {row[0]: row[1] for row in stats_result.all()}

    # Paginated rows with wallet join
    offset = (page - 1) * page_size
    rows_result = await session.execute(
        _apply_filters(
            select(
                UserModel,
                func.coalesce(WalletModel.total_invested_cents, 0).label("total_invested"),
            ).outerjoin(WalletModel, WalletModel.user_id == UserModel.id)
        )
        .order_by(UserModel.created_at.desc())
        .limit(page_size)
        .offset(offset)
    )
    rows = rows_result.all()

    return AdminClientListResponse(
        clients=[
            AdminClientResponse(
                id=str(user.id),
                name=user.name,
                email=user.email,
                cpf=user.cpf,
                status=user.status,
                phone=user.phone,
                created_at=user.created_at,
                total_invested_cents=int(total_invested),
            )
            for user, total_invested in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
        stats=AdminClientStats(
            active=stats_map.get("active", 0),
            inactive=stats_map.get("inactive", 0),
            defaulting=stats_map.get("defaulting", 0),
            registered=stats_map.get("registered", 0),
            total=sum(stats_map.values()),
        ),
    )


@router.get(
    "/users",
    response_model=UserListResponse,
    summary="List all users",
)
async def list_users(
    session: DbSession,
    current_admin: CurrentAdmin,
    status_filter: str | None = Query(None, pattern="^(active|inactive|defaulting|registered)$"),
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
    if not user.role == UserRole.CLIENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot change status of non-client users",
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


@router.get(
    "/withdrawals",
    response_model=AdminWithdrawalListResponse,
    summary="List all withdrawals",
)
async def list_all_withdrawals(
    session: DbSession,
    current_admin: CurrentAdmin,
    status_filter: str | None = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> AdminWithdrawalListResponse:
    """List all withdrawal transactions with client name enrichment.

    Admin only endpoint.
    """
    from sqlalchemy import select
    from app.infrastructure.db.models import TransactionModel, UserModel
    from app.domain.entities.transaction import TransactionType

    query = (
        select(TransactionModel, UserModel.name)
        .join(UserModel, TransactionModel.user_id == UserModel.id)
        .where(TransactionModel.transaction_type == TransactionType.WITHDRAWAL.value)
        .order_by(TransactionModel.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if status_filter:
        query = query.where(TransactionModel.status == status_filter)

    result = await session.execute(query)
    rows = result.all()

    return AdminWithdrawalListResponse(
        withdrawals=[
            AdminWithdrawalResponse(
                id=str(m.id),
                user_id=str(m.user_id),
                user_name=user_name,
                owner_name=m.bank_account,
                pix_key=m.pix_key,
                pix_key_type=m.pix_key_type,
                amount_cents=m.amount_cents,
                status=m.status,
                rejection_reason=m.rejection_reason,
                description=m.description,
                created_at=m.created_at,
                confirmed_at=m.confirmed_at,
            )
            for m, user_name in rows
        ],
        total=len(rows),
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
    "/activation-payments/{payment_id}/confirm",
    status_code=status.HTTP_200_OK,
    summary="Manually confirm a subscription activation payment (testing)",
)
async def admin_confirm_activation_payment(
    payment_id: str,
    session: DbSession,
    current_admin: CurrentAdmin,
) -> dict:
    """Manually confirm a subscription activation payment.

    Admin-only endpoint for testing purposes. Simulates a successful
    Pix confirmation for an activation payment, activating the subscription.
    """
    from app.application.services.subscription_activation_payment_service import (
        SubscriptionActivationPaymentService,
    )
    from app.domain.exceptions import PaymentNotFoundError

    service = SubscriptionActivationPaymentService(session)

    try:
        pix_tx_id = f"admin-manual-{payment_id[:8]}"
        result = await service.confirm_payment(
            payment_id=UUID(payment_id),
            pix_transaction_id=pix_tx_id,
        )
        return {
            "status": result.status,
            "payment_id": str(result.id),
            "subscription_id": str(result.subscription_id),
            "total_amount_cents": result.total_amount_cents,
        }
    except PaymentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Activation payment {payment_id} not found",
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

    All payment types — legacy DEPOSIT, SUBSCRIPTION_INSTALLMENT_PAYMENT, and
    SUBSCRIPTION_ACTIVATION_PAYMENT — are unified under the transactions table.
    Dispatch is determined by transaction_type.
    """
    from app.application.services.subscription_activation_payment_service import (
        SubscriptionActivationPaymentService,
    )

    transaction_repo = TransactionRepository(session)
    transaction = await transaction_repo.get_by_pix_transaction_id(payload.pix_id)

    if not transaction:
        return {"status": "unknown_transaction", "pix_id": payload.pix_id}

    tx_type = transaction.transaction_type

    # --- Legacy contract deposit flow ---
    if tx_type == TransactionType.DEPOSIT:
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
            await session.commit()
            return {"status": "failed", "transaction_id": str(transaction.id)}
        return {"status": "ignored", "pix_status": payload.status}

    # --- Subscription installment payment ---
    if tx_type == TransactionType.SUBSCRIPTION_INSTALLMENT_PAYMENT:
        if payload.status == "confirmed":
            service = InstallmentPaymentService(session)
            await service.confirm_payment(
                payment_id=transaction.id,
                pix_transaction_id=payload.pix_id,
            )
            return {"status": "confirmed", "transaction_id": str(transaction.id)}
        elif payload.status == "failed":
            transaction.fail()
            await transaction_repo.save(transaction)
            await session.commit()
            return {"status": "failed", "transaction_id": str(transaction.id)}
        return {"status": "ignored", "pix_status": payload.status}

    # --- Subscription activation payment ---
    if tx_type == TransactionType.SUBSCRIPTION_ACTIVATION_PAYMENT:
        if payload.status == "confirmed":
            activation_service = SubscriptionActivationPaymentService(session)
            await activation_service.confirm_payment(
                payment_id=transaction.id,
                pix_transaction_id=payload.pix_id,
            )
            return {"status": "confirmed", "transaction_id": str(transaction.id)}
        elif payload.status == "failed":
            transaction.fail()
            await transaction_repo.save(transaction)
            await session.commit()
            return {"status": "failed", "transaction_id": str(transaction.id)}
        return {"status": "ignored", "pix_status": payload.status}

    return {"status": "ignored", "pix_status": payload.status, "transaction_type": tx_type.value}


@router.post(
    "/webhooks/mercadopago",
    status_code=status.HTTP_200_OK,
    summary="Mercado Pago webhook (signature-validated, GET order for reconciliation)",
)
async def mercadopago_webhook(
    request: Request,
    session: DbSession,
    _body: MercadoPagoWebhookPayload,  # noqa: ARG001 — parsed for OpenAPI docs only
    data_id: Optional[str] = Query(None, alias="data.id"),
    type_param: Optional[str] = Query(None, alias="type"),  # noqa: ARG001
) -> dict:
    """Handle Mercado Pago payment webhook.

    Security flow:
      1. Validate x-signature HMAC-SHA256 with timestamp tolerance.
      2. GET /v1/orders/{id} to verify status (never trust body alone).
      3. Reconcile: pix_transaction_id lookup first, then external_reference fallback.
      4. Validate amount (Decimal, no float).
      5. Dispatch by transaction_type (idempotent).
    """
    import httpx as _httpx
    from app.infrastructure.config import get_settings
    from app.infrastructure.payment.pix_gateway import PixGatewayAdapter

    cfg = get_settings()

    # ---- 1. Signature validation ----------------------------------------
    x_signature = request.headers.get("x-signature", "")
    x_request_id = request.headers.get("x-request-id", "")

    if not x_signature or not data_id:
        raise HTTPException(status_code=401, detail="Missing x-signature or data.id")

    ts = ""
    v1_hash = ""
    for part in x_signature.split(","):
        k, _, v = part.strip().partition("=")
        if k == "ts":
            ts = v
        elif k == "v1":
            v1_hash = v

    if not ts or not v1_hash:
        raise HTTPException(status_code=401, detail="Malformed x-signature header")

    try:
        ts_seconds = int(ts)
        now_seconds = datetime.now(timezone.utc).timestamp()
        if abs(now_seconds - ts_seconds) > cfg.mercadopago_webhook_tolerance_seconds:
            raise HTTPException(status_code=401, detail="Webhook timestamp out of tolerance")
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid ts in x-signature")

    manifest = f"id:{data_id};request-id:{x_request_id};ts:{ts};"
    secret = cfg.mercadopago_webhook_secret.get_secret_value()
    expected = _hmac.new(
        secret.encode("utf-8"),
        manifest.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not _hmac.compare_digest(expected, v1_hash):
        if cfg.environment == "development":
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "MP webhook: signature mismatch ignored in development mode "
                "(ngrok may be replacing X-Request-Id). "
                "manifest=%r | expected=%s | received=%s",
                manifest, expected, v1_hash,
            )
        else:
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    # ---- 2. Fetch order from MP ------------------------------------------
    gateway = PixGatewayAdapter()
    try:
        order_data = await gateway.get_order(data_id)
    except _httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            # Order not found on MP (e.g. simulation with fake ID) — acknowledge and stop.
            return {"status": "order_not_found", "order_id": data_id}
        # Other MP API errors: return 200 so MP does not keep retrying this notification.
        return {"status": "mp_api_error", "order_id": data_id, "http_status": exc.response.status_code}
    except Exception:
        # Network / timeout errors: return 200 to avoid infinite MP retries.
        return {"status": "gateway_unavailable", "order_id": data_id}

    order_id = str(order_data.get("id", data_id))
    external_reference = order_data.get("external_reference", "")
    order_status = order_data.get("status", "")

    # ---- 3. Locate transaction -------------------------------------------
    transaction_repo = TransactionRepository(session)
    transaction = await transaction_repo.get_by_pix_transaction_id(order_id)

    if not transaction and external_reference:
        try:
            internal_id = UUID(hex=external_reference)
            transaction = await transaction_repo.get_by_id(internal_id)
        except (ValueError, AttributeError):
            pass

    if not transaction:
        return {"status": "unknown_transaction", "order_id": order_id}

    # Heal: record the MP order_id if found via fallback
    if transaction.pix_transaction_id != order_id:
        transaction.pix_transaction_id = order_id
        await transaction_repo.save(transaction)

    # ---- 4. Amount validation (Decimal, no float) -----------------------
    order_total_str = str(order_data.get("total_amount", "0"))
    try:
        order_amount = Decimal(order_total_str).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        tx_amount = (Decimal(transaction.amount_cents) / Decimal(100)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    except Exception:
        await session.commit()
        return {"status": "invalid_amount", "order_id": order_id}

    if order_amount != tx_amount:
        await session.commit()
        return {
            "status": "amount_mismatch",
            "order_id": order_id,
            "expected": str(tx_amount),
            "received": str(order_amount),
        }

    # ---- 5. Derive action from order/payment status ---------------------
    payments_list = order_data.get("transactions", {}).get("payments", [])
    payment_obj = payments_list[0] if payments_list else {}
    payment_status = payment_obj.get("status", "")

    is_confirmed = order_status == "closed" and payment_status == "processed"
    is_failed = payment_status == "failed"
    is_expired = order_status == "expired"
    is_cancelled = order_status == "canceled"

    tx_type = transaction.transaction_type

    # ---- 6. Dispatch (idempotent) ----------------------------------------
    if is_confirmed:
        if transaction.status == TransactionStatus.CONFIRMED:
            await session.commit()
            return {"status": "already_confirmed", "transaction_id": str(transaction.id)}

        if tx_type == TransactionType.DEPOSIT:
            service = CreateDepositService(session)
            await service.confirm_deposit(
                transaction_id=transaction.id,
                pix_transaction_id=order_id,
            )
        elif tx_type == TransactionType.SUBSCRIPTION_INSTALLMENT_PAYMENT:
            service_inst = InstallmentPaymentService(session)
            await service_inst.confirm_payment(
                payment_id=transaction.id,
                pix_transaction_id=order_id,
            )
        elif tx_type == TransactionType.SUBSCRIPTION_ACTIVATION_PAYMENT:
            from app.application.services.subscription_activation_payment_service import (
                SubscriptionActivationPaymentService,
            )
            svc_act = SubscriptionActivationPaymentService(session)
            await svc_act.confirm_payment(
                payment_id=transaction.id,
                pix_transaction_id=order_id,
            )
        else:
            await session.commit()
            return {"status": "ignored", "transaction_type": tx_type.value}

        return {"status": "confirmed", "transaction_id": str(transaction.id)}

    if is_failed:
        if transaction.status == TransactionStatus.PENDING:
            transaction.fail()
            await transaction_repo.save(transaction)
        await session.commit()
        return {"status": "failed", "transaction_id": str(transaction.id)}

    if is_expired:
        if transaction.status == TransactionStatus.PENDING:
            transaction.expire()
            await transaction_repo.save(transaction)
        await session.commit()
        return {"status": "expired", "transaction_id": str(transaction.id)}

    if is_cancelled:
        if transaction.status == TransactionStatus.PENDING:
            transaction.cancel()
            await transaction_repo.save(transaction)
        await session.commit()
        return {"status": "cancelled", "transaction_id": str(transaction.id)}

    await session.commit()
    return {
        "status": "pending",
        "transaction_id": str(transaction.id),
        "order_status": order_status,
    }


# ============================================================================
# Finance API Endpoints (Admin Only) — JSON responses
# ============================================================================


@router.get(
    "/finance/summary",
    response_model=AdminFinanceSummaryResponse,
    summary="Finance summary for a period",
)
async def get_finance_summary(
    session: DbSession,
    current_admin: CurrentAdmin,
    start_date: str = Query(..., description="Period start (YYYY-MM-DD)"),
    end_date: str = Query(..., description="Period end (YYYY-MM-DD)"),
    category: Optional[str] = Query(None, description="Filter: deposit|withdrawal|yield|fee|fundo_garantidor|activation|installment"),
    flow_type: Optional[str] = Query(None, description="Filter by flow direction (inflow|outflow)"),
) -> AdminFinanceSummaryResponse:
    """Return fundo de proteção total + inflow/outflow/net for the given period.

    All payment data comes from the unified transactions table.
    fundo_garantidor_cents is always the full wallet sum, never filtered.
    """
    from sqlalchemy import func, select
    from app.infrastructure.db.models import TransactionModel, WalletModel

    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59)

    _INFLOW_TYPES = {
        TransactionType.DEPOSIT.value,
        TransactionType.YIELD.value,
        TransactionType.SUBSCRIPTION_INSTALLMENT_PAYMENT.value,
        TransactionType.SUBSCRIPTION_ACTIVATION_PAYMENT.value,
    }
    _OUTFLOW_TYPES = {
        TransactionType.WITHDRAWAL.value,
        TransactionType.FEE.value,
        TransactionType.FUNDO_GARANTIDOR.value,
    }
    _CATEGORY_TO_TYPE = {
        "deposit": TransactionType.DEPOSIT.value,
        "withdrawal": TransactionType.WITHDRAWAL.value,
        "yield": TransactionType.YIELD.value,
        "fee": TransactionType.FEE.value,
        "fundo_garantidor": TransactionType.FUNDO_GARANTIDOR.value,
        "activation": TransactionType.SUBSCRIPTION_ACTIVATION_PAYMENT.value,
        "installment": TransactionType.SUBSCRIPTION_INSTALLMENT_PAYMENT.value,
    }

    # Determine which types to include
    if category and category in _CATEGORY_TO_TYPE:
        applicable_types = {_CATEGORY_TO_TYPE[category]}
    else:
        applicable_types = _INFLOW_TYPES | _OUTFLOW_TYPES

    if flow_type == "inflow":
        applicable_types &= _INFLOW_TYPES
    elif flow_type == "outflow":
        applicable_types &= _OUTFLOW_TYPES

    inflow_types = list(applicable_types & _INFLOW_TYPES)
    outflow_types = list(applicable_types & _OUTFLOW_TYPES)

    # Fundo de proteção — always unfiltered wallet total
    fg_result = await session.execute(
        select(func.coalesce(func.sum(WalletModel.fundo_garantidor_cents), 0))
    )
    fundo_garantidor_cents = int(fg_result.scalar() or 0)

    # Inflow
    if inflow_types:
        r = await session.execute(
            select(func.coalesce(func.sum(TransactionModel.amount_cents), 0))
            .where(TransactionModel.transaction_type.in_(inflow_types))
            .where(TransactionModel.status == TransactionStatus.CONFIRMED.value)
            .where(TransactionModel.confirmed_at >= start)
            .where(TransactionModel.confirmed_at <= end)
        )
        total_inflow_cents = int(r.scalar() or 0)
    else:
        total_inflow_cents = 0

    # Outflow
    if outflow_types:
        r = await session.execute(
            select(func.coalesce(func.sum(TransactionModel.amount_cents), 0))
            .where(TransactionModel.transaction_type.in_(outflow_types))
            .where(TransactionModel.status == TransactionStatus.CONFIRMED.value)
            .where(TransactionModel.confirmed_at >= start)
            .where(TransactionModel.confirmed_at <= end)
        )
        total_outflow_cents = int(r.scalar() or 0)
    else:
        total_outflow_cents = 0

    return AdminFinanceSummaryResponse(
        fundo_garantidor_cents=fundo_garantidor_cents,
        total_inflow_cents=total_inflow_cents,
        total_outflow_cents=total_outflow_cents,
        net_balance_cents=total_inflow_cents - total_outflow_cents,
        period_start=start_date,
        period_end=end_date,
    )


@router.get(
    "/finance/cash-flow",
    response_model=AdminCashFlowListResponse,
    summary="Paginated cash flow entries for a period",
)
async def get_finance_cash_flow(
    session: DbSession,
    current_admin: CurrentAdmin,
    start_date: str = Query(..., description="Period start (YYYY-MM-DD)"),
    end_date: str = Query(..., description="Period end (YYYY-MM-DD)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    category: Optional[str] = Query(None, description="Filter: deposit|withdrawal|yield|fee|fundo_garantidor|activation|installment"),
    flow_type: Optional[str] = Query(None, description="Filter by flow direction (inflow|outflow)"),
) -> AdminCashFlowListResponse:
    """Return paginated confirmed entries for the given period.

    All data comes from the unified transactions table.
    """
    from sqlalchemy import select
    from app.infrastructure.db.models import TransactionModel

    _CATEGORY_LABEL = {
        TransactionType.DEPOSIT.value: "Depósito",
        TransactionType.WITHDRAWAL.value: "Saque",
        TransactionType.YIELD.value: "Rendimento",
        TransactionType.FEE.value: "Taxa",
        TransactionType.FUNDO_GARANTIDOR.value: "Fundo de proteção",
        TransactionType.SUBSCRIPTION_INSTALLMENT_PAYMENT.value: "Depósito",
        TransactionType.SUBSCRIPTION_ACTIVATION_PAYMENT.value: "Taxa de Ativação",
    }
    _INFLOW_TYPES = {
        TransactionType.DEPOSIT.value,
        TransactionType.YIELD.value,
        TransactionType.SUBSCRIPTION_INSTALLMENT_PAYMENT.value,
        TransactionType.SUBSCRIPTION_ACTIVATION_PAYMENT.value,
    }
    _OUTFLOW_TYPES = {
        TransactionType.WITHDRAWAL.value,
        TransactionType.FEE.value,
        TransactionType.FUNDO_GARANTIDOR.value,
    }
    _CATEGORY_TO_TYPE = {
        "deposit": TransactionType.DEPOSIT.value,
        "withdrawal": TransactionType.WITHDRAWAL.value,
        "yield": TransactionType.YIELD.value,
        "fee": TransactionType.FEE.value,
        "fundo_garantidor": TransactionType.FUNDO_GARANTIDOR.value,
        "activation": TransactionType.SUBSCRIPTION_ACTIVATION_PAYMENT.value,
        "installment": TransactionType.SUBSCRIPTION_INSTALLMENT_PAYMENT.value,
    }

    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59)

    if category and category in _CATEGORY_TO_TYPE:
        applicable_types = {_CATEGORY_TO_TYPE[category]}
    else:
        applicable_types = _INFLOW_TYPES | _OUTFLOW_TYPES

    if flow_type == "inflow":
        applicable_types &= _INFLOW_TYPES
    elif flow_type == "outflow":
        applicable_types &= _OUTFLOW_TYPES

    tx_rows = (await session.execute(
        select(TransactionModel)
        .where(TransactionModel.status == TransactionStatus.CONFIRMED.value)
        .where(TransactionModel.confirmed_at >= start)
        .where(TransactionModel.confirmed_at <= end)
        .where(TransactionModel.transaction_type.in_(list(applicable_types)))
        .order_by(TransactionModel.confirmed_at.desc())
    )).scalars().all()

    all_entries = [
        {
            "sort_dt": t.confirmed_at or t.created_at,
            "id": str(t.id),
            "date": (t.confirmed_at or t.created_at).isoformat(),
            "description": (
                t.description
                or _CATEGORY_LABEL.get(t.transaction_type, t.transaction_type)
            ),
            "type": "inflow" if t.transaction_type in _INFLOW_TYPES else "outflow",
            "amount_cents": t.amount_cents,
            "category": _CATEGORY_LABEL.get(t.transaction_type, t.transaction_type),
        }
        for t in tx_rows
    ]

    all_entries.sort(key=lambda e: e["sort_dt"], reverse=True)
    total = len(all_entries)
    page_entries = all_entries[(page - 1) * page_size: page * page_size]

    return AdminCashFlowListResponse(
        entries=[
            AdminCashFlowEntryResponse(
                id=e["id"],
                date=e["date"],
                description=e["description"],
                type=e["type"],
                amount_cents=e["amount_cents"],
                category=e["category"],
            )
            for e in page_entries
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/finance/reconciliation/summary",
    response_model=AdminReconciliationSummaryResponse,
    summary="Reconciliation status counts for deposits",
)
async def get_reconciliation_summary(
    session: DbSession,
    current_admin: CurrentAdmin,
) -> AdminReconciliationSummaryResponse:
    """Return counts of deposit entries grouped by reconciliation status.

    Covers all payment types from the unified transactions table:
    - DEPOSIT (legacy contract flow)
    - SUBSCRIPTION_INSTALLMENT_PAYMENT
    - SUBSCRIPTION_ACTIVATION_PAYMENT

    - conciliado: confirmed with a pix_transaction_id.
    - divergente: confirmed without a pix_transaction_id (manual/system).
    - pendente: not yet confirmed (pending/failed/cancelled/expired).
    """
    from sqlalchemy import select
    from app.infrastructure.db.models import TransactionModel

    payment_types = [
        TransactionType.DEPOSIT.value,
        TransactionType.SUBSCRIPTION_INSTALLMENT_PAYMENT.value,
        TransactionType.SUBSCRIPTION_ACTIVATION_PAYMENT.value,
    ]

    rows = (await session.execute(
        select(TransactionModel.status, TransactionModel.pix_transaction_id)
        .where(TransactionModel.transaction_type.in_(payment_types))
    )).all()

    conciliado = pendente = divergente = 0
    for row_status, pix_tx_id in rows:
        if pix_tx_id and row_status == TransactionStatus.CONFIRMED.value:
            conciliado += 1
        elif row_status == TransactionStatus.CONFIRMED.value:
            divergente += 1
        else:
            pendente += 1

    total = conciliado + pendente + divergente
    return AdminReconciliationSummaryResponse(
        conciliado=conciliado,
        pendente=pendente,
        divergente=divergente,
        total=total,
    )


@router.get(
    "/reports/cash-flow",
    summary="Download cash flow report",
)
async def download_cash_flow_report(
    session: DbSession,
    current_admin: CurrentAdmin,
    start_date: str = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: str = Query(..., description="End date (YYYY-MM-DD)"),
    format: str = Query("xlsx", pattern="^(xlsx|csv|pdf)$", description="Output format"),
) -> StreamingResponse:
    """Generate and download cash flow report (xlsx, csv or pdf).

    Admin only endpoint.
    """
    from sqlalchemy import select
    from app.infrastructure.db.models import TransactionModel, UserModel

    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59)

    result = await session.execute(
        select(TransactionModel, UserModel.name)
        .join(UserModel, TransactionModel.user_id == UserModel.id)
        .where(TransactionModel.created_at >= start)
        .where(TransactionModel.created_at <= end)
        .order_by(TransactionModel.created_at.desc())
    )
    rows = result.all()

    transactions = [
        {
            "date": t.created_at,
            "type": t.transaction_type,
            "client_name": name,
            "description": t.description or "",
            "amount": t.amount_cents,
            "status": t.status,
        }
        for t, name in rows
    ]

    filename_base = f"fluxo_caixa_{start_date}_{end_date}"

    if format == "csv":
        csv_gen = CsvReportGenerator()
        data = csv_gen.generate_cash_flow_report(transactions, start, end)
        return StreamingResponse(
            iter([data]),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename_base}.csv"'},
        )

    if format == "pdf":
        pdf_gen = PdfReportGenerator()
        buffer = pdf_gen.generate_cash_flow_report(transactions, start, end)
        return StreamingResponse(
            buffer,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename_base}.pdf"'},
        )

    # Default: xlsx
    excel_gen = ExcelReportGenerator()
    buffer = excel_gen.generate_cash_flow_report(transactions, start, end)
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename_base}.xlsx"'},
    )


@router.get(
    "/reports/clients",
    summary="Download clients report",
)
async def download_clients_report(
    session: DbSession,
    current_admin: CurrentAdmin,
    start_date: str = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: str = Query(..., description="End date (YYYY-MM-DD)"),
    format: str = Query("xlsx", pattern="^(xlsx|csv)$", description="Output format"),
) -> StreamingResponse:
    """Generate and download clients report (xlsx or csv).

    Includes status, contact info, and wallet totals in centavos (no float).
    Admin only endpoint.
    """
    from sqlalchemy import func, select
    from app.infrastructure.db.models import UserModel, WalletModel

    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59)

    result = await session.execute(
        select(
            UserModel,
            func.coalesce(WalletModel.balance_cents, 0).label("balance_cents"),
            func.coalesce(WalletModel.total_invested_cents, 0).label("total_invested_cents"),
            func.coalesce(WalletModel.total_yield_cents, 0).label("total_yield_cents"),
            func.coalesce(WalletModel.fundo_garantidor_cents, 0).label("fundo_garantidor_cents"),
        )
        .outerjoin(WalletModel, WalletModel.user_id == UserModel.id)
        .where(UserModel.role == UserRole.CLIENT.value)
        .where(UserModel.created_at >= start)
        .where(UserModel.created_at <= end)
        .order_by(UserModel.created_at.desc())
    )
    rows = result.all()

    clients = [
        {
            "name": user.name,
            "email": user.email,
            "cpf": user.cpf or "",
            "phone": user.phone or "",
            "status": user.status,
            "balance_cents": int(balance),
            "total_invested_cents": int(total_invested),
            "total_yield_cents": int(total_yield),
            "fundo_garantidor_cents": int(fundo),
            "created_at": user.created_at.strftime("%d/%m/%Y %H:%M"),
        }
        for user, balance, total_invested, total_yield, fundo in rows
    ]

    filename_base = f"clientes_{start_date}_{end_date}"

    if format == "csv":
        csv_gen = CsvReportGenerator()
        data = csv_gen.generate_clients_report(clients)
        return StreamingResponse(
            iter([data]),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename_base}.csv"'},
        )

    excel_gen = ExcelReportGenerator()
    buffer = excel_gen.generate_clients_report(clients, start, end)
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename_base}.xlsx"'},
    )


@router.get(
    "/reports/transactions",
    summary="Download transactions report",
)
async def download_transactions_report(
    session: DbSession,
    current_admin: CurrentAdmin,
    start_date: str = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: str = Query(..., description="End date (YYYY-MM-DD)"),
    format: str = Query("xlsx", pattern="^(xlsx|csv)$", description="Output format"),
) -> StreamingResponse:
    """Generate and download transactions report (xlsx or csv).

    Includes id, dates, type, status, amount_cents, pix_transaction_id, description.
    Admin only endpoint.
    """
    from sqlalchemy import select
    from app.infrastructure.db.models import TransactionModel, UserModel

    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59)

    result = await session.execute(
        select(TransactionModel, UserModel.name)
        .join(UserModel, TransactionModel.user_id == UserModel.id)
        .where(TransactionModel.created_at >= start)
        .where(TransactionModel.created_at <= end)
        .order_by(TransactionModel.created_at.desc())
    )
    rows = result.all()

    transactions = [
        {
            "id": str(t.id),
            "client_name": name,
            "created_at": t.created_at.strftime("%d/%m/%Y %H:%M"),
            "confirmed_at": t.confirmed_at.strftime("%d/%m/%Y %H:%M") if t.confirmed_at else "",
            "transaction_type": t.transaction_type,
            "status": t.status,
            "amount_cents": t.amount_cents,
            "pix_transaction_id": t.pix_transaction_id or "",
            "description": t.description or "",
        }
        for t, name in rows
    ]

    filename_base = f"transacoes_{start_date}_{end_date}"

    if format == "csv":
        csv_gen = CsvReportGenerator()
        data = csv_gen.generate_transactions_report(transactions)
        return StreamingResponse(
            iter([data]),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename_base}.csv"'},
        )

    excel_gen = ExcelReportGenerator()
    buffer = excel_gen.generate_transactions_report(transactions, start, end)
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename_base}.xlsx"'},
    )


@router.get(
    "/reports/yields",
    summary="Download yields report",
)
async def download_yields_report(
    session: DbSession,
    current_admin: CurrentAdmin,
    start_date: str = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: str = Query(..., description="End date (YYYY-MM-DD)"),
    format: str = Query("xlsx", pattern="^(xlsx|csv)$", description="Output format"),
) -> StreamingResponse:
    """Generate and download yields report (xlsx or csv).

    Based on AuditLog entries with action=YIELD_CREDITED.
    Includes sgs_series_id, yield_period_from/to, effective_rate,
    principal_cents, yield_cents, installment_number, subscription_id,
    principal_deposit_id, created_at and user name.
    Admin only endpoint.
    """
    from sqlalchemy import select
    from app.infrastructure.db.models import AuditLogModel, UserModel

    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59)

    result = await session.execute(
        select(AuditLogModel, UserModel.name)
        .join(UserModel, AuditLogModel.actor_id == UserModel.id)
        .where(AuditLogModel.action == AuditAction.YIELD_CREDITED.value)
        .where(AuditLogModel.created_at >= start)
        .where(AuditLogModel.created_at <= end)
        .order_by(AuditLogModel.created_at.desc())
    )
    rows = result.all()

    yields = [
        {
            "user_name": name,
            "sgs_series_id": audit.details.get("sgs_series_id", ""),
            "yield_period_from": audit.details.get("yield_period_from", ""),
            "yield_period_to": audit.details.get("yield_period_to", ""),
            "effective_rate": audit.details.get("effective_rate", ""),
            "principal_cents": audit.details.get("principal_cents", 0),
            "yield_cents": audit.details.get("yield_cents", 0),
            "installment_number": audit.details.get("installment_number", ""),
            "subscription_id": audit.details.get("subscription_id", ""),
            "principal_deposit_id": audit.details.get("principal_deposit_id", ""),
            "created_at": audit.created_at.strftime("%d/%m/%Y %H:%M"),
        }
        for audit, name in rows
    ]

    filename_base = f"rendimentos_{start_date}_{end_date}"

    if format == "csv":
        csv_gen = CsvReportGenerator()
        data = csv_gen.generate_yields_report(yields)
        return StreamingResponse(
            iter([data]),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename_base}.csv"'},
        )

    excel_gen = ExcelReportGenerator()
    buffer = excel_gen.generate_yields_report(yields, start, end)
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename_base}.xlsx"'},
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


@router.delete(
    "/plans/{plan_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a plan",
)
async def delete_plan(
    plan_id: str,
    session: DbSession,
    current_admin: CurrentAdmin,
) -> None:
    """Soft-delete a plan by marking it as deleted.

    The plan is not removed from the database; it is hidden from listings
    and cannot be subscribed to. Existing subscriptions are unaffected.
    Admin only endpoint. Creates audit log.
    """
    service = PlanService(session)

    try:
        await service.delete_plan(UUID(plan_id), admin_id=current_admin.id)
    except PlanNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plan not found",
        )


# ------------------------------------------------------------------
# Yield processing
# ------------------------------------------------------------------


@router.post(
    "/yield/process",
    response_model=ProcessYieldsResponse,
    summary="Process poupança yields for all principal deposits",
)
async def process_yields(
    session: DbSession,
    current_admin: CurrentAdmin,
    request: ProcessYieldsRequest = ProcessYieldsRequest(),
) -> ProcessYieldsResponse:
    """Trigger poupança yield calculation and crediting for all deposits.

    Idempotent: running twice on the same date credits zero additional yield.
    Intended to be called by an external cron job (e.g., daily at midnight BRT).

    If target_date is omitted, the server uses the current UTC date.

    Workflow:
      1. Finds all PrincipalDeposit records not yet processed through target_date.
      2. Fetches required BCB SGS rate snapshots (fails loud if BCB unreachable).
      3. For each deposit: credits delta yield = yield(deposited_at→target_date)
         minus yield(deposited_at→last_yield_run_date). Commits per-deposit.
      4. Creates YIELD_CREDITED audit log per credited deposit.
      5. Returns summary.
    """
    import datetime as _dt
    from datetime import date as _date, timezone as _tz

    if request.target_date:
        try:
            calculation_date = _date.fromisoformat(request.target_date)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid target_date format: {request.target_date!r}. Expected YYYY-MM-DD.",
            )
    else:
        calculation_date = _dt.datetime.now(_tz.utc).date()

    service = YieldService(session)

    try:
        result = await service.process_all_yields(calculation_date=calculation_date)
    except BCBUnavailableError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"BCB API unavailable: {e.message}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Yield processing failed: {str(e)}",
        )

    # Audit the batch run.
    audit_repo = AuditLogRepository(session)
    batch_audit = AuditLog.create(
        action=AuditAction.YIELD_BATCH_PROCESSED,
        actor_id=current_admin.id,
        details={
            "calculation_date": calculation_date.isoformat(),
            "deposits_evaluated": result.deposits_evaluated,
            "deposits_credited": result.deposits_credited,
            "total_yield_cents": result.total_yield_cents,
        },
    )
    await audit_repo.save(batch_audit)
    await session.commit()

    return ProcessYieldsResponse(
        calculation_date=calculation_date.isoformat(),
        deposits_evaluated=result.deposits_evaluated,
        deposits_credited=result.deposits_credited,
        total_yield_cents=result.total_yield_cents,
    )


# ============================================================================
# Notification Endpoints (Admin Only)
# ============================================================================


@router.get(
    "/notifications",
    response_model=NotificationListResponse,
    summary="List admin notifications",
)
async def list_notifications(
    session: DbSession,
    current_admin: CurrentAdmin,
    unread_only: bool = Query(False, description="Return only unread notifications"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> NotificationListResponse:
    """List notifications for the admin panel.

    Admin only endpoint.
    """
    service = NotificationService(session)
    result = await service.get_all(unread_only=unread_only, limit=limit, offset=offset)

    return NotificationListResponse(
        notifications=[
            NotificationResponse(
                id=str(n.id),
                notification_type=n.notification_type,
                title=n.title,
                message=n.message,
                is_read=n.is_read,
                target_id=str(n.target_id) if n.target_id else None,
                target_type=n.target_type,
                data=n.data,
                created_at=n.created_at,
                read_at=n.read_at,
            )
            for n in result.notifications
        ],
        total=result.total,
        unread_count=result.unread_count,
    )


@router.get(
    "/notifications/unread-count",
    response_model=UnreadCountResponse,
    summary="Get unread notification count",
)
async def get_unread_count(
    session: DbSession,
    current_admin: CurrentAdmin,
) -> UnreadCountResponse:
    """Return the number of unread admin notifications.

    Admin only endpoint.
    """
    service = NotificationService(session)
    count = await service.get_unread_count()
    return UnreadCountResponse(unread_count=count)


@router.patch(
    "/notifications/{notification_id}/read",
    response_model=NotificationResponse,
    summary="Mark notification as read",
)
async def mark_notification_as_read(
    notification_id: str,
    session: DbSession,
    current_admin: CurrentAdmin,
) -> NotificationResponse:
    """Mark a single notification as read.

    Admin only endpoint.
    """
    from app.domain.exceptions import NotificationNotFoundError

    service = NotificationService(session)

    try:
        n = await service.mark_as_read(UUID(notification_id))
        return NotificationResponse(
            id=str(n.id),
            notification_type=n.notification_type,
            title=n.title,
            message=n.message,
            is_read=n.is_read,
            target_id=str(n.target_id) if n.target_id else None,
            target_type=n.target_type,
            data=n.data,
            created_at=n.created_at,
            read_at=n.read_at,
        )
    except NotificationNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=e.message,
        )


@router.post(
    "/notifications/mark-all-read",
    summary="Mark all notifications as read",
)
async def mark_all_notifications_as_read(
    session: DbSession,
    current_admin: CurrentAdmin,
) -> dict:
    """Mark all notifications as read.

    Admin only endpoint.
    """
    service = NotificationService(session)
    count = await service.mark_all_as_read()
    return {"marked_as_read": count}