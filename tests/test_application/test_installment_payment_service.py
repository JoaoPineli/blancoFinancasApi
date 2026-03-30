"""Tests for InstallmentPaymentService.

Covers:
- Listing payable installments
- Creating grouped installment payments
- Duplicate payment prevention
- Idempotent payment confirmation
- Subscription progress after confirmation
- Withdrawable subscriptions listing
- Plan withdrawal (early termination + completed)
- Financial history merging
"""

import pytest
import random
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from app.application.dtos.finance import (
    CreateInstallmentPaymentInput,
    RequestPlanWithdrawalInput,
)
from app.application.services.installment_payment_service import (
    InstallmentPaymentService,
)
from app.domain.entities.plan import Plan
from app.domain.entities.subscription import (
    SubscriptionStatus,
    UserPlanSubscription,
)
from app.domain.entities.user import User, UserRole, UserStatus
from app.domain.entities.wallet import Wallet
from app.domain.constants import calculate_pix_fee
from app.domain.exceptions import (
    DuplicatePaymentError,
    InvalidPaymentError,
    PaymentNotFoundError,
    SubscriptionNotFoundError,
)
from app.domain.value_objects.email import Email
from app.infrastructure.db.repositories.plan_repository import PlanRepository
from app.infrastructure.db.repositories.subscription_repository import (
    SubscriptionRepository,
)
from app.infrastructure.db.repositories.user_repository import UserRepository
from app.infrastructure.db.repositories.wallet_repository import WalletRepository


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _generate_valid_cpf() -> str:
    """Generate a valid, formatted CPF string for testing."""
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


async def _create_user(session, name: str = "Test User") -> User:
    """Create and persist an active test user."""
    from app.domain.value_objects.cpf import CPF
    repo = UserRepository(session)
    user = User.create(
        cpf=CPF(_generate_valid_cpf()),
        email=Email(f"{uuid4().hex[:8]}@test.com"),
        name=name,
        password_hash="test_hashed_password",
        role=UserRole.CLIENT,
    )
    return await repo.save(user)


async def _create_plan(session) -> Plan:
    """Create and persist a standard test plan."""
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
    name: str = "Minha assinatura",
    monthly_amount_cents: int = 50_000,
    deposit_count: int = 12,
    deposits_paid: int = 0,
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE,
) -> UserPlanSubscription:
    """Create and persist a test subscription.

    Subscriptions start INACTIVE; activate() is called when the desired status
    is ACTIVE (or the status is set directly for other terminal states).
    """
    repo = SubscriptionRepository(session)
    sub = UserPlanSubscription.create(
        user_id=user_id,
        plan_id=plan_id,
        target_amount_cents=monthly_amount_cents * deposit_count,
        deposit_count=deposit_count,
        monthly_amount_cents=monthly_amount_cents,
        admin_tax_value_cents=5_000,
        insurance_percent=Decimal("2.5"),
        guarantee_fund_percent=Decimal("1.0"),
        total_cost_cents=10_000,
        name=name,
        deposit_day_of_month=1,
    )
    # Activate or set the desired status
    if status == SubscriptionStatus.ACTIVE:
        sub.activate(deposit_day_of_month=1, today_local=date.today())
    elif status == SubscriptionStatus.COMPLETED:
        sub.activate(deposit_day_of_month=1, today_local=date.today())
        sub.deposits_paid = deposit_count
        sub.status = SubscriptionStatus.COMPLETED
    elif status == SubscriptionStatus.CANCELLED:
        sub.status = SubscriptionStatus.CANCELLED
    # Adjust deposits_paid if needed (for partially-paid subs)
    if deposits_paid and status == SubscriptionStatus.ACTIVE:
        sub.deposits_paid = deposits_paid
    return await repo.save(sub)


