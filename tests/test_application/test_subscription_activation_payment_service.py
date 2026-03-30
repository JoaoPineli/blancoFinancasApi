"""Tests for SubscriptionActivationPaymentService (unified transaction model).

Covers:
- Creating activation payment for inactive subscription
- Idempotency (second call returns same pending payment)
- Confirming payment activates subscription
- Cannot create activation payment for non-inactive subscription
- Pix fee applied correctly; Decimal arithmetic
"""

import pytest
import random
from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.application.dtos.finance import CreateActivationPaymentInput
from app.application.services.subscription_activation_payment_service import (
    SubscriptionActivationPaymentService,
)
from app.domain.constants import calculate_pix_fee
from app.domain.entities.plan import Plan
from app.domain.entities.subscription import SubscriptionStatus, UserPlanSubscription
from app.domain.entities.transaction import TransactionStatus, TransactionType
from app.domain.exceptions import SubscriptionNotFoundError
from app.domain.value_objects.email import Email
from app.infrastructure.db.repositories.plan_repository import PlanRepository
from app.infrastructure.db.repositories.subscription_repository import SubscriptionRepository
from app.infrastructure.db.repositories.transaction_repository import TransactionRepository
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


async def _create_user(session):
    from app.domain.entities.user import User, UserRole
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
        title="Plano Ativação",
        description="Teste",
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


async def _create_inactive_subscription(session, user_id, plan_id) -> UserPlanSubscription:
    repo = SubscriptionRepository(session)
    sub = UserPlanSubscription.create(
        user_id=user_id,
        plan_id=plan_id,
        target_amount_cents=600_000,
        deposit_count=12,
        monthly_amount_cents=50_000,
        admin_tax_value_cents=5_000,
        insurance_percent=Decimal("2.5"),
        guarantee_fund_percent=Decimal("1.0"),
        total_cost_cents=20_000,
        name="Sub Ativação",
        deposit_day_of_month=1,
    )
    # Leave INACTIVE (do not call activate())
    return await repo.save(sub)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCreateOrGetPending:
    """Tests for create_or_get_pending."""

    @pytest.mark.asyncio
    async def test_creates_payment_for_inactive_sub(self, test_session):
        user = await _create_user(test_session)
        plan = await _create_plan(test_session)
        sub = await _create_inactive_subscription(test_session, user.id, plan.id)
        await test_session.commit()

        service = SubscriptionActivationPaymentService(test_session)
        dto = await service.create_or_get_pending(
            CreateActivationPaymentInput(user_id=user.id, subscription_id=sub.id)
        )

        assert dto.user_id == user.id
        assert dto.subscription_id == sub.id
        assert dto.status == "pending"
        assert dto.admin_tax_cents > 0
        assert dto.insurance_cents > 0
        assert dto.pix_transaction_fee_cents >= 0
        assert dto.total_amount_cents == (
            dto.admin_tax_cents + dto.insurance_cents + dto.pix_transaction_fee_cents
        )
        assert dto.pix_qr_code_data is not None

    @pytest.mark.asyncio
    async def test_idempotent_returns_same_payment(self, test_session):
        user = await _create_user(test_session)
        plan = await _create_plan(test_session)
        sub = await _create_inactive_subscription(test_session, user.id, plan.id)
        await test_session.commit()

        service = SubscriptionActivationPaymentService(test_session)
        inp = CreateActivationPaymentInput(user_id=user.id, subscription_id=sub.id)
        dto1 = await service.create_or_get_pending(inp)
        dto2 = await service.create_or_get_pending(inp)

        assert dto1.id == dto2.id

    @pytest.mark.asyncio
    async def test_raises_for_active_subscription(self, test_session):
        from app.domain.exceptions import InvalidPaymentError

        user = await _create_user(test_session)
        plan = await _create_plan(test_session)
        sub = await _create_inactive_subscription(test_session, user.id, plan.id)
        sub_repo = SubscriptionRepository(test_session)
        sub.activate(deposit_day_of_month=1, today_local=date.today())
        await sub_repo.save(sub)
        await test_session.commit()

        service = SubscriptionActivationPaymentService(test_session)
        with pytest.raises(InvalidPaymentError):
            await service.create_or_get_pending(
                CreateActivationPaymentInput(user_id=user.id, subscription_id=sub.id)
            )

    @pytest.mark.asyncio
    async def test_raises_for_unknown_sub(self, test_session):
        user = await _create_user(test_session)
        await test_session.commit()

        service = SubscriptionActivationPaymentService(test_session)
        with pytest.raises(SubscriptionNotFoundError):
            await service.create_or_get_pending(
                CreateActivationPaymentInput(user_id=user.id, subscription_id=uuid4())
            )

    @pytest.mark.asyncio
    async def test_total_uses_decimal_arithmetic_no_float(self, test_session):
        """Verify total = admin_tax + insurance + pix_fee with integer arithmetic."""
        user = await _create_user(test_session)
        plan = await _create_plan(test_session)
        sub = await _create_inactive_subscription(test_session, user.id, plan.id)
        await test_session.commit()

        service = SubscriptionActivationPaymentService(test_session)
        dto = await service.create_or_get_pending(
            CreateActivationPaymentInput(user_id=user.id, subscription_id=sub.id)
        )

        expected_total = dto.admin_tax_cents + dto.insurance_cents + dto.pix_transaction_fee_cents
        assert dto.total_amount_cents == expected_total
        # Verify pix fee is consistent with calculate_pix_fee
        base = dto.admin_tax_cents + dto.insurance_cents
        assert dto.pix_transaction_fee_cents == calculate_pix_fee(base)


