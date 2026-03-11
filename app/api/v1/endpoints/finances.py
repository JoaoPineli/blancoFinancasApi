"""Finance endpoints for deposits, withdrawals, and installment payments."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.api.v1.dependencies import CurrentUser, DbSession
from app.api.v1.schemas.finance import (
    CreateDepositRequest,
    CreateDepositResponse,
    CreateInstallmentPaymentRequest,
    CreateWithdrawalRequest,
    HistoryEventResponse,
    HistoryListResponse,
    InstallmentPaymentItemResponse,
    InstallmentPaymentResponse,
    PayableInstallmentResponse,
    PayableInstallmentsListResponse,
    PlanWithdrawalResponse,
    RequestPlanWithdrawalRequest,
    TransactionListResponse,
    TransactionResponse,
    WalletResponse,
    WithdrawableSubscriptionResponse,
    WithdrawableSubscriptionsListResponse,
)
from app.application.dtos.finance import (
    CreateDepositInput,
    CreateInstallmentPaymentInput,
    CreateWithdrawalInput,
    RequestPlanWithdrawalInput,
)
from app.application.services.deposit_service import CreateDepositService
from app.application.services.installment_payment_service import (
    InstallmentPaymentService,
)
from app.application.services.withdrawal_service import WithdrawalService
from app.domain.exceptions import (
    ContractNotFoundError,
    DuplicatePaymentError,
    InsufficientBalanceError,
    InvalidPaymentError,
    PaymentNotFoundError,
    SubscriptionNotFoundError,
)
from app.infrastructure.db.repositories.transaction_repository import TransactionRepository
from app.infrastructure.db.repositories.wallet_repository import WalletRepository
from app.infrastructure.db.repositories.transaction_repository import TransactionRepository
from app.infrastructure.db.repositories.wallet_repository import WalletRepository

router = APIRouter()


@router.get(
    "/wallet",
    response_model=WalletResponse,
    summary="Get user wallet",
)
async def get_wallet(
    session: DbSession,
    current_user: CurrentUser,
) -> WalletResponse:
    """Get the current user's wallet with balance information."""
    wallet_repo = WalletRepository(session)
    wallet = await wallet_repo.get_by_user_id(current_user.id)

    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Wallet not found",
        )

    return WalletResponse(
        id=str(wallet.id),
        user_id=str(wallet.user_id),
        balance_cents=wallet.balance_cents,
        total_invested_cents=wallet.total_invested_cents,
        total_yield_cents=wallet.total_yield_cents,
        fundo_garantidor_cents=wallet.fundo_garantidor_cents,
    )


@router.get(
    "/transactions",
    response_model=TransactionListResponse,
    summary="Get user transactions",
)
async def get_transactions(
    session: DbSession,
    current_user: CurrentUser,
    limit: int = 50,
    offset: int = 0,
) -> TransactionListResponse:
    """Get transactions for the current user."""
    transaction_repo = TransactionRepository(session)
    transactions = await transaction_repo.get_by_user_id(
        user_id=current_user.id,
        limit=limit,
        offset=offset,
    )

    return TransactionListResponse(
        transactions=[
            TransactionResponse(
                id=str(t.id),
                user_id=str(t.user_id),
                contract_id=str(t.contract_id) if t.contract_id else None,
                transaction_type=t.transaction_type.value,
                status=t.status.value,
                amount_cents=t.amount_cents,
                installment_number=t.installment_number,
                installment_type=t.installment_type.value if t.installment_type else None,
                pix_key=t.pix_key,
                pix_transaction_id=t.pix_transaction_id,
                bank_account=t.bank_account,
                description=t.description,
                created_at=t.created_at,
                confirmed_at=t.confirmed_at,
            )
            for t in transactions
        ],
        total=len(transactions),
    )


