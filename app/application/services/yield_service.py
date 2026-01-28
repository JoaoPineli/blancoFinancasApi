"""Yield service for calculating and crediting yields."""

from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos.finance import TransactionDTO
from app.domain.entities.audit_log import AuditAction, AuditLog
from app.domain.entities.contract import ContractStatus
from app.domain.entities.transaction import Transaction
from app.domain.entities.yield_data import SGSSeries, YieldData
from app.domain.services.poupanca_yield_calculator import (
    PoupancaYieldCalculator,
    YieldCalculationResult,
)
from app.domain.value_objects.money import Money
from app.infrastructure.bcb.client import BcbClient
from app.infrastructure.db.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.db.repositories.contract_repository import ContractRepository
from app.infrastructure.db.repositories.transaction_repository import TransactionRepository
from app.infrastructure.db.repositories.wallet_repository import WalletRepository
from app.infrastructure.db.repositories.yield_data_repository import YieldDataRepository


class YieldService:
    """Service for yield calculations and crediting.

    Handles:
    - Fetching and storing BCB yield data
    - Calculating yields using stored data (deterministic)
    - Crediting yields to wallets with full audit trail
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize service with database session."""
        self._session = session
        self._yield_data_repo = YieldDataRepository(session)
        self._contract_repo = ContractRepository(session)
        self._wallet_repo = WalletRepository(session)
        self._transaction_repo = TransactionRepository(session)
        self._audit_repo = AuditLogRepository(session)
        self._bcb_client = BcbClient()

    async def fetch_and_store_yield_data(
        self,
        start_date: date,
        end_date: date,
    ) -> list[YieldData]:
        """Fetch yield data from BCB and store locally.

        All BCB yield data used in calculations MUST be persisted locally.

        Args:
            start_date: Start of date range
            end_date: End of date range

        Returns:
            List of stored YieldData entities
        """
        stored_data = []

        # Fetch data for both series if date range spans the cutoff
        cutoff_date = date(2012, 5, 4)

        if start_date < cutoff_date:
            # Fetch pre-2012 data
            pre_end = min(end_date, date(2012, 5, 3))
            pre_data = await self._bcb_client.fetch_yield_data(
                series_id=SGSSeries.PRE_2012,
                start_date=start_date,
                end_date=pre_end,
            )
            for data in pre_data:
                stored = await self._yield_data_repo.save(data)
                stored_data.append(stored)

        if end_date >= cutoff_date:
            # Fetch post-2012 data
            post_start = max(start_date, cutoff_date)
            post_data = await self._bcb_client.fetch_yield_data(
                series_id=SGSSeries.POST_2012,
                start_date=post_start,
                end_date=end_date,
            )
            for data in post_data:
                stored = await self._yield_data_repo.save(data)
                stored_data.append(stored)

        return stored_data

    async def calculate_yield_for_contract(
        self,
        contract_id: UUID,
        calculation_date: date,
    ) -> YieldCalculationResult | None:
        """Calculate yield for a contract.

        Uses stored BCB data for deterministic recalculation.

        Args:
            contract_id: Contract UUID
            calculation_date: Date to calculate yield up to

        Returns:
            YieldCalculationResult or None if no active contract
        """
        # Get contract
        contract = await self._contract_repo.get_by_id(contract_id)
        if not contract or contract.status != ContractStatus.ACTIVE:
            return None

        if not contract.start_date:
            return None

        # Get wallet balance
        wallet = await self._wallet_repo.get_by_user_id(contract.user_id)
        if not wallet or wallet.total_invested_cents == 0:
            return None

        # Determine series based on deposit date
        deposit_date = contract.start_date.date()
        series_id = YieldData.get_series_for_date(deposit_date)

        # Get stored yield data
        yield_data_list = await self._yield_data_repo.get_range(
            series_id=series_id,
            start_date=deposit_date,
            end_date=calculation_date,
        )

        if not yield_data_list:
            return None

        # Create calculator with stored data
        calculator = PoupancaYieldCalculator(yield_data_list)

        # Calculate yield on total invested
        principal = Money.from_cents(wallet.total_invested_cents)
        result = calculator.calculate_yield(
            principal=principal,
            deposit_date=deposit_date,
            calculation_date=calculation_date,
        )

        return result

    async def credit_yield(
        self,
        contract_id: UUID,
        yield_result: YieldCalculationResult,
    ) -> TransactionDTO:
        """Credit calculated yield to wallet.

        Creates transaction with full audit trail including:
        - Source SGS series ID
        - Reference date range
        - Applied effective rate

        Args:
            contract_id: Contract UUID
            yield_result: Calculated yield result

        Returns:
            Created yield TransactionDTO
        """
        # Get contract
        contract = await self._contract_repo.get_by_id(contract_id)
        if not contract:
            raise ValueError(f"Contract not found: {contract_id}")

        # Create yield transaction with audit data in description
        description = (
            f"Rendimento Poupança - "
            f"Série SGS {yield_result.series_id.value} - "
            f"Taxa efetiva: {yield_result.effective_rate:.6%} - "
            f"Período: {yield_result.start_date.strftime('%d/%m/%Y')} a "
            f"{yield_result.end_date.strftime('%d/%m/%Y')}"
        )

        transaction = Transaction.create_yield(
            user_id=contract.user_id,
            contract_id=contract_id,
            amount_cents=yield_result.yield_amount.cents,
            description=description,
        )

        # Save transaction
        saved_transaction = await self._transaction_repo.save(transaction)

        # Credit wallet
        wallet = await self._wallet_repo.get_by_user_id(contract.user_id)
        wallet.credit_yield(yield_result.yield_amount)
        await self._wallet_repo.save(wallet)

        # Create audit log with full audit data (immutable and queryable)
        audit = AuditLog.create(
            action=AuditAction.YIELD_CREDITED,
            actor_id=contract.user_id,  # System action on behalf of client
            target_id=saved_transaction.id,
            target_type="transaction",
            details={
                "contract_id": str(contract_id),
                "sgs_series_id": yield_result.series_id.value,
                "start_date": yield_result.start_date.isoformat(),
                "end_date": yield_result.end_date.isoformat(),
                "effective_rate": str(yield_result.effective_rate),
                "principal_cents": yield_result.principal.cents,
                "yield_cents": yield_result.yield_amount.cents,
                "days_accrued": yield_result.days_accrued,
            },
        )
        await self._audit_repo.save(audit)

        return TransactionDTO(
            id=saved_transaction.id,
            user_id=saved_transaction.user_id,
            contract_id=saved_transaction.contract_id,
            transaction_type=saved_transaction.transaction_type.value,
            status=saved_transaction.status.value,
            amount_cents=saved_transaction.amount_cents,
            installment_number=saved_transaction.installment_number,
            installment_type=None,
            pix_key=saved_transaction.pix_key,
            pix_transaction_id=saved_transaction.pix_transaction_id,
            bank_account=saved_transaction.bank_account,
            description=saved_transaction.description,
            created_at=saved_transaction.created_at,
            confirmed_at=saved_transaction.confirmed_at,
        )
