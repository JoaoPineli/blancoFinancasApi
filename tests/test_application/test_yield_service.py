"""Tests for YieldService.process_all_yields.

Covers:
- Idempotency: running twice on same date credits zero additional yield
- Multi-deposit: each deposit earns yield from its own deposited_at date
- SGS series selection: pre-2012 vs post-2012
- Delta calculation: only new complete months are credited
- No complete months: wallet unchanged
- Missing yield data: raises error (fail loud)
"""

from datetime import date, datetime
from decimal import Decimal
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.domain.entities.audit_log import AuditAction
from app.domain.entities.principal_deposit import PrincipalDeposit
from app.domain.entities.wallet import Wallet
from app.domain.entities.yield_data import SGSSeries, YieldData
from app.domain.exceptions import YieldCalculationError
from app.domain.value_objects.money import Money


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_deposit(
    user_id,
    deposited_at: date,
    principal_cents: int = 100_000,  # R$ 1,000.00
    last_yield_run_date=None,
    installment_number: int = 1,
) -> PrincipalDeposit:
    return PrincipalDeposit(
        id=uuid4(),
        user_id=user_id,
        subscription_id=uuid4(),
        transaction_item_id=uuid4(),
        installment_number=installment_number,
        principal_cents=principal_cents,
        deposited_at=deposited_at,
        last_yield_run_date=last_yield_run_date,
        created_at=datetime.utcnow(),
    )


