"""Deposit service for handling deposit operations."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos.finance import (
    CreateDepositInput,
    CreateDepositResult,
    TransactionDTO,
)
from app.domain.entities.audit_log import AuditAction, AuditLog
from app.domain.entities.transaction import InstallmentType, Transaction
from app.domain.exceptions import ContractNotFoundError
from app.domain.services.installment_calculator import InstallmentCalculator
from app.domain.value_objects.money import Money
from app.infrastructure.db.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.db.repositories.contract_repository import ContractRepository
from app.infrastructure.db.repositories.plan_repository import PlanRepository
from app.infrastructure.db.repositories.transaction_repository import TransactionRepository
from app.infrastructure.db.repositories.user_repository import UserRepository
from app.infrastructure.db.repositories.wallet_repository import WalletRepository
from app.infrastructure.payment.pix_gateway import PixGatewayAdapter


class CreateDepositService:
    """Service for creating deposit transactions."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize service with database session."""
        self._session = session
        self._transaction_repo = TransactionRepository(session)
        self._contract_repo = ContractRepository(session)
        self._plan_repo = PlanRepository(session)
        self._wallet_repo = WalletRepository(session)
        self._audit_repo = AuditLogRepository(session)
        self._user_repo = UserRepository(session)
        self._pix_gateway = PixGatewayAdapter()

    async def create_deposit(self, input_data: CreateDepositInput) -> CreateDepositResult:
        """Create a deposit transaction and generate Pix QR Code.

        Args:
            input_data: Deposit creation data

        Returns:
            CreateDepositResult with Pix QR Code data

        Raises:
            ContractNotFoundError: If contract not found
        """
        # Validate contract
        contract = await self._contract_repo.get_by_id(input_data.contract_id)
        if not contract or contract.user_id != input_data.user_id:
            raise ContractNotFoundError(str(input_data.contract_id))

        # Determine installment type
        installment_type = (
            InstallmentType.FIRST
            if input_data.installment_number == 1
            else InstallmentType.SUBSEQUENT
        )

        # Create deposit transaction
        transaction = Transaction.create_deposit(
            user_id=input_data.user_id,
            contract_id=input_data.contract_id,
            amount_cents=input_data.amount_cents,
            installment_number=input_data.installment_number,
            installment_type=installment_type,
            description=f"Parcela {input_data.installment_number}",
        )

        # Save transaction first to obtain the real UUID
        saved_transaction = await self._transaction_repo.save(transaction)

        # Load payer email for MP order
        user = await self._user_repo.get_by_id(input_data.user_id)
        payer_email = user.email.value if user else "pagador@testuser.com"

        # Generate Pix payment via Mercado Pago
        pix_payload = await self._pix_gateway.create_payment(
            internal_transaction_id=saved_transaction.id,
            amount_cents=input_data.amount_cents,
            description=f"Blanco Financas - Parcela {input_data.installment_number}",
            payer_email=payer_email,
        )

        # Store MP order_id as pix_transaction_id for reconciliation
        saved_transaction.pix_transaction_id = pix_payload.transaction_id
        await self._transaction_repo.save(saved_transaction)

        # Create audit log
        audit = AuditLog.create(
            action=AuditAction.DEPOSIT_CREATED,
            actor_id=input_data.user_id,
            target_id=saved_transaction.id,
            target_type="transaction",
            details={
                "amount_cents": input_data.amount_cents,
                "installment_number": input_data.installment_number,
            },
        )
        await self._audit_repo.save(audit)

        return CreateDepositResult(
            transaction_id=saved_transaction.id,
            pix_qr_code_data=pix_payload.qr_code_data,
            amount_cents=input_data.amount_cents,
            expiration_minutes=pix_payload.expiration_minutes,
        )

    async def confirm_deposit(
        self,
        transaction_id: UUID,
        pix_transaction_id: str,
    ) -> TransactionDTO:
        """Confirm a deposit after Pix payment.

        This method is called when a Pix webhook confirms payment.

        Args:
            transaction_id: Transaction UUID
            pix_transaction_id: Pix transaction ID from gateway

        Returns:
            Updated TransactionDTO
        """
        # Get transaction
        transaction = await self._transaction_repo.get_by_id(transaction_id)
        if not transaction:
            raise ValueError(f"Transaction not found: {transaction_id}")

        # Get contract and plan for calculations
        contract = await self._contract_repo.get_by_id(transaction.contract_id)
        plan = await self._plan_repo.get_by_id(contract.plan_id)

        # Create installment calculator
        calculator = InstallmentCalculator(plan.fundo_garantidor_percentage)

        # Calculate breakdown based on installment type
        amount = Money.from_cents(transaction.amount_cents)

        if transaction.installment_type == InstallmentType.FIRST:
            breakdown = calculator.calculate_first_installment(amount)
            investment_amount = breakdown.investment_amount
            fundo_amount = breakdown.fundo_garantidor_amount
        else:
            breakdown = calculator.calculate_subsequent_installment(amount)
            investment_amount = breakdown.investment_amount
            fundo_amount = breakdown.fundo_garantidor_amount

        # Update wallet
        wallet = await self._wallet_repo.get_by_user_id(transaction.user_id)
        wallet.credit_investment(investment_amount)
        wallet.add_fundo_garantidor(fundo_amount)
        await self._wallet_repo.save(wallet)

        # Create Fundo Garantidor transaction
        fundo_transaction = Transaction.create_fundo_garantidor(
            user_id=transaction.user_id,
            contract_id=transaction.contract_id,
            amount_cents=fundo_amount.cents,
            installment_number=transaction.installment_number,
        )
        await self._transaction_repo.save(fundo_transaction)

        # Confirm the deposit transaction
        transaction.confirm(pix_transaction_id=pix_transaction_id)
        saved_transaction = await self._transaction_repo.save(transaction)

        # Create audit log
        audit = AuditLog.create(
            action=AuditAction.DEPOSIT_CONFIRMED,
            actor_id=transaction.user_id,
            target_id=saved_transaction.id,
            target_type="transaction",
            details={
                "pix_transaction_id": pix_transaction_id,
                "investment_cents": investment_amount.cents,
                "fundo_garantidor_cents": fundo_amount.cents,
            },
        )
        await self._audit_repo.save(audit)

        return self._to_dto(saved_transaction)

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
            pix_transaction_id=transaction.pix_transaction_id,
            bank_account=transaction.bank_account,
            description=transaction.description,
            created_at=transaction.created_at,
            confirmed_at=transaction.confirmed_at,
        )
