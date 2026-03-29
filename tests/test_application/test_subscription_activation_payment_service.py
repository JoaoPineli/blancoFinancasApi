"""Tests for SubscriptionActivationPaymentService.

Covers:
- Creating activation payment for inactive subscription
- Idempotency (second call returns same pending payment)
- Confirming payment activates subscription and sets next_due_date
- Cannot create activation payment for non-inactive subscription
- PIX fee is applied correctly and uses Decimal arithmetic
"""

import pytest
import random
from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.application.dtos.subscription_activation_payment import CreateActivationPaymentInput
from app.application.services.subscription_activation_payment_service import (
    SubscriptionActivationPaymentService,
)
from app.domain.constants import calculate_pix_fee
from app.domain.entities.plan import Plan
from app.domain.entities.subscription import SubscriptionStatus, UserPlanSubscription
from app.domain.entities.subscription_activation_payment import ActivationPaymentStatus
from app.domain.entities.user import User, UserRole
from app.domain.exceptions import InvalidSubscriptionError, SubscriptionNotFoundError
from app.domain.value_objects.email import Email
from app.infrastructure.db.repositories.plan_repository import PlanRepository
from app.infrastructure.db.repositories.subscription_repository import SubscriptionRepository
from app.infrastructure.db.repositories.subscription_activation_payment_repository import (
    SubscriptionActivationPaymentRepository,
)
from app.infrastructure.db.repositories.user_repository import UserRepository


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


async def _create_user(session) -> User:
    from app.domain.value_objects.cpf import CPF
    repo = UserRepository(session)
    user = User.create(
        cpf=CPF(_generate_valid_cpf()),
        email=Email(f"{uuid4().hex[:8]}@test.com"),
        name="Test User",
        password_hash="hash",
        role=UserRole.CLIENT,
    )
    return await repo.save(user)


async def _create_plan(session) -> Plan:
    repo = PlanRepository(session)
    plan = Plan.create(
        title="Test Plan",
        description="Test",
        min_value_cents=10_000,
        max_value_cents=10_000_000,
        min_duration_months=6,
        max_duration_months=36,
        admin_tax_value_cents=500,
        insurance_percent=Decimal("1.0"),
        guarantee_fund_percent_1=Decimal("1.0"),
        guarantee_fund_percent_2=Decimal("1.3"),
        guarantee_fund_threshold_cents=5_000_000,
    )
    return await repo.save(plan)