async def _create_wallet(session, user_id) -> Wallet:
    """Create and persist a wallet for a user."""
    repo = WalletRepository(session)
    wallet = Wallet.create(user_id)
    return await repo.save(wallet)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGetPayableInstallments:
    """Tests for get_payable_installments."""

    @pytest.mark.asyncio
    async def test_returns_one_installment_per_active_sub(self, test_session):
        """Active subscriptions with unpaid installments are returned."""
        user = await _create_user(test_session)
        plan = await _create_plan(test_session)
        sub = await _create_subscription(test_session, user.id, plan.id)
        await test_session.commit()

        service = InstallmentPaymentService(test_session)
        result = await service.get_payable_installments(user.id)

        assert result.total == 1
        inst = result.installments[0]
        assert inst.subscription_id == sub.id
        assert inst.installment_number == 1
        assert inst.total_installments == 12
        assert inst.amount_cents == 50_000

    @pytest.mark.asyncio
    async def test_skips_fully_paid_subs(self, test_session):
        """Fully-paid subscriptions are excluded."""
        user = await _create_user(test_session)
        plan = await _create_plan(test_session)
        await _create_subscription(
            test_session, user.id, plan.id, deposit_count=3, deposits_paid=3,
            status=SubscriptionStatus.COMPLETED,
        )
        await test_session.commit()

        service = InstallmentPaymentService(test_session)
        result = await service.get_payable_installments(user.id)

        assert result.total == 0

    @pytest.mark.asyncio
    async def test_multiple_subs_sorted_by_urgency(self, test_session):
        """Overdue installments appear before upcoming ones."""
        user = await _create_user(test_session)
        plan = await _create_plan(test_session)

        # Create two subs — one with an overdue due_date
        sub_overdue = await _create_subscription(
            test_session, user.id, plan.id, name="Overdue"
        )
        sub_upcoming = await _create_subscription(
            test_session, user.id, plan.id, name="Upcoming"
        )

        # Manually adjust due dates
        sub_repo = SubscriptionRepository(test_session)
        sub_overdue.next_due_date = date.today() - timedelta(days=5)
        await sub_repo.save(sub_overdue)
        sub_upcoming.next_due_date = date.today() + timedelta(days=10)
        await sub_repo.save(sub_upcoming)
        await test_session.commit()

        service = InstallmentPaymentService(test_session)
        result = await service.get_payable_installments(user.id)

        assert result.total == 2
        assert result.installments[0].subscription_id == sub_overdue.id
        assert result.installments[0].status == "overdue"
        assert result.installments[1].subscription_id == sub_upcoming.id
        assert result.installments[1].status == "upcoming"


class TestCreatePayment:
    """Tests for create_payment."""

    @pytest.mark.asyncio
    async def test_create_single_subscription_payment(self, test_session):
        """Creating a payment for one subscription produces a valid Pix payload."""
        user = await _create_user(test_session)
        plan = await _create_plan(test_session)
        sub = await _create_subscription(test_session, user.id, plan.id)
        await _create_wallet(test_session, user.id)
        await test_session.commit()

        service = InstallmentPaymentService(test_session)
        dto = await service.create_payment(
            CreateInstallmentPaymentInput(
                user_id=user.id,
                subscription_ids=[sub.id],
            )
        )

        assert dto.status == "pending"
        assert dto.total_amount_cents == 50_000 + calculate_pix_fee(50_000)
        assert dto.pix_qr_code_data is not None
        assert len(dto.items) == 1
        assert dto.items[0].subscription_id == sub.id
        assert dto.items[0].installment_number == 1

    @pytest.mark.asyncio
    async def test_create_multi_subscription_payment(self, test_session):
        """Creating a payment for multiple subscriptions sums amounts."""
        user = await _create_user(test_session)
        plan = await _create_plan(test_session)
        sub1 = await _create_subscription(
            test_session, user.id, plan.id, name="Sub A", monthly_amount_cents=30_000
        )
        sub2 = await _create_subscription(
            test_session, user.id, plan.id, name="Sub B", monthly_amount_cents=20_000
        )
        await _create_wallet(test_session, user.id)
        await test_session.commit()

        service = InstallmentPaymentService(test_session)
        dto = await service.create_payment(
            CreateInstallmentPaymentInput(
                user_id=user.id,
                subscription_ids=[sub1.id, sub2.id],
            )
        )

        assert dto.total_amount_cents == 50_000 + calculate_pix_fee(50_000)
        assert len(dto.items) == 2

    @pytest.mark.asyncio
    async def test_rejects_empty_subscription_list(self, test_session):
        """An empty subscription list raises InvalidPaymentError."""
        user = await _create_user(test_session)
        await test_session.commit()

        service = InstallmentPaymentService(test_session)
        with pytest.raises(InvalidPaymentError, match="pelo menos uma"):
            await service.create_payment(
                CreateInstallmentPaymentInput(
                    user_id=user.id,
                    subscription_ids=[],
                )
            )

    @pytest.mark.asyncio
    async def test_rejects_foreign_subscription(self, test_session):
        """Cannot pay for a subscription owned by another user."""
        user_a = await _create_user(test_session, name="User A")
        user_b = await _create_user(test_session, name="User B")
        plan = await _create_plan(test_session)
        sub = await _create_subscription(test_session, user_b.id, plan.id)
        await test_session.commit()

        service = InstallmentPaymentService(test_session)
        with pytest.raises(InvalidPaymentError, match="não encontrada"):
            await service.create_payment(
                CreateInstallmentPaymentInput(
                    user_id=user_a.id,
                    subscription_ids=[sub.id],
                )
            )

    @pytest.mark.asyncio
    async def test_rejects_inactive_subscription(self, test_session):
        """Cannot pay for a cancelled subscription."""
        user = await _create_user(test_session)
        plan = await _create_plan(test_session)
        sub = await _create_subscription(
            test_session, user.id, plan.id, status=SubscriptionStatus.CANCELLED,
        )
        await test_session.commit()

        service = InstallmentPaymentService(test_session)
        with pytest.raises(InvalidPaymentError, match="não está ativa"):
            await service.create_payment(
                CreateInstallmentPaymentInput(
                    user_id=user.id,
                    subscription_ids=[sub.id],
                )
            )

    @pytest.mark.asyncio
    async def test_rejects_fully_paid_subscription(self, test_session):
        """Cannot pay when all installments are paid."""
        user = await _create_user(test_session)
        plan = await _create_plan(test_session)
        sub = await _create_subscription(
            test_session, user.id, plan.id, deposit_count=3, deposits_paid=3,
        )
        # Force status back to active to test the fully-paid guard
        sub.status = SubscriptionStatus.ACTIVE
        sub_repo = SubscriptionRepository(test_session)
        await sub_repo.save(sub)
        await test_session.commit()

        service = InstallmentPaymentService(test_session)
        with pytest.raises(InvalidPaymentError, match="já foram pagas"):
            await service.create_payment(
                CreateInstallmentPaymentInput(
                    user_id=user.id,
                    subscription_ids=[sub.id],
                )
            )

    @pytest.mark.asyncio
    async def test_rejects_duplicate_pending_payment(self, test_session):
        """Creating a second payment for the same sub raises DuplicatePaymentError."""
        user = await _create_user(test_session)
        plan = await _create_plan(test_session)
        sub = await _create_subscription(test_session, user.id, plan.id)
        await _create_wallet(test_session, user.id)
        await test_session.commit()

        service = InstallmentPaymentService(test_session)

        # First payment succeeds
        await service.create_payment(
            CreateInstallmentPaymentInput(
                user_id=user.id,
                subscription_ids=[sub.id],
            )
        )

        # Second payment is rejected
        with pytest.raises(DuplicatePaymentError, match="pendente"):
            await service.create_payment(
                CreateInstallmentPaymentInput(
                    user_id=user.id,
                    subscription_ids=[sub.id],
                )
            )


