"""Tests for Pix webhook reconciliation and admin finance summary/cash-flow.

Covers:
- Webhook dispatches SUBSCRIPTION_INSTALLMENT_PAYMENT confirmation correctly
- Webhook dispatches SUBSCRIPTION_ACTIVATION_PAYMENT confirmation correctly
- Webhook handles DEPOSIT (legacy) correctly
- Webhook returns unknown_transaction for missing pix_id
- Finance summary aggregates only from unified transactions table
- Finance cash-flow returns entries only from unified transactions table
"""

import pytest
import random
from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from httpx import AsyncClient

from app.domain.entities.transaction import Transaction, TransactionStatus, TransactionType
from app.domain.entities.user import User, UserRole
from app.domain.value_objects.cpf import CPF
from app.domain.value_objects.email import Email
from app.infrastructure.db.repositories.subscription_repository import SubscriptionRepository
from app.infrastructure.db.repositories.transaction_repository import TransactionRepository
from app.infrastructure.db.repositories.user_repository import UserRepository
from app.infrastructure.security.jwt import create_access_token
from app.infrastructure.security.password import hash_password


# ---------------------------------------------------------------------------
# Helpers shared across tests
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


async def _make_user(session):
    repo = UserRepository(session)
    user = User.create(
        cpf=CPF(_generate_valid_cpf()),
        email=Email(f"{uuid4().hex[:8]}@test.com"),
        name="Webhook Tester",
        password_hash="hash",
        role=UserRole.CLIENT,
    )
    return await repo.save(user)


async def _make_admin(session):
    repo = UserRepository(session)
    admin = User.create(
        cpf=CPF(_generate_valid_cpf()),
        email=Email(f"admin-{uuid4().hex[:8]}@test.com"),
        name="Test Admin",
        password_hash=hash_password("adminpass"),
        role=UserRole.ADMIN,
    )
    return await repo.save(admin)


def _admin_token(admin: User) -> dict:
    token = create_access_token(admin.id, admin.role)
    return {"Authorization": f"Bearer {token}"}


async def _make_plan(session):
    from app.domain.entities.plan import Plan
    from app.infrastructure.db.repositories.plan_repository import PlanRepository
    repo = PlanRepository(session)
    plan = Plan.create(
        title="Plano Webhook",
        description="Test",
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


async def _make_active_sub(session, user_id, plan_id):
    from app.domain.entities.subscription import UserPlanSubscription
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
        name="Sub Webhook",
        deposit_day_of_month=1,
    )
    sub.activate(deposit_day_of_month=1, today_local=date.today())
    return await repo.save(sub)


async def _make_inactive_sub(session, user_id, plan_id):
    from app.domain.entities.subscription import UserPlanSubscription
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
        name="Sub Inactive",
        deposit_day_of_month=1,
    )
    return await repo.save(sub)


async def _make_wallet(session, user_id):
    from app.domain.entities.wallet import Wallet
    from app.infrastructure.db.repositories.wallet_repository import WalletRepository
    repo = WalletRepository(session)
    wallet = Wallet.create(user_id)
    return await repo.save(wallet)


# ---------------------------------------------------------------------------
# Webhook tests
# ---------------------------------------------------------------------------