@router.post(
    "/deposits",
    response_model=CreateDepositResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a deposit",
)
async def create_deposit(
    request: CreateDepositRequest,
    session: DbSession,
    current_user: CurrentUser,
) -> CreateDepositResponse:
    """Create a deposit transaction and get Pix QR Code."""
    service = CreateDepositService(session)

    try:
        input_data = CreateDepositInput(
            user_id=current_user.id,
            contract_id=UUID(request.contract_id),
            amount_cents=request.amount_cents,
            installment_number=request.installment_number,
        )
        result = await service.create_deposit(input_data)

        return CreateDepositResponse(
            transaction_id=str(result.transaction_id),
            pix_qr_code_data=result.pix_qr_code_data,
            amount_cents=result.amount_cents,
            expiration_minutes=result.expiration_minutes,
        )
    except ContractNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=e.message,
        )


@router.post(
    "/withdrawals",
    response_model=TransactionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Request a withdrawal",
)
async def create_withdrawal(
    request: CreateWithdrawalRequest,
    session: DbSession,
    current_user: CurrentUser,
) -> TransactionResponse:
    """Request a withdrawal from the wallet."""
    service = WithdrawalService(session)

    try:
        input_data = CreateWithdrawalInput(
            user_id=current_user.id,
            amount_cents=request.amount_cents,
            bank_account=request.bank_account,
            description=request.description,
        )
        result = await service.create_withdrawal_request(input_data)

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
    except InsufficientBalanceError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=e.message,
        )


# ------------------------------------------------------------------
# Installment Payments
# ------------------------------------------------------------------


@router.get(
    "/payable-installments",
    response_model=PayableInstallmentsListResponse,
    summary="List payable installments",
)
async def list_payable_installments(
    session: DbSession,
    current_user: CurrentUser,
) -> PayableInstallmentsListResponse:
    """List current payable installments for authenticated user.

    Returns one installment per active subscription, ordered by urgency
    (overdue first, then due_today, then upcoming).
    """
    service = InstallmentPaymentService(session)
    result = await service.get_payable_installments(current_user.id)

    return PayableInstallmentsListResponse(
        installments=[
            PayableInstallmentResponse(
                subscription_id=str(i.subscription_id),
                subscription_name=i.subscription_name,
                plan_title=i.plan_title,
                installment_number=i.installment_number,
                total_installments=i.total_installments,
                amount_cents=i.amount_cents,
                due_date=i.due_date,
                is_overdue=i.is_overdue,
                status=i.status,
                pending_payment_id=str(i.pending_payment_id) if i.pending_payment_id else None,
            )
            for i in result.installments
        ],
        total=result.total,
    )


@router.post(
    "/installment-payments",
    response_model=InstallmentPaymentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create installment payment",
)
async def create_installment_payment(
    request: CreateInstallmentPaymentRequest,
    session: DbSession,
    current_user: CurrentUser,
) -> InstallmentPaymentResponse:
    """Create a grouped Pix payment for selected subscription installments.

    The total amount is computed server-side from stored subscription data.
    No free-form amounts are accepted.
    """
    service = InstallmentPaymentService(session)

    try:
        input_data = CreateInstallmentPaymentInput(
            user_id=current_user.id,
            subscription_ids=[UUID(sid) for sid in request.subscription_ids],
        )
        result = await service.create_payment(input_data)

        return _payment_dto_to_response(result)
    except InvalidPaymentError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=e.message,
        )
    except DuplicatePaymentError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=e.message,
        )


@router.get(
    "/installment-payments/{payment_id}",
    response_model=InstallmentPaymentResponse,
    summary="Get installment payment details",
)
async def get_installment_payment(
    payment_id: str,
    session: DbSession,
    current_user: CurrentUser,
) -> InstallmentPaymentResponse:
    """Get details of an installment payment with ownership check."""
    service = InstallmentPaymentService(session)

    try:
        result = await service.get_payment(
            payment_id=UUID(payment_id),
            user_id=current_user.id,
        )
        return _payment_dto_to_response(result)
    except PaymentNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=e.message,
        )


# ------------------------------------------------------------------
# Withdrawable Subscriptions & Plan Withdrawal
# ------------------------------------------------------------------