class TestGetPayment:
    """Tests for get_payment."""

    @pytest.mark.asyncio
    async def test_get_own_payment(self, test_session):
        """Owner can retrieve their payment."""
        user = await _create_user(test_session)
        plan = await _create_plan(test_session)
        sub = await _create_subscription(test_session, user.id, plan.id)
        await _create_wallet(test_session, user.id)
        await test_session.commit()

        service = InstallmentPaymentService(test_session)
        created = await service.create_payment(
            CreateInstallmentPaymentInput(
                user_id=user.id,
                subscription_ids=[sub.id],
            )
        )

        fetched = await service.get_payment(created.id, user.id)
        assert fetched.id == created.id

    @pytest.mark.asyncio
    async def test_get_foreign_payment_raises(self, test_session):
        """Another user cannot retrieve a payment they don't own."""
        user_a = await _create_user(test_session, name="A")
        user_b = await _create_user(test_session, name="B")
        plan = await _create_plan(test_session)
        sub = await _create_subscription(test_session, user_a.id, plan.id)
        await _create_wallet(test_session, user_a.id)
        await test_session.commit()

        service = InstallmentPaymentService(test_session)
        created = await service.create_payment(
            CreateInstallmentPaymentInput(
                user_id=user_a.id,
                subscription_ids=[sub.id],
            )
        )

        with pytest.raises(PaymentNotFoundError):
            await service.get_payment(created.id, user_b.id)