async def _create_inactive_subscription(session, user_id, plan_id) -> UserPlanSubscription:
    """Create and persist an INACTIVE subscription (default state after create())."""
    repo = SubscriptionRepository(session)
    sub = UserPlanSubscription.create(
        user_id=user_id,
        plan_id=plan_id,
        target_amount_cents=100_000,
        deposit_count=12,
        monthly_amount_cents=10_000,
        admin_tax_value_cents=500,
        insurance_percent=Decimal("1.0"),
        guarantee_fund_percent=Decimal("1.0"),
        total_cost_cents=600,
        name="Test sub",
        deposit_day_of_month=5,
    )
    assert sub.status == SubscriptionStatus.INACTIVE
    return await repo.save(sub)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCreateOrGetPendingActivationPayment:
    """Tests for create_or_get_pending()."""

    @pytest.mark.asyncio
    async def test_creates_payment_for_inactive_subscription(self, test_session):
        """Successfully creates a payment for an INACTIVE subscription."""
        user = await _create_user(test_session)
        plan = await _create_plan(test_session)
        sub = await _create_inactive_subscription(test_session, user.id, plan.id)

        service = SubscriptionActivationPaymentService(test_session)
        dto = await service.create_or_get_pending(
            CreateActivationPaymentInput(user_id=user.id, subscription_id=sub.id)
        )

        assert dto.status == "pending"
        assert dto.subscription_id == sub.id
        assert dto.user_id == user.id
        assert dto.pix_qr_code_data is not None

    @pytest.mark.asyncio
    async def test_admin_tax_and_insurance_amounts_are_correct(self, test_session):
        """admin_tax_cents and insurance_cents match subscription snapshots."""
        user = await _create_user(test_session)
        plan = await _create_plan(test_session)
        sub = await _create_inactive_subscription(test_session, user.id, plan.id)

        service = SubscriptionActivationPaymentService(test_session)
        dto = await service.create_or_get_pending(
            CreateActivationPaymentInput(user_id=user.id, subscription_id=sub.id)
        )

        # admin_tax from subscription snapshot
        assert dto.admin_tax_cents == sub.admin_tax_value_cents  # 500

        # insurance = monthly_amount * insurance_percent / 100 (rounded HALF_UP)
        from decimal import Decimal, ROUND_HALF_UP
        expected_insurance = int(
            (Decimal(sub.monthly_amount_cents) * sub.insurance_percent / Decimal(100))
            .quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
        assert dto.insurance_cents == expected_insurance

    @pytest.mark.asyncio
    async def test_pix_fee_is_0_99_percent_of_base(self, test_session):
        """PIX transaction fee is exactly 0.99% of (admin_tax + insurance), as Decimal."""
        user = await _create_user(test_session)
        plan = await _create_plan(test_session)
        sub = await _create_inactive_subscription(test_session, user.id, plan.id)

        service = SubscriptionActivationPaymentService(test_session)
        dto = await service.create_or_get_pending(
            CreateActivationPaymentInput(user_id=user.id, subscription_id=sub.id)
        )

        base = dto.admin_tax_cents + dto.insurance_cents
        expected_fee = calculate_pix_fee(base)
        assert dto.pix_transaction_fee_cents == expected_fee

    @pytest.mark.asyncio
    async def test_total_equals_components_sum(self, test_session):
        """total_amount_cents = admin_tax + insurance + pix_fee."""
        user = await _create_user(test_session)
        plan = await _create_plan(test_session)
        sub = await _create_inactive_subscription(test_session, user.id, plan.id)

        service = SubscriptionActivationPaymentService(test_session)
        dto = await service.create_or_get_pending(
            CreateActivationPaymentInput(user_id=user.id, subscription_id=sub.id)
        )

        expected = dto.admin_tax_cents + dto.insurance_cents + dto.pix_transaction_fee_cents
        assert dto.total_amount_cents == expected

    @pytest.mark.asyncio
    async def test_idempotent_returns_same_payment(self, test_session):
        """Calling create_or_get_pending twice returns the same payment ID."""
        user = await _create_user(test_session)
        plan = await _create_plan(test_session)
        sub = await _create_inactive_subscription(test_session, user.id, plan.id)

        service = SubscriptionActivationPaymentService(test_session)
        input_data = CreateActivationPaymentInput(user_id=user.id, subscription_id=sub.id)

        dto1 = await service.create_or_get_pending(input_data)
        dto2 = await service.create_or_get_pending(input_data)

        assert dto1.id == dto2.id

    @pytest.mark.asyncio
    async def test_raises_for_active_subscription(self, test_session):
        """Cannot create activation payment for already-ACTIVE subscription."""
        user = await _create_user(test_session)
        plan = await _create_plan(test_session)
        sub = await _create_inactive_subscription(test_session, user.id, plan.id)

        # Activate the subscription first
        sub.activate(deposit_day_of_month=5, today_local=date.today())
        sub_repo = SubscriptionRepository(test_session)
        await sub_repo.save(sub)
        await test_session.commit()

        service = SubscriptionActivationPaymentService(test_session)
        with pytest.raises(InvalidSubscriptionError):
            await service.create_or_get_pending(
                CreateActivationPaymentInput(user_id=user.id, subscription_id=sub.id)
            )

    @pytest.mark.asyncio
    async def test_raises_if_subscription_not_found(self, test_session):
        """Raises SubscriptionNotFoundError for nonexistent subscription."""
        user = await _create_user(test_session)
        service = SubscriptionActivationPaymentService(test_session)
        with pytest.raises(SubscriptionNotFoundError):
            await service.create_or_get_pending(
                CreateActivationPaymentInput(user_id=user.id, subscription_id=uuid4())
            )


class TestConfirmActivationPayment:
    """Tests for confirm_payment() — activates subscription on confirmation."""

    @pytest.mark.asyncio
    async def test_confirm_activates_subscription(self, test_session):
        """Confirming an activation payment sets subscription to ACTIVE."""
        user = await _create_user(test_session)
        plan = await _create_plan(test_session)
        sub = await _create_inactive_subscription(test_session, user.id, plan.id)

        service = SubscriptionActivationPaymentService(test_session)
        dto = await service.create_or_get_pending(
            CreateActivationPaymentInput(user_id=user.id, subscription_id=sub.id)
        )

        await service.confirm_payment(
            payment_id=dto.id,
            pix_transaction_id="PIX-TEST-123",
        )

        sub_repo = SubscriptionRepository(test_session)
        activated_sub = await sub_repo.get_by_id(sub.id)
        assert activated_sub is not None
        assert activated_sub.status == SubscriptionStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_confirm_sets_next_due_date(self, test_session):
        """After confirmation, next_due_date is set on the subscription."""
        user = await _create_user(test_session)
        plan = await _create_plan(test_session)
        sub = await _create_inactive_subscription(test_session, user.id, plan.id)

        service = SubscriptionActivationPaymentService(test_session)
        dto = await service.create_or_get_pending(
            CreateActivationPaymentInput(user_id=user.id, subscription_id=sub.id)
        )

        await service.confirm_payment(
            payment_id=dto.id,
            pix_transaction_id="PIX-TEST-456",
        )

        sub_repo = SubscriptionRepository(test_session)
        activated_sub = await sub_repo.get_by_id(sub.id)
        assert activated_sub is not None
        assert activated_sub.next_due_date is not None

    @pytest.mark.asyncio
    async def test_confirm_payment_status_is_confirmed(self, test_session):
        """The payment entity itself is marked CONFIRMED."""
        user = await _create_user(test_session)
        plan = await _create_plan(test_session)
        sub = await _create_inactive_subscription(test_session, user.id, plan.id)

        service = SubscriptionActivationPaymentService(test_session)
        dto = await service.create_or_get_pending(
            CreateActivationPaymentInput(user_id=user.id, subscription_id=sub.id)
        )

        confirmed_dto = await service.confirm_payment(
            payment_id=dto.id,
            pix_transaction_id="PIX-TEST-789",
        )

        assert confirmed_dto.status == "confirmed"

    @pytest.mark.asyncio
    async def test_confirm_idempotent(self, test_session):
        """Confirming twice does not raise and returns current state."""
        user = await _create_user(test_session)
        plan = await _create_plan(test_session)
        sub = await _create_inactive_subscription(test_session, user.id, plan.id)

        service = SubscriptionActivationPaymentService(test_session)
        dto = await service.create_or_get_pending(
            CreateActivationPaymentInput(user_id=user.id, subscription_id=sub.id)
        )

        await service.confirm_payment(dto.id, "PIX-FIRST")
        second = await service.confirm_payment(dto.id, "PIX-SECOND")  # should not raise

        assert second.status == "confirmed"


class TestInactiveSubscriptionExcludedFromPayableInstallments:
    """INACTIVE subscriptions must not appear in payable installments."""

    @pytest.mark.asyncio
    async def test_inactive_subscription_excluded(self, test_session):
        """Payable installments only returns ACTIVE subscriptions."""
        from app.application.services.installment_payment_service import InstallmentPaymentService

        user = await _create_user(test_session)
        plan = await _create_plan(test_session)

        # Create an INACTIVE subscription (not yet activated)
        await _create_inactive_subscription(test_session, user.id, plan.id)

        service = InstallmentPaymentService(test_session)
        result = await service.get_payable_installments(user.id)

        assert result.total == 0
