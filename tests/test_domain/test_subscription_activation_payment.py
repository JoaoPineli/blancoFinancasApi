"""Tests for SubscriptionActivationPayment entity."""

import pytest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.domain.entities.subscription_activation_payment import (
    ActivationPaymentStatus,
    SubscriptionActivationPayment,
)


def _make_payment(**overrides) -> SubscriptionActivationPayment:
    """Helper: create a payment with sensible defaults."""
    defaults = dict(
        user_id=uuid4(),
        subscription_id=uuid4(),
        admin_tax_cents=500,
        insurance_cents=100,
        pix_transaction_fee_cents=6,  # 0.99% of 606 ≈ 6
        pix_qr_code_data="00020101021226...",
        expiration_minutes=30,
    )
    defaults.update(overrides)
    return SubscriptionActivationPayment.create(**defaults)


class TestSubscriptionActivationPaymentCreate:
    """Factory method validation."""

    def test_create_sets_pending_status(self):
        payment = _make_payment()
        assert payment.status == ActivationPaymentStatus.PENDING

    def test_create_total_equals_sum_of_components(self):
        payment = _make_payment(admin_tax_cents=500, insurance_cents=100, pix_transaction_fee_cents=6)
        assert payment.total_amount_cents == 606

    def test_create_sets_pix_transaction_id_to_none(self):
        payment = _make_payment()
        assert payment.pix_transaction_id is None

    def test_invariant_total_mismatch_raises(self):
        """Direct construction with bad total raises ValueError."""
        with pytest.raises(ValueError, match="must equal"):
            SubscriptionActivationPayment(
                id=uuid4(),
                user_id=uuid4(),
                subscription_id=uuid4(),
                status=ActivationPaymentStatus.PENDING,
                admin_tax_cents=500,
                insurance_cents=100,
                pix_transaction_fee_cents=6,
                total_amount_cents=999,  # wrong: should be 606
                pix_qr_code_data="qr",
                pix_transaction_id=None,
                expiration_minutes=30,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )

    def test_invariant_negative_admin_tax_raises(self):
        with pytest.raises(ValueError, match="admin_tax_cents"):
            _make_payment(admin_tax_cents=-1)

    def test_invariant_zero_total_raises(self):
        with pytest.raises(ValueError, match="total_amount_cents must be positive"):
            _make_payment(admin_tax_cents=0, insurance_cents=0, pix_transaction_fee_cents=0)


class TestSubscriptionActivationPaymentConfirm:
    """confirm() transitions to CONFIRMED and is idempotent."""

    def test_confirm_sets_confirmed_status(self):
        payment = _make_payment()
        payment.confirm("PIX123")
        assert payment.status == ActivationPaymentStatus.CONFIRMED

    def test_confirm_sets_pix_transaction_id(self):
        payment = _make_payment()
        payment.confirm("PIX123")
        assert payment.pix_transaction_id == "PIX123"

    def test_confirm_sets_confirmed_at(self):
        payment = _make_payment()
        payment.confirm("PIX123")
        assert payment.confirmed_at is not None

    def test_confirm_idempotent_returns_false(self):
        payment = _make_payment()
        payment.confirm("PIX123")
        result = payment.confirm("PIX456")
        assert result is False

    def test_confirm_idempotent_preserves_original_pix_id(self):
        payment = _make_payment()
        payment.confirm("PIX-FIRST")
        payment.confirm("PIX-SECOND")
        assert payment.pix_transaction_id == "PIX-FIRST"

    def test_cannot_confirm_cancelled(self):
        payment = _make_payment()
        payment.cancel()
        with pytest.raises(ValueError):
            payment.confirm("PIX123")

    def test_cannot_confirm_expired(self):
        payment = _make_payment()
        payment.expire()
        with pytest.raises(ValueError):
            payment.confirm("PIX123")


class TestSubscriptionActivationPaymentIsStale:
    """is_stale() checks whether the pending payment exceeded its window."""

    def test_not_stale_when_fresh(self):
        payment = _make_payment(expiration_minutes=30)
        now = datetime.now(timezone.utc)
        assert payment.is_stale(now=now) is False

    def test_stale_when_past_expiration(self):
        payment = _make_payment(expiration_minutes=30)
        now = datetime.now(timezone.utc) + timedelta(minutes=31)
        assert payment.is_stale(now=now) is True

    def test_not_stale_when_confirmed(self):
        payment = _make_payment()
        payment.confirm("PIX123")
        now = datetime.now(timezone.utc) + timedelta(hours=1)
        assert payment.is_stale(now=now) is False


class TestSubscriptionActivationPaymentStatusMethods:
    """Status helper methods."""

    def test_is_pending_when_pending(self):
        payment = _make_payment()
        assert payment.is_pending() is True

    def test_is_confirmed_after_confirm(self):
        payment = _make_payment()
        payment.confirm("PIX")
        assert payment.is_confirmed() is True

    def test_fail_sets_failed_status(self):
        payment = _make_payment()
        payment.fail()
        assert payment.status == ActivationPaymentStatus.FAILED

    def test_cancel_sets_cancelled_status(self):
        payment = _make_payment()
        payment.cancel()
        assert payment.status == ActivationPaymentStatus.CANCELLED

    def test_expire_sets_expired_status(self):
        payment = _make_payment()
        payment.expire()
        assert payment.status == ActivationPaymentStatus.EXPIRED