class TestConfirmPayment:
    """Tests for confirm_payment."""

    @pytest.mark.asyncio
    async def test_confirm_updates_state(self, test_session):
        """Confirming a payment sets status to confirmed."""
        user = await _create_user(test_session)
        plan = await _create_plan(test_session)
        sub = await _create_subscription(test_session, user.id, plan.id)
        await _create_wallet(test_session, user.id)
        await test_session.commit()

        service = InstallmentPaymentService(test_session)
        created = await service.create_payment(
            CreateInstallmentPaymentInput(
                user_id=user.id,
                subscription_ids=[sub.id],
            )
        )

        confirmed = await service.confirm_payment(created.id, "pix-tx-001")
        assert confirmed.status == "confirmed"

    @pytest.mark.asyncio
    async def test_confirm_increments_deposits_paid(self, test_session):
        """Confirming increments deposits_paid on the subscription."""
        user = await _create_user(test_session)
        plan = await _create_plan(test_session)
        sub = await _create_subscription(test_session, user.id, plan.id)
        await _create_wallet(test_session, user.id)
        await test_session.commit()

        service = InstallmentPaymentService(test_session)
        created = await service.create_payment(
            CreateInstallmentPaymentInput(
                user_id=user.id,
                subscription_ids=[sub.id],
            )
        )
        await service.confirm_payment(created.id, "pix-tx-002")

        # Re-fetch subscription
        sub_repo = SubscriptionRepository(test_session)
        updated_sub = await sub_repo.get_by_id(sub.id)
        assert updated_sub is not None
        assert updated_sub.deposits_paid == 1

    @pytest.mark.asyncio
    async def test_confirm_credits_wallet(self, test_session):
        """Confirming a payment credits the user's wallet."""
        user = await _create_user(test_session)
        plan = await _create_plan(test_session)
        sub = await _create_subscription(
            test_session, user.id, plan.id, monthly_amount_cents=100_000,
        )
        await _create_wallet(test_session, user.id)
        await test_session.commit()

        service = InstallmentPaymentService(test_session)
        created = await service.create_payment(
            CreateInstallmentPaymentInput(
                user_id=user.id,
                subscription_ids=[sub.id],
            )
        )
        await service.confirm_payment(created.id, "pix-tx-003")

        wallet_repo = WalletRepository(test_session)
        wallet = await wallet_repo.get_by_user_id(user.id)
        assert wallet is not None
        # Wallet should have a positive invested balance and fundo garantidor
        assert wallet.total_invested_cents > 0
        assert wallet.fundo_garantidor_cents > 0
        # Total invested + fundo should be <= original amount
        assert (wallet.total_invested_cents + wallet.fundo_garantidor_cents) <= 100_000

    @pytest.mark.asyncio
    async def test_confirm_is_idempotent(self, test_session):
        """Confirming an already-confirmed payment returns the same state."""
        user = await _create_user(test_session)
        plan = await _create_plan(test_session)
        sub = await _create_subscription(test_session, user.id, plan.id)
        await _create_wallet(test_session, user.id)
        await test_session.commit()

        service = InstallmentPaymentService(test_session)
        created = await service.create_payment(
            CreateInstallmentPaymentInput(
                user_id=user.id,
                subscription_ids=[sub.id],
            )
        )

        first = await service.confirm_payment(created.id, "pix-tx-004")
        second = await service.confirm_payment(created.id, "pix-tx-004")

        assert first.status == second.status == "confirmed"

        # Deposits should only be incremented once
        sub_repo = SubscriptionRepository(test_session)
        updated_sub = await sub_repo.get_by_id(sub.id)
        assert updated_sub is not None
        assert updated_sub.deposits_paid == 1

    @pytest.mark.asyncio
    async def test_confirm_completes_subscription_when_all_paid(self, test_session):
        """Paying the last installment marks the subscription as completed."""
        user = await _create_user(test_session)
        plan = await _create_plan(test_session)
        sub = await _create_subscription(
            test_session, user.id, plan.id,
            deposit_count=2, deposits_paid=1,
        )
        await _create_wallet(test_session, user.id)
        await test_session.commit()

        service = InstallmentPaymentService(test_session)
        created = await service.create_payment(
            CreateInstallmentPaymentInput(
                user_id=user.id,
                subscription_ids=[sub.id],
            )
        )
        await service.confirm_payment(created.id, "pix-tx-005")

        sub_repo = SubscriptionRepository(test_session)
        updated_sub = await sub_repo.get_by_id(sub.id)
        assert updated_sub is not None
        assert updated_sub.status == SubscriptionStatus.COMPLETED
        assert updated_sub.deposits_paid == 2

    @pytest.mark.asyncio
    async def test_confirm_not_found_raises(self, test_session):
        """Confirming a non-existent payment raises PaymentNotFoundError."""
        service = InstallmentPaymentService(test_session)
        with pytest.raises(PaymentNotFoundError):
            await service.confirm_payment(uuid4(), "pix-tx-none")


