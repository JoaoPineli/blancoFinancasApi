"""Finance endpoints for deposits and withdrawals."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.api.v1.dependencies import CurrentUser, DbSession
from app.api.v1.schemas.finance import (
    CreateDepositRequest,
    CreateDepositResponse,
    CreateWithdrawalRequest,
    TransactionListResponse,
    TransactionResponse,
    WalletResponse,
)
from app.application.dtos.finance import CreateDepositInput, CreateWithdrawalInput
from app.application.services.deposit_service import CreateDepositService
from app.application.services.withdrawal_service import WithdrawalService
from app.domain.exceptions import ContractNotFoundError, InsufficientBalanceError
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