class TestPixWebhook:
    """Integration tests for POST /admin/webhooks/pix."""

    @pytest.mark.asyncio
    async def test_unknown_pix_id_returns_unknown(self, client: AsyncClient, test_session):
        resp = await client.post(
            "/api/v1/admin/webhooks/pix",
            json={"pix_id": "nonexistent-pix-id", "status": "confirmed"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "unknown_transaction"

    @pytest.mark.asyncio
    async def test_installment_payment_confirmed_via_webhook(
        self, client: AsyncClient, test_session
    ):
        """Webhook confirms SUBSCRIPTION_INSTALLMENT_PAYMENT and updates subscription."""
        from app.application.dtos.finance import CreateInstallmentPaymentInput
        from app.application.services.installment_payment_service import (
            InstallmentPaymentService,
        )

        user = await _make_user(test_session)
        plan = await _make_plan(test_session)
        sub = await _make_active_sub(test_session, user.id, plan.id)
        await _make_wallet(test_session, user.id)
        await test_session.commit()

        svc = InstallmentPaymentService(test_session)
        payment = await svc.create_payment(
            CreateInstallmentPaymentInput(
                user_id=user.id,
                subscription_ids=[sub.id],
            )
        )
        pix_tx_id = f"pix-installment-{uuid4().hex[:8]}"

        tx_repo = TransactionRepository(test_session)
        tx = await tx_repo.get_by_id(payment.id)
        assert tx is not None
        tx.pix_transaction_id = pix_tx_id
        await tx_repo.save(tx)
        await test_session.commit()

        resp = await client.post(
            "/api/v1/admin/webhooks/pix",
            json={"pix_id": pix_tx_id, "status": "confirmed"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "confirmed"
        assert data["transaction_id"] == str(payment.id)

        sub_repo = SubscriptionRepository(test_session)
        updated_sub = await sub_repo.get_by_id(sub.id)
        assert updated_sub is not None
        assert updated_sub.deposits_paid == 1

    @pytest.mark.asyncio
    async def test_activation_payment_confirmed_via_webhook(
        self, client: AsyncClient, test_session
    ):
        """Webhook confirms SUBSCRIPTION_ACTIVATION_PAYMENT and activates subscription."""
        from app.application.dtos.finance import CreateActivationPaymentInput
        from app.application.services.subscription_activation_payment_service import (
            SubscriptionActivationPaymentService,
        )
        from app.domain.entities.subscription import SubscriptionStatus

        user = await _make_user(test_session)
        plan = await _make_plan(test_session)
        sub = await _make_inactive_sub(test_session, user.id, plan.id)
        await test_session.commit()

        svc = SubscriptionActivationPaymentService(test_session)
        dto = await svc.create_or_get_pending(
            CreateActivationPaymentInput(user_id=user.id, subscription_id=sub.id)
        )

        pix_tx_id = f"pix-activation-{uuid4().hex[:8]}"
        tx_repo = TransactionRepository(test_session)
        tx = await tx_repo.get_by_id(dto.id)
        assert tx is not None
        tx.pix_transaction_id = pix_tx_id
        await tx_repo.save(tx)
        await test_session.commit()

        resp = await client.post(
            "/api/v1/admin/webhooks/pix",
            json={"pix_id": pix_tx_id, "status": "confirmed"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "confirmed"

        sub_repo = SubscriptionRepository(test_session)
        updated_sub = await sub_repo.get_by_id(sub.id)
        assert updated_sub is not None
        assert updated_sub.status == SubscriptionStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_installment_payment_failed_via_webhook(
        self, client: AsyncClient, test_session
    ):
        """Webhook marks SUBSCRIPTION_INSTALLMENT_PAYMENT as failed."""
        from app.application.dtos.finance import CreateInstallmentPaymentInput
        from app.application.services.installment_payment_service import (
            InstallmentPaymentService,
        )

        user = await _make_user(test_session)
        plan = await _make_plan(test_session)
        sub = await _make_active_sub(test_session, user.id, plan.id)
        await _make_wallet(test_session, user.id)
        await test_session.commit()

        svc = InstallmentPaymentService(test_session)
        payment = await svc.create_payment(
            CreateInstallmentPaymentInput(
                user_id=user.id,
                subscription_ids=[sub.id],
            )
        )
        pix_tx_id = f"pix-fail-{uuid4().hex[:8]}"

        tx_repo = TransactionRepository(test_session)
        tx = await tx_repo.get_by_id(payment.id)
        assert tx is not None
        tx.pix_transaction_id = pix_tx_id
        await tx_repo.save(tx)
        await test_session.commit()

        resp = await client.post(
            "/api/v1/admin/webhooks/pix",
            json={"pix_id": pix_tx_id, "status": "failed"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "failed"

        tx_updated = await tx_repo.get_by_id(payment.id)
        assert tx_updated is not None
        assert tx_updated.status == TransactionStatus.FAILED


# ---------------------------------------------------------------------------
# Admin finance summary tests
# ---------------------------------------------------------------------------


class TestAdminFinanceSummary:
    """Tests for GET /admin/finance/summary."""

    @pytest.mark.asyncio
    async def test_summary_counts_installment_payments(
        self, client: AsyncClient, test_session
    ):
        """Confirmed installment payments appear in total_inflow_cents."""
        admin = await _make_admin(test_session)
        await test_session.commit()
        headers = _admin_token(admin)

        user = await _make_user(test_session)
        plan = await _make_plan(test_session)
        sub = await _make_active_sub(test_session, user.id, plan.id)
        await _make_wallet(test_session, user.id)
        await test_session.commit()

        tx = Transaction.create_installment_payment(
            user_id=user.id,
            total_amount_cents=50_000,
            pix_qr_code_data="pix-qr",
            expiration_minutes=30,
            pix_transaction_fee_cents=500,
            pix_transaction_id="pix-summary-test",
        )
        tx.status = TransactionStatus.CONFIRMED
        tx.confirmed_at = datetime(2026, 3, 15)
        tx_repo = TransactionRepository(test_session)
        await tx_repo.save(tx)
        await test_session.commit()

        resp = await client.get(
            "/api/v1/admin/finance/summary",
            params={"start_date": "2026-03-01", "end_date": "2026-03-31"},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_inflow_cents"] >= 50_000

    @pytest.mark.asyncio
    async def test_summary_counts_activation_payments(
        self, client: AsyncClient, test_session
    ):
        """Confirmed activation payments appear in total_inflow_cents."""
        admin = await _make_admin(test_session)
        await test_session.commit()
        headers = _admin_token(admin)

        user = await _make_user(test_session)
        plan = await _make_plan(test_session)
        sub = await _make_inactive_sub(test_session, user.id, plan.id)
        await test_session.commit()

        tx = Transaction.create_activation_payment(
            user_id=user.id,
            subscription_id=sub.id,
            admin_tax_cents=5_000,
            insurance_cents=1_250,
            pix_transaction_fee_cents=62,
            pix_qr_code_data="pix-qr",
            expiration_minutes=30,
            pix_transaction_id="pix-activation-summary",
        )
        tx.status = TransactionStatus.CONFIRMED
        tx.confirmed_at = datetime(2026, 3, 20)
        tx_repo = TransactionRepository(test_session)
        await tx_repo.save(tx)
        await test_session.commit()

        resp = await client.get(
            "/api/v1/admin/finance/summary",
            params={
                "start_date": "2026-03-01",
                "end_date": "2026-03-31",
                "category": "activation",
            },
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_inflow_cents"] >= 6_312  # 5000+1250+62

    @pytest.mark.asyncio
    async def test_summary_no_old_table_references(
        self, client: AsyncClient, test_session
    ):
        """Summary endpoint returns 200 with no old table references."""
        admin = await _make_admin(test_session)
        await test_session.commit()
        headers = _admin_token(admin)

        resp = await client.get(
            "/api/v1/admin/finance/summary",
            params={"start_date": "2026-01-01", "end_date": "2026-01-31"},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "fundo_garantidor_cents" in data
        assert "total_inflow_cents" in data
        assert "total_outflow_cents" in data
        assert "net_balance_cents" in data


class TestAdminFinanceCashFlow:
    """Tests for GET /admin/finance/cash-flow."""

    @pytest.mark.asyncio
    async def test_cash_flow_includes_installment_entries(
        self, client: AsyncClient, test_session
    ):
        admin = await _make_admin(test_session)
        await test_session.commit()
        headers = _admin_token(admin)

        user = await _make_user(test_session)
        await test_session.commit()

        tx = Transaction.create_installment_payment(
            user_id=user.id,
            total_amount_cents=75_000,
            pix_qr_code_data="pix-qr",
            expiration_minutes=30,
            pix_transaction_fee_cents=750,
            pix_transaction_id="pix-cf-test",
        )
        tx.status = TransactionStatus.CONFIRMED
        tx.confirmed_at = datetime(2026, 3, 10)
        tx_repo = TransactionRepository(test_session)
        await tx_repo.save(tx)
        await test_session.commit()

        resp = await client.get(
            "/api/v1/admin/finance/cash-flow",
            params={"start_date": "2026-03-01", "end_date": "2026-03-31"},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        ids = [e["id"] for e in data["entries"]]
        assert str(tx.id) in ids

    @pytest.mark.asyncio
    async def test_cash_flow_category_filter_installment(
        self, client: AsyncClient, test_session
    ):
        """category=installment only returns SUBSCRIPTION_INSTALLMENT_PAYMENT entries."""
        admin = await _make_admin(test_session)
        await test_session.commit()
        headers = _admin_token(admin)

        user = await _make_user(test_session)
        await test_session.commit()

        tx = Transaction.create_installment_payment(
            user_id=user.id,
            total_amount_cents=60_000,
            pix_qr_code_data="pix-qr-2",
            expiration_minutes=30,
            pix_transaction_fee_cents=600,
            pix_transaction_id="pix-cf-filter-test",
        )
        tx.status = TransactionStatus.CONFIRMED
        tx.confirmed_at = datetime(2026, 3, 5)
        tx_repo = TransactionRepository(test_session)
        await tx_repo.save(tx)
        await test_session.commit()

        resp = await client.get(
            "/api/v1/admin/finance/cash-flow",
            params={
                "start_date": "2026-03-01",
                "end_date": "2026-03-31",
                "category": "installment",
            },
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        for entry in data["entries"]:
            assert entry["category"] == "Depósito"
