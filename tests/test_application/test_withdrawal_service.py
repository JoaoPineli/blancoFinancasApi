"""Tests for WithdrawalService.

Covers:
- reject_withdrawal stores rejection_reason on transaction
- reject_withdrawal reinstates subscription (ACTIVE if not fully paid)
- reject_withdrawal reinstates subscription (COMPLETED if fully paid)
- reject_withdrawal raises AuthorizationError for non-admin
- reject_withdrawal raises TransactionNotFoundError for unknown transaction
"""

import pytest
import random
from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.application.dtos.finance import RequestPlanWithdrawalInput
from app.application.services.installment_payment_service import InstallmentPaymentService
from app.application.services.withdrawal_service import WithdrawalService
from app.domain.entities.plan import Plan
from app.domain.entities.subscription import SubscriptionStatus, UserPlanSubscription
from app.domain.entities.transaction import TransactionStatus
from app.domain.entities.user import User, UserRole, UserStatus
from app.domain.entities.wallet import Wallet
from app.domain.exceptions import AuthorizationError, TransactionNotFoundError
from app.domain.value_objects.cpf import CPF
from app.domain.value_objects.email import Email
from app.infrastructure.db.repositories.plan_repository import PlanRepository
from app.infrastructure.db.repositories.subscription_repository import SubscriptionRepository
from app.infrastructure.db.repositories.transaction_repository import TransactionRepository
from app.infrastructure.db.repositories.user_repository import UserRepository
from app.infrastructure.db.repositories.wallet_repository import WalletRepository


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _generate_valid_cpf() -> str:
    while True:
        digits = [random.randint(0, 9) for _ in range(9)]
        if len(set(digits)) > 1:
            break
    s1 = sum(d * w for d, w in zip(digits, range(10, 1, -1)))
    r1 = s1 % 11
    d1 = 0 if r1 < 2 else 11 - r1
    s2 = sum(d * w for d, w in zip(digits, range(11, 2, -1))) + d1 * 2
    r2 = s2 % 11
    d2 = 0 if r2 < 2 else 11 - r2
    full = digits + [d1, d2]
    return f"{full[0]}{full[1]}{full[2]}.{full[3]}{full[4]}{full[5]}.{full[6]}{full[7]}{full[8]}-{full[9]}{full[10]}"


async def _create_user(session, role: UserRole = UserRole.CLIENT) -> User:
    repo = UserRepository(session)
    user = User.create(
        cpf=CPF(_generate_valid_cpf()),
        email=Email(f"{uuid4().hex[:8]}@test.com"),
        name="Test User",
        password_hash="hash",
        role=role,
    )
    saved = await repo.save(user)
    if role == UserRole.ADMIN:
        saved.role = UserRole.ADMIN
        saved = await repo.save(saved)
    return saved


async def _create_plan(session) -> Plan:
    repo = PlanRepository(session)
    plan = Plan.create(
        title="Plano Teste",
        description="Desc",
        min_value_cents=100_000,
        max_value_cents=10_000_000,
        min_duration_months=6,
        max_duration_months=36,
        admin_tax_value_cents=5_000,
        insurance_percent=Decimal("2.5"),
        guarantee_fund_percent_1=Decimal("1.0"),
        guarantee_fund_percent_2=Decimal("1.3"),
        guarantee_fund_threshold_cents=5_000_000,
    )
    return await repo.save(plan)


async def _create_subscription(
    session,
    user_id,
    plan_id,
    *,
    deposit_count: int = 12,
    deposits_paid: int = 4,
    status: SubscriptionStatus = SubscriptionStatus.CANCELLED,
) -> UserPlanSubscription:
    repo = SubscriptionRepository(session)
    sub = UserPlanSubscription.create(
        user_id=user_id,
        plan_id=plan_id,
        target_amount_cents=50_000 * deposit_count,
        deposit_count=deposit_count,
        monthly_amount_cents=50_000,
        admin_tax_value_cents=5_000,
        insurance_percent=Decimal("2.5"),
        guarantee_fund_percent=Decimal("1.0"),
        total_cost_cents=10_000,
        name="Minha Poupança",
        deposit_day_of_month=1,
    )
    # Activate first so status can be ACTIVE or CANCELLED/COMPLETED
    sub.activate(deposit_day_of_month=1, today_local=date.today())
    sub.deposits_paid = deposits_paid
    sub.status = status
    return await repo.save(sub)


async def _create_wallet(session, user_id, balance_cents: int = 300_000) -> Wallet:
    from app.domain.value_objects.money import Money
    repo = WalletRepository(session)
    wallet = Wallet.create(user_id)
    wallet.credit(Money.from_cents(balance_cents))
    return await repo.save(wallet)