class TestGetWithdrawableSubscriptions:
    """Tests for get_withdrawable_subscriptions."""

    @pytest.mark.asyncio
    async def test_completed_sub_is_withdrawable(self, test_session):
        """Completed subscriptions appear in withdrawable list."""
        user = await _create_user(test_session)
        plan = await _create_plan(test_session)
        await _create_subscription(
            test_session, user.id, plan.id,
            deposit_count=6, deposits_paid=6,
            status=SubscriptionStatus.COMPLETED,
        )
        await test_session.commit()

        service = InstallmentPaymentService(test_session)
        result = await service.get_withdrawable_subscriptions(user.id)

        assert result.total == 1
        assert result.subscriptions[0].is_early_termination is False
        assert result.subscriptions[0].withdrawable_amount_cents == 50_000 * 6

    @pytest.mark.asyncio
    async def test_active_with_deposits_is_withdrawable(self, test_session):
        """Active subscriptions with deposits > 0 appear (early termination)."""
        user = await _create_user(test_session)
        plan = await _create_plan(test_session)
        await _create_subscription(
            test_session, user.id, plan.id,
            deposit_count=12, deposits_paid=3,
        )
        await test_session.commit()

        service = InstallmentPaymentService(test_session)
        result = await service.get_withdrawable_subscriptions(user.id)

        assert result.total == 1
        assert result.subscriptions[0].is_early_termination is True
        assert result.subscriptions[0].withdrawable_amount_cents == 50_000 * 3

    @pytest.mark.asyncio
    async def test_active_with_zero_deposits_not_withdrawable(self, test_session):
        """Active subscriptions with 0 deposits are not withdrawable."""
        user = await _create_user(test_session)
        plan = await _create_plan(test_session)
        await _create_subscription(
            test_session, user.id, plan.id,
            deposit_count=12, deposits_paid=0,
        )
        await test_session.commit()

        service = InstallmentPaymentService(test_session)
        result = await service.get_withdrawable_subscriptions(user.id)

        assert result.total == 0

    @pytest.mark.asyncio
    async def test_cancelled_sub_not_withdrawable(self, test_session):
        """Cancelled subscriptions are not withdrawable."""
        user = await _create_user(test_session)
        plan = await _create_plan(test_session)
        await _create_subscription(
            test_session, user.id, plan.id,
            status=SubscriptionStatus.CANCELLED,
        )
        await test_session.commit()

        service = InstallmentPaymentService(test_session)
        result = await service.get_withdrawable_subscriptions(user.id)

        assert result.total == 0


class TestRequestPlanWithdrawal:
    """Tests for request_plan_withdrawal."""

    @pytest.mark.asyncio
    async def test_withdraw_completed_plan(self, test_session):
        """Withdrawing a completed plan creates a withdrawal transaction."""
        user = await _create_user(test_session)
        plan = await _create_plan(test_session)
        sub = await _create_subscription(
            test_session, user.id, plan.id,
            deposit_count=6, deposits_paid=6,
            status=SubscriptionStatus.COMPLETED,
        )
        await test_session.commit()

        service = InstallmentPaymentService(test_session)
        dto = await service.request_plan_withdrawal(
            RequestPlanWithdrawalInput(
                user_id=user.id,
                subscription_id=sub.id,
            )
        )

        assert dto.status == "pending"
        assert dto.amount_cents == 50_000 * 6
        assert dto.is_early_termination is False

        # Subscription should remain COMPLETED
        sub_repo = SubscriptionRepository(test_session)
        updated_sub = await sub_repo.get_by_id(sub.id)
        assert updated_sub is not None
        assert updated_sub.status == SubscriptionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_withdraw_active_early_cancels_sub(self, test_session):
        """Early withdrawal from active plan cancels the subscription."""
        user = await _create_user(test_session)
        plan = await _create_plan(test_session)
        sub = await _create_subscription(
            test_session, user.id, plan.id,
            deposit_count=12, deposits_paid=4,
        )
        await test_session.commit()

        service = InstallmentPaymentService(test_session)
        dto = await service.request_plan_withdrawal(
            RequestPlanWithdrawalInput(
                user_id=user.id,
                subscription_id=sub.id,
            )
        )

        assert dto.is_early_termination is True
        assert dto.amount_cents == 50_000 * 4

        # Subscription should be cancelled
        sub_repo = SubscriptionRepository(test_session)
        updated_sub = await sub_repo.get_by_id(sub.id)
        assert updated_sub is not None
        assert updated_sub.status == SubscriptionStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_withdraw_foreign_sub_raises(self, test_session):
        """Cannot withdraw from another user's subscription."""
        user_a = await _create_user(test_session, name="A")
        user_b = await _create_user(test_session, name="B")
        plan = await _create_plan(test_session)
        sub = await _create_subscription(
            test_session, user_b.id, plan.id,
            deposit_count=6, deposits_paid=6,
            status=SubscriptionStatus.COMPLETED,
        )
        await test_session.commit()

        service = InstallmentPaymentService(test_session)
        with pytest.raises(SubscriptionNotFoundError):
            await service.request_plan_withdrawal(
                RequestPlanWithdrawalInput(
                    user_id=user_a.id,
                    subscription_id=sub.id,
                )
            )

    @pytest.mark.asyncio
    async def test_withdraw_ineligible_sub_raises(self, test_session):
        """Cannot withdraw from sub with zero deposits."""
        user = await _create_user(test_session)
        plan = await _create_plan(test_session)
        sub = await _create_subscription(
            test_session, user.id, plan.id,
            deposit_count=12, deposits_paid=0,
        )
        await test_session.commit()

        service = InstallmentPaymentService(test_session)
        with pytest.raises(InvalidPaymentError, match="não está elegível"):
            await service.request_plan_withdrawal(
                RequestPlanWithdrawalInput(
                    user_id=user.id,
                    subscription_id=sub.id,
                )
            )


