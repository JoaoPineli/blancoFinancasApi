"""Tests for Transaction.create_activation_payment (unified entity).

These tests replace the old SubscriptionActivationPayment entity tests.
All activation payment behavior is now exercised via the Transaction entity.
"""

import pytest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.domain.entities.transaction import Transaction, TransactionStatus, TransactionType


def _make_payment(**overrides) -> Transaction:
    """Helper: create an activation payment transaction with sensible defaults."""
    defaults = dict(
        user_id=uuid4(),
        subscription_id=uuid4(),
        admin_tax_cents=500,
        insurance_cents=100,
        pix_transaction_fee_cents=6,
        pix_qr_code_data="00020101021226...",
        expiration_minutes=30,
    )
    defaults.update(overrides)
    return Transaction.create_activation_payment(**defaults)


class TestCreateActivationPayment:
    """Factory method validation."""

    def test_create_sets_pending_status(self):
        payment = _make_payment()
        assert payment.status == TransactionStatus.PENDING

    def test_create_sets_correct_type(self):
        payment = _make_payment()
        assert payment.transaction_type == TransactionType.SUBSCRIPTION_ACTIVATION_PAYMENT

    def test_create_total_equals_sum_of_components(self):
        payment = _make_payment(admin_tax_cents=500, insurance_cents=100, pix_transaction_fee_cents=6)
        assert payment.amount_cents == 606

    def test_create_sets_pix_transaction_id_to_none_by_default(self):
        payment = _make_payment()
        assert payment.pix_transaction_id is None

    def test_create_stores_breakdown_snapshots(self):
        payment = _make_payment(admin_tax_cents=500, insurance_cents=100, pix_transaction_fee_cents=6)
        assert payment.admin_tax_cents == 500
        assert payment.insurance_cents == 100
        assert payment.pix_transaction_fee_cents == 6


class TestConfirmPaymentIdempotent:
    """confirm_payment() transitions to CONFIRMED and is idempotent."""

    def test_confirm_sets_confirmed_status(self):
        payment = _make_payment()
        payment.confirm_payment("PIX123")
        assert payment.status == TransactionStatus.CONFIRMED

    def test_confirm_sets_pix_transaction_id(self):
        payment = _make_payment()
        payment.confirm_payment("PIX123")
        assert payment.pix_transaction_id == "PIX123"

    def test_confirm_sets_confirmed_at(self):
        payment = _make_payment()
        payment.confirm_payment("PIX123")
        assert payment.confirmed_at is not None

    def test_confirm_idempotent_returns_false(self):
        payment = _make_payment()
        payment.confirm_payment("PIX123")
        result = payment.confirm_payment("PIX456")
        assert result is False

    def test_confirm_idempotent_preserves_original_pix_id(self):
        payment = _make_payment()
        payment.confirm_payment("PIX-FIRST")
        payment.confirm_payment("PIX-SECOND")
        assert payment.pix_transaction_id == "PIX-FIRST"

    def test_cannot_confirm_cancelled(self):
        payment = _make_payment()
        payment.cancel()
        with pytest.raises(ValueError):
            payment.confirm_payment("PIX123")

    def test_cannot_confirm_expired(self):
        payment = _make_payment()
        payment.expire()
        with pytest.raises(ValueError):
            payment.confirm_payment("PIX123")


class TestIsStale:
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
        payment.confirm_payment("PIX123")
        now = datetime.now(timezone.utc) + timedelta(hours=1)
        assert payment.is_stale(now=now) is False


class TestStatusMethods:
    """Status helper methods."""

    def test_is_pending_when_pending(self):
        payment = _make_payment()
        assert payment.is_pending() is True

    def test_is_confirmed_after_confirm(self):
        payment = _make_payment()
        payment.confirm_payment("PIX")
        assert payment.is_confirmed() is True

    def test_fail_sets_failed_status(self):
        payment = _make_payment()
        payment.fail()
        assert payment.status == TransactionStatus.FAILED

    def test_cancel_sets_cancelled_status(self):
        payment = _make_payment()
        payment.cancel()
        assert payment.status == TransactionStatus.CANCELLED

    def test_expire_sets_expired_status(self):
        payment = _make_payment()
        payment.expire()
        assert payment.status == TransactionStatus.EXPIRED