class TestConfirmPayment:
    """Tests for confirm_payment."""

    @pytest.mark.asyncio
    async def test_confirms_and_activates_subscription(self, test_session):
        user = await _create_user(test_session)
        plan = await _create_plan(test_session)
        sub = await _create_inactive_subscription(test_session, user.id, plan.id)
        await test_session.commit()

        service = SubscriptionActivationPaymentService(test_session)
        dto = await service.create_or_get_pending(
            CreateActivationPaymentInput(user_id=user.id, subscription_id=sub.id)
        )

        confirmed = await service.confirm_payment(
            payment_id=dto.id,
            pix_transaction_id="pix-test-abc123",
        )

        assert confirmed.status == "confirmed"
        assert confirmed.confirmed_at is not None

        sub_repo = SubscriptionRepository(test_session)
        updated_sub = await sub_repo.get_by_id(sub.id)
        assert updated_sub is not None
        assert updated_sub.status == SubscriptionStatus.ACTIVE
        assert updated_sub.covers_activation_fees is True

    @pytest.mark.asyncio
    async def test_confirm_is_idempotent(self, test_session):
        user = await _create_user(test_session)
        plan = await _create_plan(test_session)
        sub = await _create_inactive_subscription(test_session, user.id, plan.id)
        await test_session.commit()

        service = SubscriptionActivationPaymentService(test_session)
        dto = await service.create_or_get_pending(
            CreateActivationPaymentInput(user_id=user.id, subscription_id=sub.id)
        )
        confirmed1 = await service.confirm_payment(dto.id, "pix-id-1")
        confirmed2 = await service.confirm_payment(dto.id, "pix-id-2")

        assert confirmed1.id == confirmed2.id
        assert confirmed2.status == "confirmed"
        # pix_transaction_id set on first confirm, not overwritten
        assert confirmed2.pix_transaction_id == "pix-id-1"

    @pytest.mark.asyncio
    async def test_transaction_stored_in_unified_table(self, test_session):
        """Activation payment must be stored as SUBSCRIPTION_ACTIVATION_PAYMENT type."""
        user = await _create_user(test_session)
        plan = await _create_plan(test_session)
        sub = await _create_inactive_subscription(test_session, user.id, plan.id)
        await test_session.commit()

        service = SubscriptionActivationPaymentService(test_session)
        dto = await service.create_or_get_pending(
            CreateActivationPaymentInput(user_id=user.id, subscription_id=sub.id)
        )

        tx_repo = TransactionRepository(test_session)
        tx = await tx_repo.get_by_id(dto.id)

        assert tx is not None
        assert tx.transaction_type == TransactionType.SUBSCRIPTION_ACTIVATION_PAYMENT
        assert tx.status == TransactionStatus.PENDING
        assert tx.admin_tax_cents is not None and tx.admin_tax_cents > 0
        assert tx.insurance_cents is not None and tx.insurance_cents > 0
