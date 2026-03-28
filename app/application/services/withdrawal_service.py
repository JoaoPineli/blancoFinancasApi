"""Withdrawal service for handling withdrawal operations."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos.finance import (
    ApproveWithdrawalInput,
    CreateWithdrawalInput,
    TransactionDTO,
)
from app.domain.entities.audit_log import AuditAction, AuditLog
from app.domain.entities.transaction import Transaction, TransactionStatus
from app.domain.exceptions import (
    AuthorizationError,
    InsufficientBalanceError,
    InvalidWithdrawalError,
    TransactionNotFoundError,
)
from app.domain.value_objects.money import Money
from app.infrastructure.db.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.db.repositories.subscription_repository import SubscriptionRepository
from app.infrastructure.db.repositories.user_repository import UserRepository
from app.infrastructure.db.repositories.transaction_repository import TransactionRepository
from app.infrastructure.db.repositories.wallet_repository import WalletRepository


class WithdrawalService:
    """Service for withdrawal operations."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize service with database session."""
        self._session = session
        self._transaction_repo = TransactionRepository(session)
        self._wallet_repo = WalletRepository(session)
        self._user_repo = UserRepository(session)
        self._subscription_repo = SubscriptionRepository(session)
        self._audit_repo = AuditLogRepository(session)

    async def create_withdrawal_request(
        self, input_data: CreateWithdrawalInput
    ) -> TransactionDTO:
        """Create a withdrawal request.

        Args:
            input_data: Withdrawal request data

        Returns:
            Created TransactionDTO

        Raises:
            InsufficientBalanceError: If balance is insufficient
        """
        # Get wallet
        wallet = await self._wallet_repo.get_by_user_id(input_data.user_id)
        if not wallet:
            raise InvalidWithdrawalError("Wallet not found")

        # Check balance
        withdrawal_amount = Money.from_cents(input_data.amount_cents)
        if not wallet.can_withdraw(withdrawal_amount):
            raise InsufficientBalanceError(
                requested=str(withdrawal_amount),
                available=str(wallet.balance),
            )

        # Create withdrawal transaction
        transaction = Transaction.create_withdrawal(
            user_id=input_data.user_id,
            amount_cents=input_data.amount_cents,
            bank_account=input_data.bank_account,
            description=input_data.description,
        )

        # Save transaction
        saved_transaction = await self._transaction_repo.save(transaction)

        # Create audit log
        audit = AuditLog.create(
            action=AuditAction.WITHDRAWAL_REQUESTED,
            actor_id=input_data.user_id,
            target_id=saved_transaction.id,
            target_type="transaction",
            details={
                "amount_cents": input_data.amount_cents,
                "bank_account": input_data.bank_account,
            },
        )
        await self._audit_repo.save(audit)

        return self._to_dto(saved_transaction)

    async def approve_withdrawal(
        self, input_data: ApproveWithdrawalInput
    ) -> TransactionDTO:
        """Approve a pending withdrawal request.

        Args:
            input_data: Approval data

        Returns:
            Updated TransactionDTO

        Raises:
            TransactionNotFoundError: If transaction not found
            AuthorizationError: If admin is not authorized
            InvalidWithdrawalError: If transaction is not pending
        """
        # Validate admin authorization
        admin = await self._user_repo.get_by_id(input_data.admin_id)
        if not admin or not admin.is_admin():
            raise AuthorizationError("Only admins can approve withdrawals")

        # Get transaction
        transaction = await self._transaction_repo.get_by_id(input_data.transaction_id)
        if not transaction:
            raise TransactionNotFoundError(str(input_data.transaction_id))

        if transaction.status != TransactionStatus.PENDING:
            raise InvalidWithdrawalError(
                f"Cannot approve transaction in {transaction.status.value} status"
            )

        # Get and update wallet
        wallet = await self._wallet_repo.get_by_user_id(transaction.user_id)
        withdrawal_amount = Money.from_cents(transaction.amount_cents)

        # Debit wallet
        wallet.debit(withdrawal_amount)
        await self._wallet_repo.save(wallet)

        # Confirm transaction
        transaction.confirm()
        saved_transaction = await self._transaction_repo.save(transaction)

        # Create audit log
        audit = AuditLog.create(
            action=AuditAction.WITHDRAWAL_APPROVED,
            actor_id=input_data.admin_id,
            target_id=saved_transaction.id,
            target_type="transaction",
            details={
                "amount_cents": transaction.amount_cents,
                "user_id": str(transaction.user_id),
            },
        )
        await self._audit_repo.save(audit)

        return self._to_dto(saved_transaction)

    async def reject_withdrawal(
        self,
        transaction_id: UUID,
        admin_id: UUID,
        reason: str,
    ) -> TransactionDTO:
        """Reject a pending withdrawal request.

        Args:
            transaction_id: Transaction UUID
            admin_id: Admin UUID
            reason: Rejection reason

        Returns:
            Updated TransactionDTO
        """
        # Validate admin authorization
        admin = await self._user_repo.get_by_id(admin_id)
        if not admin or not admin.is_admin():
            raise AuthorizationError("Only admins can reject withdrawals")

        # Get transaction
        transaction = await self._transaction_repo.get_by_id(transaction_id)
        if not transaction:
            raise TransactionNotFoundError(str(transaction_id))

        if transaction.status != TransactionStatus.PENDING:
            raise InvalidWithdrawalError(
                f"Cannot reject transaction in {transaction.status.value} status"
            )

        # Cancel transaction with reason
        transaction.reject_with_reason(reason)
        saved_transaction = await self._transaction_repo.save(transaction)

        # Reinstate subscription if this was a plan withdrawal
        if transaction.subscription_id:
            sub = await self._subscription_repo.get_by_id(transaction.subscription_id)
            if sub:
                from app.domain.entities.subscription import SubscriptionStatus
                if sub.deposits_paid >= sub.deposit_count:
                    sub.status = SubscriptionStatus.COMPLETED
                else:
                    sub.status = SubscriptionStatus.ACTIVE
                await self._subscription_repo.save(sub)

        # Create audit log
        audit = AuditLog.create(
            action=AuditAction.WITHDRAWAL_REJECTED,
            actor_id=admin_id,
            target_id=saved_transaction.id,
            target_type="transaction",
            details={
                "reason": reason,
                "amount_cents": transaction.amount_cents,
                "user_id": str(transaction.user_id),
            },
        )
        await self._audit_repo.save(audit)

        return self._to_dto(saved_transaction)

    async def get_pending_withdrawals(self) -> list[TransactionDTO]:
        """Get all pending withdrawal requests.

        Returns:
            List of pending TransactionDTO
        """
        from app.domain.entities.transaction import TransactionStatus, TransactionType

        # Get pending withdrawals
        transactions = await self._transaction_repo.get_by_user_id(
            user_id=None,  # Get all
            transaction_type=TransactionType.WITHDRAWAL,
            status=TransactionStatus.PENDING,
        )
        return [self._to_dto(t) for t in transactions]

    async def get_all_withdrawals(
        self,
        status_filter: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[TransactionDTO]:
        """Get all withdrawal transactions for admin listing.

        Args:
            status_filter: Optional status string to filter by
            limit: Max records to return
            offset: Pagination offset

        Returns:
            List of TransactionDTO
        """
        from sqlalchemy import select
        from app.infrastructure.db.models import TransactionModel
        from app.domain.entities.transaction import TransactionType

        query = (
            select(TransactionModel)
            .where(TransactionModel.transaction_type == TransactionType.WITHDRAWAL.value)
            .order_by(TransactionModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if status_filter:
            query = query.where(TransactionModel.status == status_filter)

        result = await self._session.execute(query)
        models = result.scalars().all()

        dtos = []
        for m in models:
            t = self._transaction_repo._to_entity(m)
            # Enrich with user name stored in bank_account (owner_name)
            dtos.append(self._to_dto(t))
        return dtos

    def _to_dto(self, transaction: Transaction) -> TransactionDTO:
        """Convert Transaction entity to DTO."""
        return TransactionDTO(
            id=transaction.id,
            user_id=transaction.user_id,
            contract_id=transaction.contract_id,
            transaction_type=transaction.transaction_type.value,
            status=transaction.status.value,
            amount_cents=transaction.amount_cents,
            installment_number=transaction.installment_number,
            installment_type=transaction.installment_type.value
            if transaction.installment_type
            else None,
            pix_key=transaction.pix_key,
            pix_key_type=transaction.pix_key_type,
            pix_transaction_id=transaction.pix_transaction_id,
            bank_account=transaction.bank_account,
            description=transaction.description,
            rejection_reason=transaction.rejection_reason,
            created_at=transaction.created_at,
            confirmed_at=transaction.confirmed_at,
        )
