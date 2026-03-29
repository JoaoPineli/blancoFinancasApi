"""Tests for inactive subscription status and activation flow."""

import pytest
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from app.domain.entities.subscription import SubscriptionStatus, UserPlanSubscription


def _make_subscription(**overrides) -> UserPlanSubscription:
    """Helper: create a subscription with sensible defaults."""
    defaults = dict(
        user_id=uuid4(),
        plan_id=uuid4(),
        target_amount_cents=100_000,
        deposit_count=12,
        monthly_amount_cents=10_000,
        admin_tax_value_cents=500,
        insurance_percent=Decimal("1.0"),
        guarantee_fund_percent=Decimal("1.0"),
        total_cost_cents=1_200,
        name="Meu plano",
        deposit_day_of_month=5,
    )
    defaults.update(overrides)
    return UserPlanSubscription.create(**defaults)


class TestSubscriptionInactiveCreation:
    """Subscriptions must start as INACTIVE."""

    def test_create_returns_inactive_status(self):
        sub = _make_subscription()
        assert sub.status == SubscriptionStatus.INACTIVE

    def test_create_next_due_date_is_none(self):
        """next_due_date must be None until activation."""
        sub = _make_subscription()
        assert sub.next_due_date is None

    def test_create_covers_activation_fees_is_true(self):
        """New subscriptions flag covers_activation_fees=True."""
        sub = _make_subscription()
        assert sub.covers_activation_fees is True

    def test_create_deposits_paid_is_zero(self):
        sub = _make_subscription()
        assert sub.deposits_paid == 0

    def test_create_is_not_active(self):
        sub = _make_subscription()
        assert sub.is_active() is False


class TestSubscriptionActivate:
    """activate() transitions subscription to ACTIVE and sets next_due_date."""

    def test_activate_sets_active_status(self):
        sub = _make_subscription()
        sub.activate(deposit_day_of_month=5, today_local=date(2026, 3, 28))
        assert sub.status == SubscriptionStatus.ACTIVE

    def test_activate_sets_next_due_date(self):
        sub = _make_subscription()
        sub.activate(deposit_day_of_month=5, today_local=date(2026, 3, 28))
        assert sub.next_due_date is not None

    def test_activate_next_due_date_in_future_or_today(self):
        today = date(2026, 3, 28)
        sub = _make_subscription()
        sub.activate(deposit_day_of_month=5, today_local=today)
        # next_due_date should be >= today
        assert sub.next_due_date >= today

    def test_activate_raises_if_already_active(self):
        sub = _make_subscription()
        sub.activate(deposit_day_of_month=5, today_local=date(2026, 3, 28))
        with pytest.raises(ValueError, match="Cannot activate"):
            sub.activate(deposit_day_of_month=5, today_local=date(2026, 3, 28))

    def test_activate_raises_if_cancelled(self):
        sub = _make_subscription()
        sub.cancel()
        with pytest.raises(ValueError, match="Cannot activate"):
            sub.activate(deposit_day_of_month=5, today_local=date(2026, 3, 28))


class TestSubscriptionInactiveRestrictions:
    """INACTIVE subscriptions cannot perform active-subscription operations."""

    def test_record_deposit_paid_raises_if_inactive(self):
        sub = _make_subscription()
        with pytest.raises(ValueError, match="Cannot record payment"):
            sub.record_deposit_paid(today_local=date(2026, 3, 28))

    def test_cancel_works_for_inactive(self):
        sub = _make_subscription()
        sub.cancel()
        assert sub.status == SubscriptionStatus.CANCELLED

    def test_is_active_returns_false_for_inactive(self):
        sub = _make_subscription()
        assert sub.is_active() is False


class TestSubscriptionAfterActivation:
    """After activation, subscription behaves like a normal active subscription."""

    def test_record_deposit_paid_works_after_activation(self):
        sub = _make_subscription()
        sub.activate(deposit_day_of_month=5, today_local=date(2026, 3, 1))
        sub.record_deposit_paid(today_local=date(2026, 4, 5))
        assert sub.deposits_paid == 1

    def test_completes_when_all_deposits_paid(self):
        sub = _make_subscription(deposit_count=1)
        sub.activate(deposit_day_of_month=5, today_local=date(2026, 3, 1))
        sub.record_deposit_paid(today_local=date(2026, 4, 5))
        assert sub.status == SubscriptionStatus.COMPLETED