class TestGetUserHistory:
    """Tests for get_user_history."""

    @pytest.mark.asyncio
    async def test_history_includes_payments(self, test_session):
        """Confirmed and pending payments appear in history."""
        user = await _create_user(test_session)
        plan = await _create_plan(test_session)
        sub = await _create_subscription(test_session, user.id, plan.id)
        await _create_wallet(test_session, user.id)
        await test_session.commit()

        service = InstallmentPaymentService(test_session)
        await service.create_payment(
            CreateInstallmentPaymentInput(
                user_id=user.id,
                subscription_ids=[sub.id],
            )
        )

        result = await service.get_user_history(user.id)

        assert result.total >= 1
        payment_events = [e for e in result.events if e.event_type == "installment_payment"]
        assert len(payment_events) == 1
        assert payment_events[0].status == "pending"

    @pytest.mark.asyncio
    async def test_history_includes_withdrawals(self, test_session):
        """Withdrawal transactions appear in history."""
        user = await _create_user(test_session)
        plan = await _create_plan(test_session)
        sub = await _create_subscription(
            test_session, user.id, plan.id,
            deposit_count=6, deposits_paid=6,
            status=SubscriptionStatus.COMPLETED,
        )
        await test_session.commit()

        service = InstallmentPaymentService(test_session)
        await service.request_plan_withdrawal(
            RequestPlanWithdrawalInput(
                user_id=user.id,
                subscription_id=sub.id,
            )
        )

        result = await service.get_user_history(user.id)

        withdrawal_events = [e for e in result.events if e.event_type == "plan_withdrawal"]
        assert len(withdrawal_events) == 1
        assert withdrawal_events[0].status == "pending"
        assert withdrawal_events[0].amount_cents == 50_000 * 6

    @pytest.mark.asyncio
    async def test_history_sorted_desc(self, test_session):
        """Events are sorted newest-first."""
        user = await _create_user(test_session)
        plan = await _create_plan(test_session)

        # Create a completed sub for withdrawal
        sub_completed = await _create_subscription(
            test_session, user.id, plan.id,
            name="Completed",
            deposit_count=2, deposits_paid=2,
            status=SubscriptionStatus.COMPLETED,
        )
        # Create an active sub for payment
        sub_active = await _create_subscription(
            test_session, user.id, plan.id,
            name="Active",
        )
        await _create_wallet(test_session, user.id)
        await test_session.commit()

        service = InstallmentPaymentService(test_session)

        # First: withdrawal (created first, older)
        await service.request_plan_withdrawal(
            RequestPlanWithdrawalInput(
                user_id=user.id,
                subscription_id=sub_completed.id,
            )
        )

        # Second: payment (created after, newer)
        await service.create_payment(
            CreateInstallmentPaymentInput(
                user_id=user.id,
                subscription_ids=[sub_active.id],
            )
        )

        result = await service.get_user_history(user.id)

        assert result.total >= 2
        # Most recent event should be the payment
        assert result.events[0].event_type == "installment_payment"

    @pytest.mark.asyncio
    async def test_history_empty_for_new_user(self, test_session):
        """New user with no activity has empty history."""
        user = await _create_user(test_session)
        await test_session.commit()

        service = InstallmentPaymentService(test_session)
        result = await service.get_user_history(user.id)

        assert result.total == 0
        assert result.events == []


# ---------------------------------------------------------------------------
# Plan withdrawal with Pix data and notification
# ---------------------------------------------------------------------------


