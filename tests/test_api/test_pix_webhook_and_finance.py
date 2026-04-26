"""Tests for Pix webhook reconciliation and admin finance summary/cash-flow.

Covers:
- Webhook dispatches SUBSCRIPTION_INSTALLMENT_PAYMENT confirmation correctly
- Webhook dispatches SUBSCRIPTION_ACTIVATION_PAYMENT confirmation correctly
- Webhook handles DEPOSIT (legacy) correctly
- Webhook returns unknown_transaction for missing pix_id
- Finance summary aggregates only from unified transactions table
- Finance cash-flow returns entries only from unified transactions table
"""

import hashlib
import hmac as _hmac
import time
import pytest
import random
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
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

        pix_tx_id = f"pix-installment-{uuid4().hex[:8]}"
        _fake_create_resp = {
            "id": pix_tx_id,
            "transactions": {"payments": [{"payment_method": {"qr_code": "qr"}}]},
        }
        with patch("app.infrastructure.payment.pix_gateway.httpx.AsyncClient") as _mock:
            _m = AsyncMock()
            _mock.return_value.__aenter__.return_value = _m
            _p = MagicMock()
            _p.status_code = 200
            _p.json.return_value = _fake_create_resp
            _p.raise_for_status = MagicMock()
            _m.post = AsyncMock(return_value=_p)

            svc = InstallmentPaymentService(test_session)
            payment = await svc.create_payment(
                CreateInstallmentPaymentInput(
                    user_id=user.id,
                    subscription_ids=[sub.id],
                )
            )

        tx_repo = TransactionRepository(test_session)
        tx = await tx_repo.get_by_id(payment.id)
        assert tx is not None
        # pix_transaction_id already set to pix_tx_id via mock
        assert tx.pix_transaction_id == pix_tx_id
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

        pix_tx_id = f"pix-activation-{uuid4().hex[:8]}"
        _fake_create_resp = {
            "id": pix_tx_id,
            "transactions": {"payments": [{"payment_method": {"qr_code": "qr"}}]},
        }
        with patch("app.infrastructure.payment.pix_gateway.httpx.AsyncClient") as _mock:
            _m = AsyncMock()
            _mock.return_value.__aenter__.return_value = _m
            _p = MagicMock()
            _p.status_code = 200
            _p.json.return_value = _fake_create_resp
            _p.raise_for_status = MagicMock()
            _m.post = AsyncMock(return_value=_p)

            svc = SubscriptionActivationPaymentService(test_session)
            dto = await svc.create_or_get_pending(
                CreateActivationPaymentInput(user_id=user.id, subscription_id=sub.id)
            )

        tx_repo = TransactionRepository(test_session)
        tx = await tx_repo.get_by_id(dto.id)
        assert tx is not None
        assert tx.pix_transaction_id == pix_tx_id
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

        pix_tx_id = f"pix-fail-{uuid4().hex[:8]}"
        _fake_create_resp = {
            "id": pix_tx_id,
            "transactions": {"payments": [{"payment_method": {"qr_code": "qr"}}]},
        }
        with patch("app.infrastructure.payment.pix_gateway.httpx.AsyncClient") as _mock:
            _m = AsyncMock()
            _mock.return_value.__aenter__.return_value = _m
            _p = MagicMock()
            _p.status_code = 200
            _p.json.return_value = _fake_create_resp
            _p.raise_for_status = MagicMock()
            _m.post = AsyncMock(return_value=_p)

            svc = InstallmentPaymentService(test_session)
            payment = await svc.create_payment(
                CreateInstallmentPaymentInput(
                    user_id=user.id,
                    subscription_ids=[sub.id],
                )
            )

        tx_repo = TransactionRepository(test_session)
        tx = await tx_repo.get_by_id(payment.id)
        assert tx is not None
        assert tx.pix_transaction_id == pix_tx_id
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


# ---------------------------------------------------------------------------
# Helpers for Mercado Pago webhook tests
# ---------------------------------------------------------------------------


def _mp_signature(order_id: str, request_id: str, secret: str | None = None) -> str:
    """Build a valid x-signature header value using the same secret as the server."""
    if secret is None:
        from app.infrastructure.config import get_settings
        secret = get_settings().mercadopago_webhook_secret.get_secret_value()
    ts = str(int(time.time()))
    manifest = f"id:{order_id.lower()};request-id:{request_id};ts:{ts};"
    v1 = _hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()
    return f"ts={ts},v1={v1}"