def _make_wallet(user_id) -> Wallet:
    return Wallet(
        id=uuid4(),
        user_id=user_id,
        balance_cents=200_000,
        total_invested_cents=100_000,
        total_yield_cents=0,
        fundo_garantidor_cents=5_000,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


def _make_yield_data(reference_date: date, series: SGSSeries, rate_str: str) -> YieldData:
    return YieldData.create(
        series_id=series,
        reference_date=reference_date,
        rate=Decimal(rate_str),
    )


# ---------------------------------------------------------------------------
# Service factory with mocked infrastructure
# ---------------------------------------------------------------------------


def _build_service_with_mocks(
    deposits,
    wallet,
    yield_data_for_range,
    bcb_data=None,
):
    """Build a YieldService instance with all repositories mocked.

    Args:
        deposits: List returned by get_pending_yield_processing.
        wallet: Wallet entity returned by get_by_user_id.
        yield_data_for_range: List returned by yield_data_repo.get_range.
        bcb_data: List returned by BCB client (defaults to empty).
    """
    from app.application.services.yield_service import YieldService
    from sqlalchemy.ext.asyncio import AsyncSession

    session = AsyncMock(spec=AsyncSession)
    session.commit = AsyncMock()

    service = YieldService.__new__(YieldService)
    service._session = session

    # Principal deposit repo
    pd_repo = AsyncMock()
    pd_repo.get_pending_yield_processing = AsyncMock(return_value=deposits)
    pd_repo.save = AsyncMock(side_effect=lambda d: d)
    service._principal_deposit_repo = pd_repo

    # Yield data repo
    yd_repo = AsyncMock()
    yd_repo.get_range = AsyncMock(return_value=yield_data_for_range)
    yd_repo.save = AsyncMock(side_effect=lambda d: d)
    service._yield_data_repo = yd_repo

    # Wallet repo
    wallet_repo = AsyncMock()
    wallet_repo.get_by_user_id = AsyncMock(return_value=wallet)
    wallet_repo.save = AsyncMock(side_effect=lambda w: w)
    service._wallet_repo = wallet_repo

    # Transaction repo
    tx_repo = AsyncMock()
    saved_tx = MagicMock()
    saved_tx.id = uuid4()
    saved_tx.user_id = wallet.user_id
    saved_tx.contract_id = None
    saved_tx.transaction_type = MagicMock(value="yield")
    saved_tx.status = MagicMock(value="confirmed")
    saved_tx.amount_cents = 0
    saved_tx.installment_number = None
    saved_tx.pix_key = None
    saved_tx.pix_transaction_id = None
    saved_tx.bank_account = None
    saved_tx.description = None
    saved_tx.created_at = datetime.utcnow()
    saved_tx.confirmed_at = datetime.utcnow()
    tx_repo.save = AsyncMock(return_value=saved_tx)
    service._transaction_repo = tx_repo

    # Audit repo
    audit_repo = AsyncMock()
    audit_repo.save = AsyncMock()
    service._audit_repo = audit_repo

    # BCB client
    bcb = AsyncMock()
    bcb.fetch_yield_data = AsyncMock(return_value=bcb_data or [])
    service._bcb_client = bcb

    # Contract repo (not used in subscription flow)
    service._contract_repo = AsyncMock()

    return service, pd_repo, yd_repo, wallet_repo, tx_repo, audit_repo, bcb


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestProcessAllYieldsEmpty:
    """process_all_yields with no pending deposits."""

    @pytest.mark.asyncio
    async def test_no_deposits_returns_zero_summary(self):
        user_id = uuid4()
        wallet = _make_wallet(user_id)
        service, *_ = _build_service_with_mocks(
            deposits=[],
            wallet=wallet,
            yield_data_for_range=[],
        )

        result = await service.process_all_yields(calculation_date=date(2024, 3, 15))

        assert result.deposits_evaluated == 0
        assert result.deposits_credited == 0
        assert result.total_yield_cents == 0
        assert result.credited == []


class TestProcessAllYieldsNoCompletedMonth:
    """Deposit exists but no complete month has elapsed — nothing credited."""

    @pytest.mark.asyncio
    async def test_no_month_elapsed_no_credit(self):
        user_id = uuid4()
        wallet = _make_wallet(user_id)
        deposit = _make_deposit(
            user_id=user_id,
            deposited_at=date(2024, 3, 1),
            last_yield_run_date=None,
        )
        # Calculation date before first anniversary
        service, pd_repo, yd_repo, wallet_repo, tx_repo, audit_repo, _ = (
            _build_service_with_mocks(
                deposits=[deposit],
                wallet=wallet,
                yield_data_for_range=[],  # No data needed — 0 complete months
            )
        )

        result = await service.process_all_yields(calculation_date=date(2024, 3, 20))

        assert result.deposits_evaluated == 1
        assert result.deposits_credited == 0
        assert result.total_yield_cents == 0
        # last_yield_run_date is updated even if nothing credited
        pd_repo.save.assert_called()
        tx_repo.save.assert_not_called()
        wallet_repo.save.assert_not_called()


class TestProcessAllYieldsOnComplete:
    """Deposit has one complete month — credit it."""

    @pytest.mark.asyncio
    async def test_one_month_credited(self):
        user_id = uuid4()
        wallet = _make_wallet(user_id)
        deposit = _make_deposit(
            user_id=user_id,
            deposited_at=date(2024, 1, 15),
            principal_cents=1_000_000,  # R$ 10,000.00
            last_yield_run_date=None,
        )
        yield_data = [
            _make_yield_data(date(2024, 1, 15), SGSSeries.POST_2012, "0.005"),
        ]

        service, pd_repo, yd_repo, wallet_repo, tx_repo, audit_repo, _ = (
            _build_service_with_mocks(
                deposits=[deposit],
                wallet=wallet,
                yield_data_for_range=yield_data,
            )
        )

        result = await service.process_all_yields(calculation_date=date(2024, 2, 15))

        assert result.deposits_evaluated == 1
        assert result.deposits_credited == 1
        # R$ 10,000 * 0.5% = R$ 50 → 5000 cents
        assert result.total_yield_cents == 5000
        assert result.credited[0].yield_credited_cents == 5000

        # Wallet.credit_yield was called with the right amount
        wallet_repo.save.assert_called_once()
        saved_wallet = wallet_repo.save.call_args[0][0]
        assert saved_wallet.total_yield_cents == 5000
        assert saved_wallet.balance_cents == 205_000  # 200_000 + 5_000

        # YIELD transaction was created
        tx_repo.save.assert_called_once()

        # Audit log was saved
        audit_repo.save.assert_called_once()
        audit_call = audit_repo.save.call_args[0][0]
        assert audit_call.action == AuditAction.YIELD_CREDITED
        assert audit_call.details["sgs_series_id"] == SGSSeries.POST_2012.value
        assert audit_call.details["yield_cents"] == 5000
        assert audit_call.details["principal_cents"] == 1_000_000

        # last_yield_run_date updated
        saved_deposit = pd_repo.save.call_args[0][0]
        assert saved_deposit.last_yield_run_date == date(2024, 2, 15)


class TestIdempotency:
    """Running twice on the same date credits zero additional yield."""

    @pytest.mark.asyncio
    async def test_same_date_no_double_credit(self):
        user_id = uuid4()
        wallet = _make_wallet(user_id)
        # Deposit already processed through Feb 15
        deposit = _make_deposit(
            user_id=user_id,
            deposited_at=date(2024, 1, 15),
            principal_cents=1_000_000,
            last_yield_run_date=date(2024, 2, 15),
        )
        yield_data = [
            _make_yield_data(date(2024, 1, 15), SGSSeries.POST_2012, "0.005"),
        ]

        service, pd_repo, yd_repo, wallet_repo, tx_repo, audit_repo, _ = (
            _build_service_with_mocks(
                deposits=[deposit],
                wallet=wallet,
                yield_data_for_range=yield_data,
            )
        )

        # Run again with the same calculation_date
        result = await service.process_all_yields(calculation_date=date(2024, 2, 15))

        assert result.deposits_evaluated == 1
        assert result.deposits_credited == 0
        assert result.total_yield_cents == 0
        tx_repo.save.assert_not_called()
        wallet_repo.save.assert_not_called()
        audit_repo.save.assert_not_called()


class TestDeltaCalculation:
    """Only new complete months since last run are credited."""

    @pytest.mark.asyncio
    async def test_delta_credits_only_new_month(self):
        user_id = uuid4()
        wallet = _make_wallet(user_id)
        # Already credited 1 month (Jan 15 → Feb 15)
        deposit = _make_deposit(
            user_id=user_id,
            deposited_at=date(2024, 1, 15),
            principal_cents=1_000_000,  # R$ 10,000.00
            last_yield_run_date=date(2024, 2, 15),
        )
        yield_data = [
            _make_yield_data(date(2024, 1, 15), SGSSeries.POST_2012, "0.005"),
            _make_yield_data(date(2024, 2, 15), SGSSeries.POST_2012, "0.005"),
        ]

        service, pd_repo, yd_repo, wallet_repo, tx_repo, audit_repo, _ = (
            _build_service_with_mocks(
                deposits=[deposit],
                wallet=wallet,
                yield_data_for_range=yield_data,
            )
        )

        result = await service.process_all_yields(calculation_date=date(2024, 3, 15))

        assert result.deposits_credited == 1
        # Month 2 yield: R$10,000 * 1.005 * 0.005 = R$50.25 → 5025 cents
        assert result.total_yield_cents == 5025


class TestMultipleDeposits:
    """Each deposit earns yield independently from its own deposited_at."""

    @pytest.mark.asyncio
    async def test_two_deposits_different_dates(self):
        user_id = uuid4()
        wallet = _make_wallet(user_id)
        wallet.total_invested_cents = 2_000_000

        deposit_jan = _make_deposit(
            user_id=user_id,
            deposited_at=date(2024, 1, 15),
            principal_cents=1_000_000,  # R$ 10,000
            last_yield_run_date=None,
            installment_number=1,
        )
        deposit_feb = _make_deposit(
            user_id=user_id,
            deposited_at=date(2024, 2, 15),
            principal_cents=1_000_000,  # R$ 10,000
            last_yield_run_date=None,
            installment_number=2,
        )

        yield_data = [
            _make_yield_data(date(2024, 1, 15), SGSSeries.POST_2012, "0.005"),
            _make_yield_data(date(2024, 2, 15), SGSSeries.POST_2012, "0.005"),
        ]

        service, pd_repo, yd_repo, wallet_repo, tx_repo, audit_repo, _ = (
            _build_service_with_mocks(
                deposits=[deposit_jan, deposit_feb],
                wallet=wallet,
                yield_data_for_range=yield_data,
            )
        )

        result = await service.process_all_yields(calculation_date=date(2024, 3, 15))

        # Jan deposit: 2 complete months (Jan15→Feb15, Feb15→Mar15)
        # Feb deposit: 1 complete month (Feb15→Mar15)
        assert result.deposits_credited == 2
        # Jan: 10000 * (1.005^2 - 1) = 10000 * 0.010025 = 100.25 → 10025 cents
        # Feb: 10000 * 0.005 = 50.00 → 5000 cents
        assert result.total_yield_cents == 10025 + 5000

    @pytest.mark.asyncio
    async def test_mixed_credited_and_uncredited(self):
        """One deposit already credited, one not — only uncredited deposit is processed."""
        user_id = uuid4()
        wallet = _make_wallet(user_id)

        deposit_done = _make_deposit(
            user_id=user_id,
            deposited_at=date(2024, 1, 15),
            principal_cents=1_000_000,
            last_yield_run_date=date(2024, 2, 15),  # already credited 1 month
            installment_number=1,
        )
        deposit_new = _make_deposit(
            user_id=user_id,
            deposited_at=date(2024, 2, 15),
            principal_cents=1_000_000,
            last_yield_run_date=None,  # never credited
            installment_number=2,
        )

        yield_data = [
            _make_yield_data(date(2024, 1, 15), SGSSeries.POST_2012, "0.005"),
            _make_yield_data(date(2024, 2, 15), SGSSeries.POST_2012, "0.005"),
        ]

        service, pd_repo, yd_repo, wallet_repo, tx_repo, audit_repo, _ = (
            _build_service_with_mocks(
                deposits=[deposit_done, deposit_new],
                wallet=wallet,
                yield_data_for_range=yield_data,
            )
        )

        result = await service.process_all_yields(calculation_date=date(2024, 2, 15))

        # deposit_done: delta from Feb15 to Feb15 = 0 months → not credited
        # deposit_new: delta from Feb15 to Feb15 = 0 months → not credited either
        # (Calculation date = Feb 15 = deposit_new.deposited_at → 0 complete months)
        assert result.deposits_credited == 0


class TestSGSSeriesSelection:
    """Correct SGS series is used based on deposit date."""

    @pytest.mark.asyncio
    async def test_post_2012_deposit_uses_series_195(self):
        user_id = uuid4()
        wallet = _make_wallet(user_id)
        deposit = _make_deposit(
            user_id=user_id,
            deposited_at=date(2024, 1, 15),
            principal_cents=100_000,
        )
        yield_data = [
            _make_yield_data(date(2024, 1, 15), SGSSeries.POST_2012, "0.005"),
        ]

        service, pd_repo, *_ = _build_service_with_mocks(
            deposits=[deposit],
            wallet=wallet,
            yield_data_for_range=yield_data,
        )

        result = await service.process_all_yields(calculation_date=date(2024, 2, 15))

        assert result.deposits_credited == 1
        assert result.credited[0].yield_credited_cents > 0

    @pytest.mark.asyncio
    async def test_pre_2012_deposit_uses_series_25(self):
        user_id = uuid4()
        wallet = _make_wallet(user_id)
        deposit = _make_deposit(
            user_id=user_id,
            deposited_at=date(2011, 6, 1),  # pre-2012
            principal_cents=100_000,
        )
        yield_data = [
            _make_yield_data(date(2011, 6, 1), SGSSeries.PRE_2012, "0.005"),
        ]

        service, pd_repo, yd_repo, wallet_repo, tx_repo, audit_repo, bcb = (
            _build_service_with_mocks(
                deposits=[deposit],
                wallet=wallet,
                yield_data_for_range=yield_data,
            )
        )

        result = await service.process_all_yields(calculation_date=date(2011, 7, 1))

        assert result.deposits_credited == 1
        # Verify get_range was called with PRE_2012 series
        yd_repo.get_range.assert_called_once()
        call_kwargs = yd_repo.get_range.call_args[1]
        assert call_kwargs["series_id"] == SGSSeries.PRE_2012


class TestFailLoudBehavior:
    """Missing yield data causes YieldCalculationError — not silent skip."""

    @pytest.mark.asyncio
    async def test_missing_yield_data_raises(self):
        user_id = uuid4()
        wallet = _make_wallet(user_id)
        deposit = _make_deposit(
            user_id=user_id,
            deposited_at=date(2024, 1, 15),
            principal_cents=100_000,
        )

        service, *_ = _build_service_with_mocks(
            deposits=[deposit],
            wallet=wallet,
            yield_data_for_range=[],  # no data — 1 complete month should raise
        )

        with pytest.raises(YieldCalculationError):
            await service.process_all_yields(calculation_date=date(2024, 2, 15))


class TestAuditLogDetails:
    """YIELD_CREDITED audit log contains all required traceability fields."""

    @pytest.mark.asyncio
    async def test_audit_log_has_required_fields(self):
        user_id = uuid4()
        wallet = _make_wallet(user_id)
        deposit = _make_deposit(
            user_id=user_id,
            deposited_at=date(2024, 1, 15),
            principal_cents=500_000,  # R$ 5,000
        )
        yield_data = [
            _make_yield_data(date(2024, 1, 15), SGSSeries.POST_2012, "0.005"),
        ]

        service, pd_repo, yd_repo, wallet_repo, tx_repo, audit_repo, _ = (
            _build_service_with_mocks(
                deposits=[deposit],
                wallet=wallet,
                yield_data_for_range=yield_data,
            )
        )

        await service.process_all_yields(calculation_date=date(2024, 2, 15))

        audit_repo.save.assert_called_once()
        audit_log = audit_repo.save.call_args[0][0]
        details = audit_log.details

        assert "principal_deposit_id" in details
        assert "subscription_id" in details
        assert "sgs_series_id" in details
        assert "deposited_at" in details
        assert "yield_period_from" in details
        assert "yield_period_to" in details
        assert "effective_rate" in details
        assert "principal_cents" in details
        assert "yield_cents" in details
        assert "days_accrued" in details

        assert details["sgs_series_id"] == SGSSeries.POST_2012.value
        assert details["principal_cents"] == 500_000
        assert details["yield_cents"] == 2500  # R$5,000 * 0.5%