class TestRequestPlanWithdrawalPixAndNotification:
    """Tests for Pix data propagation and notification creation in request_plan_withdrawal."""

    @staticmethod
    async def _get_withdrawal_tx(session, user_id):
        """Fetch the most recent pending withdrawal transaction for a user."""
        from app.infrastructure.db.repositories.transaction_repository import TransactionRepository
        from app.domain.entities.transaction import TransactionStatus, TransactionType
        txs = await TransactionRepository(session).get_by_user_id(
            user_id=user_id,
            transaction_type=TransactionType.WITHDRAWAL,
            status=TransactionStatus.PENDING,
        )
        assert txs, "Expected at least one pending withdrawal"
        return txs[0]

    @pytest.mark.asyncio
    async def test_pix_data_stored_on_transaction(self, test_session):
        """Pix fields (owner_name→bank_account, pix_key, pix_key_type) are stored."""
        user = await _create_user(test_session)
        plan = await _create_plan(test_session)
        sub = await _create_subscription(
            test_session, user.id, plan.id,
            deposit_count=6, deposits_paid=6,
            status=SubscriptionStatus.COMPLETED,
        )
        await test_session.commit()

        service = InstallmentPaymentService(test_session)
        await service.request_plan_withdrawal(
            RequestPlanWithdrawalInput(
                user_id=user.id,
                subscription_id=sub.id,
                owner_name="João da Silva",
                pix_key_type="cpf",
                pix_key="529.982.247-25",
            )
        )
        await test_session.commit()

        tx = await self._get_withdrawal_tx(test_session, user.id)
        assert tx.bank_account == "João da Silva"
        assert tx.pix_key == "529.982.247-25"
        assert tx.pix_key_type == "cpf"

    @pytest.mark.asyncio
    async def test_subscription_id_stored_on_transaction(self, test_session):
        """transaction.subscription_id links back to the source subscription."""
        user = await _create_user(test_session)
        plan = await _create_plan(test_session)
        sub = await _create_subscription(
            test_session, user.id, plan.id,
            deposit_count=6, deposits_paid=6,
            status=SubscriptionStatus.COMPLETED,
        )
        await test_session.commit()

        service = InstallmentPaymentService(test_session)
        await service.request_plan_withdrawal(
            RequestPlanWithdrawalInput(
                user_id=user.id,
                subscription_id=sub.id,
                owner_name="Maria",
                pix_key_type="email",
                pix_key="maria@test.com",
            )
        )
        await test_session.commit()

        tx = await self._get_withdrawal_tx(test_session, user.id)
        assert tx.subscription_id == sub.id

    @pytest.mark.asyncio
    async def test_notification_created_on_withdrawal_request(self, test_session):
        """A WITHDRAWAL_REQUESTED notification is persisted when a plan withdrawal is requested."""
        from app.infrastructure.db.repositories.notification_repository import NotificationRepository
        from app.domain.entities.notification import NotificationType

        user = await _create_user(test_session)
        plan = await _create_plan(test_session)
        sub = await _create_subscription(
            test_session, user.id, plan.id,
            deposit_count=6, deposits_paid=6,
            status=SubscriptionStatus.COMPLETED,
        )
        await test_session.commit()

        # Count notifications before
        notif_repo = NotificationRepository(test_session)
        before = await notif_repo.get_all(unread_only=False, limit=200, offset=0)
        count_before = len([n for n in before if n.notification_type == NotificationType.WITHDRAWAL_REQUESTED])

        service = InstallmentPaymentService(test_session)
        await service.request_plan_withdrawal(
            RequestPlanWithdrawalInput(
                user_id=user.id,
                subscription_id=sub.id,
                owner_name="Carlos",
                pix_key_type="aleatoria",
                pix_key="abc123-uuid-key",
            )
        )
        await test_session.commit()

        tx = await self._get_withdrawal_tx(test_session, user.id)

        after = await notif_repo.get_all(unread_only=False, limit=200, offset=0)
        withdrawal_notifs = [n for n in after if n.notification_type == NotificationType.WITHDRAWAL_REQUESTED]
        assert len(withdrawal_notifs) == count_before + 1

        # Find notification for this specific transaction
        notif_for_tx = next(
            (n for n in withdrawal_notifs if n.target_id == tx.id), None
        )
        assert notif_for_tx is not None, f"No notification found with target_id={tx.id}"
        assert notif_for_tx.is_read is False


# ---------------------------------------------------------------------------
# Lazy expiration
# ---------------------------------------------------------------------------