def _mp_order_response(
    order_id: str,
    external_reference: str,
    amount_str: str,
    order_status: str = "closed",
    payment_status: str = "processed",
    qr_code: str = "00020101021226870014br.gov.bcb.pix",
) -> dict:
    """Build a minimal MP GET /v1/orders/{id} response."""
    return {
        "id": order_id,
        "type": "online",
        "status": order_status,
        "total_amount": amount_str,
        "external_reference": external_reference,
        "transactions": {
            "payments": [
                {
                    "status": payment_status,
                    "amount": amount_str,
                    "payment_method": {
                        "id": "pix",
                        "type": "bank_transfer",
                        "qr_code": qr_code,
                        "qr_code_base64": "base64data==",
                    },
                }
            ]
        },
    }


def _mp_headers(order_id: str, request_id: str | None = None) -> dict:
    rid = request_id or str(uuid4())
    sig = _mp_signature(order_id, rid)
    return {
        "x-signature": sig,
        "x-request-id": rid,
    }


# ---------------------------------------------------------------------------
# Mercado Pago webhook tests
# ---------------------------------------------------------------------------


class TestMercadoPagoWebhook:
    """Integration tests for POST /admin/webhooks/mercadopago."""

    MP_URL = "/api/v1/admin/webhooks/mercadopago"

    @pytest.mark.asyncio
    async def test_missing_signature_returns_401(self, client: AsyncClient, test_session):
        """No x-signature header → 401."""
        order_id = "mp-order-001"
        resp = await client.post(
            self.MP_URL,
            params={"data.id": order_id},
            json={},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_signature_returns_401(self, client: AsyncClient, test_session):
        """Wrong HMAC hash → 401 (enforced outside development mode)."""
        from app.infrastructure.config import get_settings
        real_settings = get_settings()

        order_id = "mp-order-002"
        rid = str(uuid4())
        ts = str(int(time.time()))
        bad_sig = f"ts={ts},v1=deadbeef0000000000000000000000000000000000000000000000000000dead"

        mock_cfg = MagicMock()
        mock_cfg.environment = "production"
        mock_cfg.mercadopago_webhook_tolerance_seconds = 300
        mock_cfg.mercadopago_webhook_secret.get_secret_value.return_value = (
            real_settings.mercadopago_webhook_secret.get_secret_value()
        )
        with patch("app.infrastructure.config.get_settings", return_value=mock_cfg):
            resp = await client.post(
                self.MP_URL,
                params={"data.id": order_id},
                json={},
                headers={"x-signature": bad_sig, "x-request-id": rid},
            )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_valid_signature_unknown_order_id(self, client: AsyncClient, test_session):
        """Valid signature but no matching transaction → unknown_transaction."""
        order_id = f"mp-unknown-{uuid4().hex[:8]}"
        headers = _mp_headers(order_id)

        order_resp = _mp_order_response(
            order_id=order_id,
            external_reference=uuid4().hex,
            amount_str="500.00",
        )

        with patch("app.infrastructure.payment.pix_gateway.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_get = MagicMock()
            mock_get.json.return_value = order_resp
            mock_get.raise_for_status = MagicMock()
            mock_http.get = AsyncMock(return_value=mock_get)

            resp = await client.post(
                self.MP_URL,
                params={"data.id": order_id},
                json={},
                headers=headers,
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "unknown_transaction"

    @pytest.mark.asyncio
    async def test_confirmed_installment_via_mp_webhook(
        self, client: AsyncClient, test_session
    ):
        """Confirmed MP order dispatches SUBSCRIPTION_INSTALLMENT_PAYMENT confirmation."""
        from app.application.dtos.finance import CreateInstallmentPaymentInput
        from app.application.services.installment_payment_service import (
            InstallmentPaymentService,
        )

        user = await _make_user(test_session)
        plan = await _make_plan(test_session)
        sub = await _make_active_sub(test_session, user.id, plan.id)
        await _make_wallet(test_session, user.id)
        await test_session.commit()

        # Create payment (mock MP gateway call)
        mp_order_id = f"mp-inst-{uuid4().hex[:12]}"
        qr_code = "00020101qr-code-string"
        create_resp = _mp_order_response(
            order_id=mp_order_id,
            external_reference=str(uuid4()),
            amount_str="500.99",
            qr_code=qr_code,
        )
        with patch("app.infrastructure.payment.pix_gateway.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_post = MagicMock()
            mock_post.status_code = 200
            mock_post.json.return_value = create_resp
            mock_post.raise_for_status = MagicMock()
            mock_http.post = AsyncMock(return_value=mock_post)

            svc = InstallmentPaymentService(test_session)
            payment = await svc.create_payment(
                CreateInstallmentPaymentInput(
                    user_id=user.id,
                    subscription_ids=[sub.id],
                )
            )

        assert payment.pix_transaction_id == mp_order_id
        assert payment.pix_qr_code_data == qr_code

        # Craft webhook with amount that matches actual transaction
        tx_repo = TransactionRepository(test_session)
        tx = await tx_repo.get_by_id(payment.id)
        assert tx is not None
        actual_amount_str = str(
            (Decimal(tx.amount_cents) / Decimal(100)).quantize(Decimal("0.01"))
        )

        headers = _mp_headers(mp_order_id)
        order_resp = _mp_order_response(
            order_id=mp_order_id,
            external_reference=tx.id.hex,
            amount_str=actual_amount_str,
        )

        with patch("app.infrastructure.payment.pix_gateway.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_get = MagicMock()
            mock_get.json.return_value = order_resp
            mock_get.raise_for_status = MagicMock()
            mock_http.get = AsyncMock(return_value=mock_get)

            resp = await client.post(
                self.MP_URL,
                params={"data.id": mp_order_id},
                json={},
                headers=headers,
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
    async def test_confirmed_activation_via_mp_webhook(
        self, client: AsyncClient, test_session
    ):
        """Confirmed MP order dispatches SUBSCRIPTION_ACTIVATION_PAYMENT confirmation."""
        from app.application.dtos.finance import CreateActivationPaymentInput
        from app.application.services.subscription_activation_payment_service import (
            SubscriptionActivationPaymentService,
        )
        from app.domain.entities.subscription import SubscriptionStatus

        user = await _make_user(test_session)
        plan = await _make_plan(test_session)
        sub = await _make_inactive_sub(test_session, user.id, plan.id)
        await test_session.commit()

        mp_order_id = f"mp-act-{uuid4().hex[:12]}"
        create_resp = _mp_order_response(
            order_id=mp_order_id,
            external_reference=str(uuid4()),
            amount_str="100.00",
        )
        with patch("app.infrastructure.payment.pix_gateway.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_post = MagicMock()
            mock_post.status_code = 200
            mock_post.json.return_value = create_resp
            mock_post.raise_for_status = MagicMock()
            mock_http.post = AsyncMock(return_value=mock_post)

            svc = SubscriptionActivationPaymentService(test_session)
            dto = await svc.create_or_get_pending(
                CreateActivationPaymentInput(user_id=user.id, subscription_id=sub.id)
            )

        assert dto.pix_transaction_id == mp_order_id

        tx_repo = TransactionRepository(test_session)
        tx = await tx_repo.get_by_id(dto.id)
        assert tx is not None
        actual_amount_str = str(
            (Decimal(tx.amount_cents) / Decimal(100)).quantize(Decimal("0.01"))
        )

        headers = _mp_headers(mp_order_id)
        order_resp = _mp_order_response(
            order_id=mp_order_id,
            external_reference=tx.id.hex,
            amount_str=actual_amount_str,
        )

        with patch("app.infrastructure.payment.pix_gateway.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_get = MagicMock()
            mock_get.json.return_value = order_resp
            mock_get.raise_for_status = MagicMock()
            mock_http.get = AsyncMock(return_value=mock_get)

            resp = await client.post(
                self.MP_URL,
                params={"data.id": mp_order_id},
                json={},
                headers=headers,
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "confirmed"

        sub_repo = SubscriptionRepository(test_session)
        updated = await sub_repo.get_by_id(sub.id)
        assert updated is not None
        assert updated.status == SubscriptionStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_idempotent_webhook_already_confirmed(
        self, client: AsyncClient, test_session
    ):
        """Second webhook delivery on already-confirmed transaction returns already_confirmed."""
        from app.application.dtos.finance import CreateInstallmentPaymentInput
        from app.application.services.installment_payment_service import (
            InstallmentPaymentService,
        )

        user = await _make_user(test_session)
        plan = await _make_plan(test_session)
        sub = await _make_active_sub(test_session, user.id, plan.id)
        await _make_wallet(test_session, user.id)
        await test_session.commit()

        mp_order_id = f"mp-idem-{uuid4().hex[:12]}"
        create_resp = _mp_order_response(
            order_id=mp_order_id,
            external_reference=str(uuid4()),
            amount_str="100.00",
        )
        with patch("app.infrastructure.payment.pix_gateway.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_post = MagicMock()
            mock_post.status_code = 200
            mock_post.json.return_value = create_resp
            mock_post.raise_for_status = MagicMock()
            mock_http.post = AsyncMock(return_value=mock_post)

            svc = InstallmentPaymentService(test_session)
            payment = await svc.create_payment(
                CreateInstallmentPaymentInput(
                    user_id=user.id,
                    subscription_ids=[sub.id],
                )
            )

        tx_repo = TransactionRepository(test_session)
        tx = await tx_repo.get_by_id(payment.id)
        actual_amount_str = str(
            (Decimal(tx.amount_cents) / Decimal(100)).quantize(Decimal("0.01"))
        )

        headers = _mp_headers(mp_order_id)
        order_resp = _mp_order_response(
            order_id=mp_order_id,
            external_reference=tx.id.hex,
            amount_str=actual_amount_str,
        )

        def _mock_get():
            mock_cls2 = patch("app.infrastructure.payment.pix_gateway.httpx.AsyncClient")
            mock_cls2_start = mock_cls2.start()
            mock_http2 = AsyncMock()
            mock_cls2_start.return_value.__aenter__.return_value = mock_http2
            mock_get2 = MagicMock()
            mock_get2.json.return_value = order_resp
            mock_get2.raise_for_status = MagicMock()
            mock_http2.get = AsyncMock(return_value=mock_get2)
            return mock_cls2, mock_cls2_start

        with patch("app.infrastructure.payment.pix_gateway.httpx.AsyncClient") as mock_cls2:
            mock_http2 = AsyncMock()
            mock_cls2.return_value.__aenter__.return_value = mock_http2
            mock_get2 = MagicMock()
            mock_get2.json.return_value = order_resp
            mock_get2.raise_for_status = MagicMock()
            mock_http2.get = AsyncMock(return_value=mock_get2)

            resp1 = await client.post(
                self.MP_URL,
                params={"data.id": mp_order_id},
                json={},
                headers=headers,
            )
        assert resp1.json()["status"] == "confirmed"

        # Second delivery
        headers2 = _mp_headers(mp_order_id)
        with patch("app.infrastructure.payment.pix_gateway.httpx.AsyncClient") as mock_cls3:
            mock_http3 = AsyncMock()
            mock_cls3.return_value.__aenter__.return_value = mock_http3
            mock_get3 = MagicMock()
            mock_get3.json.return_value = order_resp
            mock_get3.raise_for_status = MagicMock()
            mock_http3.get = AsyncMock(return_value=mock_get3)

            resp2 = await client.post(
                self.MP_URL,
                params={"data.id": mp_order_id},
                json={},
                headers=headers2,
            )
        assert resp2.status_code == 200
        assert resp2.json()["status"] == "already_confirmed"

    @pytest.mark.asyncio
    async def test_expired_order_marks_transaction_expired(
        self, client: AsyncClient, test_session
    ):
        """MP order with status=expired marks the transaction as EXPIRED."""
        from app.domain.entities.transaction import Transaction, TransactionStatus

        user = await _make_user(test_session)
        await test_session.commit()

        mp_order_id = f"mp-exp-{uuid4().hex[:12]}"
        tx = Transaction.create_installment_payment(
            user_id=user.id,
            total_amount_cents=50_000,
            pix_qr_code_data="qr",
            expiration_minutes=30,
            pix_transaction_fee_cents=0,
            pix_transaction_id=mp_order_id,
        )
        tx_repo = TransactionRepository(test_session)
        await tx_repo.save(tx)
        await test_session.commit()

        amount_str = str(
            (Decimal(tx.amount_cents) / Decimal(100)).quantize(Decimal("0.01"))
        )
        headers = _mp_headers(mp_order_id)
        order_resp = _mp_order_response(
            order_id=mp_order_id,
            external_reference=tx.id.hex,
            amount_str=amount_str,
            order_status="expired",
            payment_status="pending",
        )

        with patch("app.infrastructure.payment.pix_gateway.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_get = MagicMock()
            mock_get.json.return_value = order_resp
            mock_get.raise_for_status = MagicMock()
            mock_http.get = AsyncMock(return_value=mock_get)

            resp = await client.post(
                self.MP_URL,
                params={"data.id": mp_order_id},
                json={},
                headers=headers,
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "expired"

        updated = await tx_repo.get_by_id(tx.id)
        assert updated is not None
        assert updated.status == TransactionStatus.EXPIRED

    @pytest.mark.asyncio
    async def test_failed_payment_marks_transaction_failed(
        self, client: AsyncClient, test_session
    ):
        """MP payment with status=failed marks the transaction as FAILED."""
        from app.domain.entities.transaction import Transaction, TransactionStatus

        user = await _make_user(test_session)
        await test_session.commit()

        mp_order_id = f"mp-fail-{uuid4().hex[:12]}"
        tx = Transaction.create_installment_payment(
            user_id=user.id,
            total_amount_cents=30_000,
            pix_qr_code_data="qr",
            expiration_minutes=30,
            pix_transaction_fee_cents=0,
            pix_transaction_id=mp_order_id,
        )
        tx_repo = TransactionRepository(test_session)
        await tx_repo.save(tx)
        await test_session.commit()

        amount_str = str(
            (Decimal(tx.amount_cents) / Decimal(100)).quantize(Decimal("0.01"))
        )
        headers = _mp_headers(mp_order_id)
        order_resp = _mp_order_response(
            order_id=mp_order_id,
            external_reference=tx.id.hex,
            amount_str=amount_str,
            order_status="open",
            payment_status="failed",
        )

        with patch("app.infrastructure.payment.pix_gateway.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_get = MagicMock()
            mock_get.json.return_value = order_resp
            mock_get.raise_for_status = MagicMock()
            mock_http.get = AsyncMock(return_value=mock_get)

            resp = await client.post(
                self.MP_URL,
                params={"data.id": mp_order_id},
                json={},
                headers=headers,
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "failed"

        updated = await tx_repo.get_by_id(tx.id)
        assert updated is not None
        assert updated.status == TransactionStatus.FAILED

    @pytest.mark.asyncio
    async def test_amount_mismatch_rejected(self, client: AsyncClient, test_session):
        """Order amount that doesn't match transaction amount is rejected with amount_mismatch."""
        from app.domain.entities.transaction import Transaction

        user = await _make_user(test_session)
        await test_session.commit()

        mp_order_id = f"mp-mismatch-{uuid4().hex[:8]}"
        tx = Transaction.create_installment_payment(
            user_id=user.id,
            total_amount_cents=50_000,  # R$ 500.00
            pix_qr_code_data="qr",
            expiration_minutes=30,
            pix_transaction_fee_cents=0,
            pix_transaction_id=mp_order_id,
        )
        tx_repo = TransactionRepository(test_session)
        await tx_repo.save(tx)
        await test_session.commit()

        headers = _mp_headers(mp_order_id)
        order_resp = _mp_order_response(
            order_id=mp_order_id,
            external_reference=tx.id.hex,
            amount_str="123.00",  # Wrong amount
        )

        with patch("app.infrastructure.payment.pix_gateway.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_get = MagicMock()
            mock_get.json.return_value = order_resp
            mock_get.raise_for_status = MagicMock()
            mock_http.get = AsyncMock(return_value=mock_get)

            resp = await client.post(
                self.MP_URL,
                params={"data.id": mp_order_id},
                json={},
                headers=headers,
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "amount_mismatch"

    @pytest.mark.asyncio
    async def test_fallback_reconciliation_via_external_reference(
        self, client: AsyncClient, test_session
    ):
        """Transaction located via external_reference when pix_transaction_id is not yet set."""
        from app.domain.entities.transaction import Transaction, TransactionStatus

        user = await _make_user(test_session)
        await test_session.commit()

        # Transaction with NO pix_transaction_id yet
        tx = Transaction.create_installment_payment(
            user_id=user.id,
            total_amount_cents=20_000,
            pix_qr_code_data="qr",
            expiration_minutes=30,
            pix_transaction_fee_cents=0,
            pix_transaction_id=None,
        )
        tx_repo = TransactionRepository(test_session)
        await tx_repo.save(tx)
        await test_session.commit()

        mp_order_id = f"mp-fallback-{uuid4().hex[:12]}"
        amount_str = str(
            (Decimal(tx.amount_cents) / Decimal(100)).quantize(Decimal("0.01"))
        )
        headers = _mp_headers(mp_order_id)
        # external_reference = tx.id.hex (the fallback path)
        order_resp = _mp_order_response(
            order_id=mp_order_id,
            external_reference=tx.id.hex,
            amount_str=amount_str,
            order_status="closed",
            payment_status="processed",
        )

        with patch("app.infrastructure.payment.pix_gateway.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_get = MagicMock()
            mock_get.json.return_value = order_resp
            mock_get.raise_for_status = MagicMock()
            mock_http.get = AsyncMock(return_value=mock_get)

            resp = await client.post(
                self.MP_URL,
                params={"data.id": mp_order_id},
                json={},
                headers=headers,
            )

        assert resp.status_code == 200
        # Ignored because tx type is SUBSCRIPTION_INSTALLMENT_PAYMENT but
        # confirm_payment should succeed here; just verify the heal happened
        result = resp.json()
        assert result["status"] in ("confirmed", "already_confirmed")

        healed = await tx_repo.get_by_id(tx.id)
        assert healed is not None
        assert healed.pix_transaction_id == mp_order_id


# ---------------------------------------------------------------------------
# Service-level tests: create_payment stores real MP data (no temp_id)
# ---------------------------------------------------------------------------


class TestInstallmentServiceStoresMPData:
    """Unit-level service tests verifying MP order_id is persisted (not a temp_id)."""

    @pytest.mark.asyncio
    async def test_create_payment_stores_mp_order_id_and_qr_code(self, test_session):
        """After create_payment, pix_transaction_id == MP order_id and qr_code is real."""
        from app.application.dtos.finance import CreateInstallmentPaymentInput
        from app.application.services.installment_payment_service import (
            InstallmentPaymentService,
        )
        from app.infrastructure.db.repositories.transaction_repository import (
            TransactionRepository,
        )

        user = await _make_user(test_session)
        plan = await _make_plan(test_session)
        sub = await _make_active_sub(test_session, user.id, plan.id)
        await _make_wallet(test_session, user.id)
        await test_session.commit()

        mp_order_id = "ORDER-123-REAL"
        real_qr_code = "00020101021226870014br.gov.bcb.pix.real.qr"

        mock_order_resp = {
            "id": mp_order_id,
            "transactions": {
                "payments": [
                    {
                        "payment_method": {
                            "qr_code": real_qr_code,
                        },
                        "date_of_expiration": None,
                    }
                ]
            },
        }

        with patch("app.infrastructure.payment.pix_gateway.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_post = MagicMock()
            mock_post.status_code = 200
            mock_post.json.return_value = mock_order_resp
            mock_post.raise_for_status = MagicMock()
            mock_http.post = AsyncMock(return_value=mock_post)

            svc = InstallmentPaymentService(test_session)
            payment = await svc.create_payment(
                CreateInstallmentPaymentInput(
                    user_id=user.id,
                    subscription_ids=[sub.id],
                )
            )

        # DTO should have real values
        assert payment.pix_transaction_id == mp_order_id
        assert payment.pix_qr_code_data == real_qr_code

        # DB should also have real values
        tx_repo = TransactionRepository(test_session)
        stored = await tx_repo.get_by_id(payment.id)
        assert stored is not None
        assert stored.pix_transaction_id == mp_order_id
        assert stored.pix_qr_code_data == real_qr_code

    @pytest.mark.asyncio
    async def test_create_activation_stores_mp_order_id(self, test_session):
        """After create_or_get_pending, pix_transaction_id == MP order_id."""
        from app.application.dtos.finance import CreateActivationPaymentInput
        from app.application.services.subscription_activation_payment_service import (
            SubscriptionActivationPaymentService,
        )
        from app.infrastructure.db.repositories.transaction_repository import (
            TransactionRepository,
        )

        user = await _make_user(test_session)
        plan = await _make_plan(test_session)
        sub = await _make_inactive_sub(test_session, user.id, plan.id)
        await test_session.commit()

        mp_order_id = "ORDER-ACT-456-REAL"
        real_qr_code = "00020101021226870014br.gov.bcb.activation.real"

        mock_order_resp = {
            "id": mp_order_id,
            "transactions": {
                "payments": [
                    {
                        "payment_method": {
                            "qr_code": real_qr_code,
                        },
                    }
                ]
            },
        }

        with patch("app.infrastructure.payment.pix_gateway.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_post = MagicMock()
            mock_post.status_code = 200
            mock_post.json.return_value = mock_order_resp
            mock_post.raise_for_status = MagicMock()
            mock_http.post = AsyncMock(return_value=mock_post)

            svc = SubscriptionActivationPaymentService(test_session)
            dto = await svc.create_or_get_pending(
                CreateActivationPaymentInput(user_id=user.id, subscription_id=sub.id)
            )

        assert dto.pix_transaction_id == mp_order_id
        assert dto.pix_qr_code_data == real_qr_code

        tx_repo = TransactionRepository(test_session)
        stored = await tx_repo.get_by_id(dto.id)
        assert stored is not None
        assert stored.pix_transaction_id == mp_order_id
