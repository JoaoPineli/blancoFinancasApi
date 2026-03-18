"""Yield service for calculating and crediting poupança yields.

Two entry points:
- Legacy:  calculate_yield_for_contract / credit_yield (contract-based flow)
- Current: process_all_yields (subscription/principal-deposit flow)

process_all_yields is the authoritative method for automatic yield crediting.
It is idempotent: running it twice on the same date credits zero additional yield.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import List
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos.finance import TransactionDTO
from app.domain.entities.audit_log import AuditAction, AuditLog
from app.domain.entities.contract import ContractStatus
from app.domain.entities.principal_deposit import PrincipalDeposit
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
from app.infrastructure.db.repositories.principal_deposit_repository import (
    PrincipalDepositRepository,
)
from app.infrastructure.db.repositories.transaction_repository import TransactionRepository
from app.infrastructure.db.repositories.wallet_repository import WalletRepository
from app.infrastructure.db.repositories.yield_data_repository import YieldDataRepository


@dataclass
class ProcessedDepositResult:
    """Result for a single principal deposit's yield processing."""

    principal_deposit_id: UUID
    user_id: UUID
    subscription_id: UUID
    installment_number: int
    principal_cents: int
    deposited_at: date
    yield_credited_cents: int


@dataclass
class ProcessYieldsResult:
    """Summary result of a yield processing run."""

    calculation_date: date
    deposits_evaluated: int
    deposits_credited: int
    total_yield_cents: int
    credited: List[ProcessedDepositResult] = field(default_factory=list)


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
        self._principal_deposit_repo = PrincipalDepositRepository(session)
        self._bcb_client = BcbClient()

    # ------------------------------------------------------------------
    # BCB data management
    # ------------------------------------------------------------------

    async def fetch_and_store_yield_data(
        self,
        start_date: date,
        end_date: date,
    ) -> list[YieldData]:
        """Fetch yield data from BCB and store locally.

        All BCB yield data used in calculations MUST be persisted locally.
        Idempotent: uses merge, safe to call multiple times for overlapping ranges.

        Args:
            start_date: Start of date range
            end_date: End of date range

        Returns:
            List of stored YieldData entities
        """
        stored_data = []

        cutoff_date = date(2012, 5, 4)

        if start_date < cutoff_date:
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

    # ------------------------------------------------------------------
    # Automatic yield processing (subscription flow)
    # ------------------------------------------------------------------

    async def process_all_yields(
        self,
        calculation_date: date,
    ) -> ProcessYieldsResult:
        """Process poupança yields for all principal deposits.

        For each PrincipalDeposit:
          1. Computes total yield from deposited_at → calculation_date.
          2. Computes previously credited yield from deposited_at → last_yield_run_date.
          3. Credits the delta (new complete months only).
          4. Updates last_yield_run_date = calculation_date.

        Idempotency:
          Running twice on the same date: delta = yield(D→T) - yield(D→T) = 0 → no credit.

        BCB data:
          Fetches the full required range from BCB upfront (idempotent).
          Raises if BCB is unavailable (fail loud; no silent fallback).

        Args:
            calculation_date: Reference date for yield calculation (typically today).

        Returns:
            ProcessYieldsResult with summary of what was credited.
        """
        deposits = await self._principal_deposit_repo.get_pending_yield_processing(
            before_date=calculation_date
        )

        result = ProcessYieldsResult(
            calculation_date=calculation_date,
            deposits_evaluated=len(deposits),
            deposits_credited=0,
            total_yield_cents=0,
        )

        if not deposits:
            return result

        # Determine the overall date range needed and pre-fetch BCB data once.
        earliest_date = min(d.deposited_at for d in deposits)
        await self.fetch_and_store_yield_data(
            start_date=earliest_date,
            end_date=calculation_date,
        )
        # Commit BCB snapshot persistence before calculations.
        await self._session.commit()

        for deposit in deposits:
            credited_cents = await self._process_single_deposit(
                deposit=deposit,
                calculation_date=calculation_date,
            )
            if credited_cents > 0:
                result.deposits_credited += 1
                result.total_yield_cents += credited_cents
                result.credited.append(
                    ProcessedDepositResult(
                        principal_deposit_id=deposit.id,
                        user_id=deposit.user_id,
                        subscription_id=deposit.subscription_id,
                        installment_number=deposit.installment_number,
                        principal_cents=deposit.principal_cents,
                        deposited_at=deposit.deposited_at,
                        yield_credited_cents=credited_cents,
                    )
                )

        return result

    async def _process_single_deposit(
        self,
        deposit: PrincipalDeposit,
        calculation_date: date,
    ) -> int:
        """Calculate and credit yield for a single principal deposit.

        Returns the amount credited in cents (0 if nothing to credit).
        Each successful credit is committed atomically.

        Idempotency:
          delta = yield(deposited_at → calculation_date)
                - yield(deposited_at → last_yield_run_date)
          If last_yield_run_date is None, previous yield = 0.
          If calculation_date == last_yield_run_date, delta = 0.
        """
        principal = Money.from_cents(deposit.principal_cents)
        series_id = YieldData.get_series_for_date(deposit.deposited_at)

        # Load persisted yield data for the full range from this deposit.
        yield_data_list = await self._yield_data_repo.get_range(
            series_id=series_id,
            start_date=deposit.deposited_at,
            end_date=calculation_date,
        )
        calculator = PoupancaYieldCalculator(yield_data_list)

        # Total yield from deposit date to calculation_date.
        total_result = calculator.calculate_yield(
            principal=principal,
            deposit_date=deposit.deposited_at,
            calculation_date=calculation_date,
        )

        # Previously credited yield (yield from deposit date to last run date).
        if deposit.last_yield_run_date is not None:
            prev_result = calculator.calculate_yield(
                principal=principal,
                deposit_date=deposit.deposited_at,
                calculation_date=deposit.last_yield_run_date,
            )
            prev_yield_cents = prev_result.yield_amount.cents
        else:
            prev_yield_cents = 0

        delta_cents = total_result.yield_amount.cents - prev_yield_cents

        if delta_cents <= 0:
            # No new complete months — update run date only (mark as evaluated).
            deposit.last_yield_run_date = calculation_date
            await self._principal_deposit_repo.save(deposit)
            await self._session.commit()
            return 0

        delta_yield = Money.from_cents(delta_cents)

        # Build rich description for ledger and audit trail.
        prev_date_str = (
            deposit.last_yield_run_date.isoformat()
            if deposit.last_yield_run_date
            else deposit.deposited_at.isoformat()
        )
        description = (
            f"Rendimento Poupança"
            f" | Série SGS {total_result.series_id.value}"
            f" | Principal: R$ {principal.amount:.2f}"
            f" | Taxa efetiva: {total_result.effective_rate:.8f}"
            f" | Período: {prev_date_str} a {calculation_date.isoformat()}"
            f" | Parcela nº {deposit.installment_number}"
            f" | Aporte: {deposit.deposited_at.isoformat()}"
        )

        # Create YIELD transaction (no contract in subscription flow).
        transaction = Transaction.create_yield(
            user_id=deposit.user_id,
            amount_cents=delta_cents,
            description=description,
            subscription_id=deposit.subscription_id,
        )
        saved_transaction = await self._transaction_repo.save(transaction)

        # Credit wallet.
        wallet = await self._wallet_repo.get_by_user_id(deposit.user_id)
        if not wallet:
            raise ValueError(
                f"Wallet not found for user {deposit.user_id} "
                f"while crediting yield for deposit {deposit.id}"
            )
        wallet.credit_yield(delta_yield)
        await self._wallet_repo.save(wallet)

        # Audit log with full traceability (immutable, queryable).
        audit = AuditLog.create(
            action=AuditAction.YIELD_CREDITED,
            actor_id=deposit.user_id,
            target_id=saved_transaction.id,
            target_type="transaction",
            details={
                "principal_deposit_id": str(deposit.id),
                "subscription_id": str(deposit.subscription_id),
                "installment_number": deposit.installment_number,
                "sgs_series_id": total_result.series_id.value,
                "deposited_at": deposit.deposited_at.isoformat(),
                "yield_period_from": prev_date_str,
                "yield_period_to": calculation_date.isoformat(),
                "effective_rate": str(total_result.effective_rate),
                "principal_cents": deposit.principal_cents,
                "yield_cents": delta_cents,
                "days_accrued": total_result.days_accrued,
            },
        )
        await self._audit_repo.save(audit)

        # Mark deposit as processed up to calculation_date.
        deposit.last_yield_run_date = calculation_date
        await self._principal_deposit_repo.save(deposit)

        # Atomic commit per deposit: partial progress preserved on failure.
        await self._session.commit()

        return delta_cents

    # ------------------------------------------------------------------
    # Legacy: contract-based yield (kept for backward compatibility)
    # ------------------------------------------------------------------

    async def calculate_yield_for_contract(
        self,
        contract_id: UUID,
        calculation_date: date,
    ) -> YieldCalculationResult | None:
        """Calculate yield for a contract (legacy contract flow).

        Uses stored BCB data for deterministic recalculation.
        """
        contract = await self._contract_repo.get_by_id(contract_id)
        if not contract or contract.status != ContractStatus.ACTIVE:
            return None

        if not contract.start_date:
            return None

        wallet = await self._wallet_repo.get_by_user_id(contract.user_id)
        if not wallet or wallet.total_invested_cents == 0:
            return None

        deposit_date = contract.start_date.date()
        series_id = YieldData.get_series_for_date(deposit_date)

        yield_data_list = await self._yield_data_repo.get_range(
            series_id=series_id,
            start_date=deposit_date,
            end_date=calculation_date,
        )

        if not yield_data_list:
            return None

        calculator = PoupancaYieldCalculator(yield_data_list)
        principal = Money.from_cents(wallet.total_invested_cents)
        return calculator.calculate_yield(
            principal=principal,
            deposit_date=deposit_date,
            calculation_date=calculation_date,
        )

    async def credit_yield(
        self,
        contract_id: UUID,
        yield_result: YieldCalculationResult,
    ) -> TransactionDTO:
        """Credit calculated yield to wallet (legacy contract flow).

        Creates transaction with full audit trail including:
        - Source SGS series ID
        - Reference date range
        - Applied effective rate
        """
        contract = await self._contract_repo.get_by_id(contract_id)
        if not contract:
            raise ValueError(f"Contract not found: {contract_id}")

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

        saved_transaction = await self._transaction_repo.save(transaction)

        wallet = await self._wallet_repo.get_by_user_id(contract.user_id)
        wallet.credit_yield(yield_result.yield_amount)
        await self._wallet_repo.save(wallet)

        audit = AuditLog.create(
            action=AuditAction.YIELD_CREDITED,
            actor_id=contract.user_id,
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