class TestLazyExpiration:
    """Tests for lazy expiration of stale pending payments."""

    @pytest.mark.asyncio
    async def test_stale_payment_expired_before_payable_list(self, test_session):
        """Pending payment older than expiration_minutes is expired lazily
        when fetching payable installments, so it no longer blocks the item."""
        from app.infrastructure.db.models import TransactionModel

        user = await _create_user(test_session)
        plan = await _create_plan(test_session)
        sub = await _create_subscription(test_session, user.id, plan.id)
        await _create_wallet(test_session, user.id)
        await test_session.commit()

        service = InstallmentPaymentService(test_session)
        payment = await service.create_payment(
            CreateInstallmentPaymentInput(
                user_id=user.id,
                subscription_ids=[sub.id],
            )
        )

        # Before expiry: installment shows pending_payment_id
        result = await service.get_payable_installments(user.id)
        assert result.installments[0].pending_payment_id == payment.id

        # Simulate time passing: backdate created_at by 31 minutes
        from sqlalchemy import update as sa_update

        await test_session.execute(
            sa_update(TransactionModel)
            .where(TransactionModel.id == payment.id)
            .values(created_at=datetime.utcnow() - timedelta(minutes=31))
        )
        await test_session.commit()

        # After expiry: lazy expiration clears the pending state
        result = await service.get_payable_installments(user.id)
        assert result.installments[0].pending_payment_id is None

    @pytest.mark.asyncio
    async def test_stale_payment_expired_in_history(self, test_session):
        """Stale payments appear as 'expired' in history after lazy expiration."""
        from app.infrastructure.db.models import TransactionModel

        user = await _create_user(test_session)
        plan = await _create_plan(test_session)
        sub = await _create_subscription(test_session, user.id, plan.id)
        await _create_wallet(test_session, user.id)
        await test_session.commit()

        service = InstallmentPaymentService(test_session)
        await service.create_payment(
            CreateInstallmentPaymentInput(
                user_id=user.id,
                subscription_ids=[sub.id],
            )
        )

        # Backdate created_at
        from sqlalchemy import update as sa_update

        await test_session.execute(
            sa_update(TransactionModel)
            .where(TransactionModel.user_id == user.id)
            .values(created_at=datetime.utcnow() - timedelta(minutes=31))
        )
        await test_session.commit()

        result = await service.get_user_history(user.id)
        payment_event = next(
            e for e in result.events if e.event_type == "installment_payment"
        )
        assert payment_event.status == "expired"

    @pytest.mark.asyncio
    async def test_get_payment_expires_stale_payment(self, test_session):
        """get_payment lazily expires a stale pending payment."""
        from app.infrastructure.db.models import TransactionModel

        user = await _create_user(test_session)
        plan = await _create_plan(test_session)
        sub = await _create_subscription(test_session, user.id, plan.id)
        await _create_wallet(test_session, user.id)
        await test_session.commit()

        service = InstallmentPaymentService(test_session)
        created = await service.create_payment(
            CreateInstallmentPaymentInput(
                user_id=user.id,
                subscription_ids=[sub.id],
            )
        )
        assert created.status == "pending"

        # Backdate
        from sqlalchemy import update as sa_update

        await test_session.execute(
            sa_update(TransactionModel)
            .where(TransactionModel.id == created.id)
            .values(created_at=datetime.utcnow() - timedelta(minutes=31))
        )
        await test_session.commit()

        fetched = await service.get_payment(created.id, user.id)
        assert fetched.status == "expired"

    @pytest.mark.asyncio
    async def test_fresh_payment_not_expired(self, test_session):
        """A recently created payment is not expired lazily."""
        user = await _create_user(test_session)
        plan = await _create_plan(test_session)
        sub = await _create_subscription(test_session, user.id, plan.id)
        await _create_wallet(test_session, user.id)
        await test_session.commit()

        service = InstallmentPaymentService(test_session)
        created = await service.create_payment(
            CreateInstallmentPaymentInput(
                user_id=user.id,
                subscription_ids=[sub.id],
            )
        )

        # Immediately fetch — should still be pending
        fetched = await service.get_payment(created.id, user.id)
        assert fetched.status == "pending"

        # Payable list should still show the pending_payment_id
        result = await service.get_payable_installments(user.id)
        assert result.installments[0].pending_payment_id == created.id

    @pytest.mark.asyncio
    async def test_confirmed_payment_not_expired(self, test_session):
        """A confirmed payment is never expired, even if old."""
        from app.infrastructure.db.models import TransactionModel

        user = await _create_user(test_session)
        plan = await _create_plan(test_session)
        sub = await _create_subscription(test_session, user.id, plan.id)
        await _create_wallet(test_session, user.id)
        await test_session.commit()

        service = InstallmentPaymentService(test_session)
        created = await service.create_payment(
            CreateInstallmentPaymentInput(
                user_id=user.id,
                subscription_ids=[sub.id],
            )
        )
        await service.confirm_payment(created.id, "pix_tx_ok")

        # Backdate created_at far in the past
        from sqlalchemy import update as sa_update

        await test_session.execute(
            sa_update(TransactionModel)
            .where(TransactionModel.id == created.id)
            .values(created_at=datetime.utcnow() - timedelta(hours=24))
        )
        await test_session.commit()

        fetched = await service.get_payment(created.id, user.id)
        assert fetched.status == "confirmed"

    @pytest.mark.asyncio
    async def test_expired_payment_allows_new_payment(self, test_session):
        """After a payment expires, user can create a new one for the same sub."""
        from app.infrastructure.db.models import TransactionModel

        user = await _create_user(test_session)
        plan = await _create_plan(test_session)
        sub = await _create_subscription(test_session, user.id, plan.id)
        await _create_wallet(test_session, user.id)
        await test_session.commit()

        service = InstallmentPaymentService(test_session)
        first = await service.create_payment(
            CreateInstallmentPaymentInput(
                user_id=user.id,
                subscription_ids=[sub.id],
            )
        )

        # Backdate first payment past expiration
        from sqlalchemy import update as sa_update

        await test_session.execute(
            sa_update(TransactionModel)
            .where(TransactionModel.id == first.id)
            .values(created_at=datetime.utcnow() - timedelta(minutes=31))
        )
        await test_session.commit()

        # Trigger lazy expiration
        await service.get_payable_installments(user.id)

        # Now creating a new payment should succeed
        second = await service.create_payment(
            CreateInstallmentPaymentInput(
                user_id=user.id,
                subscription_ids=[sub.id],
            )
        )
        assert second.status == "pending"
        assert second.id != first.id