@router.get(
    "/withdrawable-subscriptions",
    response_model=WithdrawableSubscriptionsListResponse,
    summary="List withdrawable subscriptions",
)
async def list_withdrawable_subscriptions(
    session: DbSession,
    current_user: CurrentUser,
) -> WithdrawableSubscriptionsListResponse:
    """List subscriptions eligible for value withdrawal.

    Includes completed subscriptions and active ones with at least
    one deposit paid (early termination).
    """
    service = InstallmentPaymentService(session)
    result = await service.get_withdrawable_subscriptions(current_user.id)

    return WithdrawableSubscriptionsListResponse(
        subscriptions=[
            WithdrawableSubscriptionResponse(
                subscription_id=str(s.subscription_id),
                subscription_name=s.subscription_name,
                plan_title=s.plan_title,
                status=s.status,
                is_early_termination=s.is_early_termination,
                withdrawable_amount_cents=s.withdrawable_amount_cents,
                deposits_paid=s.deposits_paid,
                deposit_count=s.deposit_count,
                created_at=s.created_at,
            )
            for s in result.subscriptions
        ],
        total=result.total,
    )


@router.post(
    "/plan-withdrawals",
    response_model=PlanWithdrawalResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Request plan withdrawal",
)
async def request_plan_withdrawal(
    request: RequestPlanWithdrawalRequest,
    session: DbSession,
    current_user: CurrentUser,
) -> PlanWithdrawalResponse:
    """Request withdrawal from a subscription with plan closure.

    Active subscriptions will be cancelled (early termination).
    Completed subscriptions remain in completed state.
    """
    service = InstallmentPaymentService(session)

    try:
        input_data = RequestPlanWithdrawalInput(
            user_id=current_user.id,
            subscription_id=UUID(request.subscription_id),
        )
        result = await service.request_plan_withdrawal(input_data)

        return PlanWithdrawalResponse(
            subscription_id=str(result.subscription_id),
            subscription_name=result.subscription_name,
            plan_title=result.plan_title,
            status=result.status,
            amount_cents=result.amount_cents,
            is_early_termination=result.is_early_termination,
            created_at=result.created_at.isoformat(),
        )
    except SubscriptionNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=e.message,
        )
    except InvalidPaymentError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=e.message,
        )


# ------------------------------------------------------------------
# History
# ------------------------------------------------------------------


@router.get(
    "/history",
    response_model=HistoryListResponse,
    summary="Get financial history",
)
async def get_history(
    session: DbSession,
    current_user: CurrentUser,
    limit: int = 50,
    offset: int = 0,
) -> HistoryListResponse:
    """Get unified financial history for the authenticated user.

    Merges installment payments and plan withdrawals into a single
    timeline sorted by date descending.
    """
    service = InstallmentPaymentService(session)
    result = await service.get_user_history(
        user_id=current_user.id,
        limit=limit,
        offset=offset,
    )

    return HistoryListResponse(
        events=[
            HistoryEventResponse(
                id=str(e.id),
                event_type=e.event_type,
                status=e.status,
                amount_cents=e.amount_cents,
                description=e.description,
                plan_titles=e.plan_titles,
                created_at=e.created_at.isoformat(),
                confirmed_at=e.confirmed_at.isoformat() if e.confirmed_at else None,
            )
            for e in result.events
        ],
        total=result.total,
    )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _payment_dto_to_response(dto) -> InstallmentPaymentResponse:
    """Convert InstallmentPaymentDTO to response schema."""
    return InstallmentPaymentResponse(
        id=str(dto.id),
        user_id=str(dto.user_id),
        status=dto.status,
        total_amount_cents=dto.total_amount_cents,
        pix_qr_code_data=dto.pix_qr_code_data,
        pix_transaction_id=dto.pix_transaction_id,
        expiration_minutes=dto.expiration_minutes,
        items=[
            InstallmentPaymentItemResponse(
                id=str(item.id),
                subscription_id=str(item.subscription_id),
                subscription_name=item.subscription_name,
                plan_title=item.plan_title,
                amount_cents=item.amount_cents,
                installment_number=item.installment_number,
            )
            for item in dto.items
        ],
        created_at=dto.created_at.isoformat(),
        updated_at=dto.updated_at.isoformat(),
        confirmed_at=dto.confirmed_at.isoformat() if dto.confirmed_at else None,
    )