async def _get_pending_withdrawal(session, user_id):
    """Get the pending withdrawal transaction for a user."""
    from app.domain.entities.transaction import TransactionStatus, TransactionType
    repo = TransactionRepository(session)
    txs = await repo.get_by_user_id(
        user_id=user_id,
        transaction_type=TransactionType.WITHDRAWAL,
        status=TransactionStatus.PENDING,
    )
    assert txs, "No pending withdrawal found"
    return txs[0]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRejectWithdrawal:
    """Tests for WithdrawalService.reject_withdrawal."""

    @pytest.mark.asyncio
    async def test_reject_saves_rejection_reason(self, test_session):
        """Rejected withdrawal has rejection_reason stored on the transaction."""
        client = await _create_user(test_session, UserRole.CLIENT)
        admin = await _create_user(test_session, UserRole.ADMIN)
        plan = await _create_plan(test_session)
        sub = await _create_subscription(
            test_session, client.id, plan.id,
            deposit_count=6, deposits_paid=4,
            status=SubscriptionStatus.ACTIVE,
        )
        await _create_wallet(test_session, client.id)
        await test_session.commit()

        # Create a withdrawal via InstallmentPaymentService
        ips = InstallmentPaymentService(test_session)
        await ips.request_plan_withdrawal(
            RequestPlanWithdrawalInput(
                user_id=client.id,
                subscription_id=sub.id,
                owner_name="Test User",
                pix_key_type="cpf",
                pix_key="529.982.247-25",
            )
        )
        await test_session.commit()

        tx = await _get_pending_withdrawal(test_session, client.id)

        # Reject it
        service = WithdrawalService(test_session)
        result = await service.reject_withdrawal(
            transaction_id=tx.id,
            admin_id=admin.id,
            reason="Chave Pix inválida",
        )
        await test_session.commit()

        assert result.status == "cancelled"
        assert result.rejection_reason == "Chave Pix inválida"

        # Verify in DB
        tx_repo = TransactionRepository(test_session)
        tx = await tx_repo.get_by_id(tx.id)
        assert tx is not None
        assert tx.status == TransactionStatus.CANCELLED
        assert tx.rejection_reason == "Chave Pix inválida"

    @pytest.mark.asyncio
    async def test_reject_reinstates_active_subscription(self, test_session):
        """Rejecting a withdrawal from an active (early) plan reactivates the subscription."""
        client = await _create_user(test_session, UserRole.CLIENT)
        admin = await _create_user(test_session, UserRole.ADMIN)
        plan = await _create_plan(test_session)
        sub = await _create_subscription(
            test_session, client.id, plan.id,
            deposit_count=12, deposits_paid=4,
            status=SubscriptionStatus.ACTIVE,
        )
        await _create_wallet(test_session, client.id)
        await test_session.commit()

        ips = InstallmentPaymentService(test_session)
        await ips.request_plan_withdrawal(
            RequestPlanWithdrawalInput(
                user_id=client.id,
                subscription_id=sub.id,
                owner_name="Test",
                pix_key_type="email",
                pix_key="test@test.com",
            )
        )
        await test_session.commit()

        tx = await _get_pending_withdrawal(test_session, client.id)
        service = WithdrawalService(test_session)
        await service.reject_withdrawal(
            transaction_id=tx.id,
            admin_id=admin.id,
            reason="Dados incorretos",
        )
        await test_session.commit()

        sub_repo = SubscriptionRepository(test_session)
        updated = await sub_repo.get_by_id(sub.id)
        assert updated is not None
        assert updated.status == SubscriptionStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_reject_marks_completed_subscription_as_completed(self, test_session):
        """Rejecting withdrawal from a completed plan restores COMPLETED status."""
        client = await _create_user(test_session, UserRole.CLIENT)
        admin = await _create_user(test_session, UserRole.ADMIN)
        plan = await _create_plan(test_session)
        sub = await _create_subscription(
            test_session, client.id, plan.id,
            deposit_count=6, deposits_paid=6,
            status=SubscriptionStatus.COMPLETED,
        )
        await _create_wallet(test_session, client.id)
        await test_session.commit()

        ips = InstallmentPaymentService(test_session)
        await ips.request_plan_withdrawal(
            RequestPlanWithdrawalInput(
                user_id=client.id,
                subscription_id=sub.id,
                owner_name="Test",
                pix_key_type="celular",
                pix_key="+5511999999999",
            )
        )
        await test_session.commit()

        tx = await _get_pending_withdrawal(test_session, client.id)
        service = WithdrawalService(test_session)
        await service.reject_withdrawal(
            transaction_id=tx.id,
            admin_id=admin.id,
            reason="Conta incorreta",
        )
        await test_session.commit()

        sub_repo = SubscriptionRepository(test_session)
        updated = await sub_repo.get_by_id(sub.id)
        assert updated is not None
        assert updated.status == SubscriptionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_reject_raises_for_non_admin(self, test_session):
        """Non-admin cannot reject a withdrawal."""
        client = await _create_user(test_session, UserRole.CLIENT)
        plan = await _create_plan(test_session)
        sub = await _create_subscription(
            test_session, client.id, plan.id,
            deposit_count=6, deposits_paid=4,
            status=SubscriptionStatus.ACTIVE,
        )
        await _create_wallet(test_session, client.id)
        await test_session.commit()

        ips = InstallmentPaymentService(test_session)
        await ips.request_plan_withdrawal(
            RequestPlanWithdrawalInput(
                user_id=client.id,
                subscription_id=sub.id,
                owner_name="Test",
                pix_key_type="cpf",
                pix_key="529.982.247-25",
            )
        )
        await test_session.commit()

        tx = await _get_pending_withdrawal(test_session, client.id)
        service = WithdrawalService(test_session)
        with pytest.raises(AuthorizationError):
            await service.reject_withdrawal(
                transaction_id=tx.id,
                admin_id=client.id,  # client, not admin
                reason="Invalid",
            )

    @pytest.mark.asyncio
    async def test_reject_raises_for_unknown_transaction(self, test_session):
        """Rejecting an unknown transaction raises TransactionNotFoundError."""
        admin = await _create_user(test_session, UserRole.ADMIN)
        await test_session.commit()

        service = WithdrawalService(test_session)
        with pytest.raises(TransactionNotFoundError):
            await service.reject_withdrawal(
                transaction_id=uuid4(),
                admin_id=admin.id,
                reason="Motivo",
            )
