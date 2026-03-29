"""Tests for subscription deposit due-date features.

Covers:
- next_due_date calculation on creation
- dashboard lazy update (due_today vs overdue, idempotent flagging)
- payment clears overdue flag and advances next_due_date
- deposit_day_of_month validation and update
"""

import random
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.plan import Plan
from app.domain.entities.subscription import (
    ALLOWED_DEPOSIT_DAYS,
    SubscriptionStatus,
    UserPlanSubscription,
)
from app.domain.entities.user import User, UserRole
from app.domain.services.due_date_service import DueDateService
from app.domain.value_objects.cpf import CPF
from app.domain.value_objects.email import Email
from app.infrastructure.db.repositories.plan_repository import PlanRepository
from app.infrastructure.db.repositories.subscription_repository import (
    SubscriptionRepository,
)
from app.infrastructure.db.repositories.user_repository import UserRepository
from app.infrastructure.security.jwt import create_access_token
from app.infrastructure.security.password import hash_password


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
    return (
        f"{full[0]}{full[1]}{full[2]}.{full[3]}{full[4]}{full[5]}"
        f".{full[6]}{full[7]}{full[8]}-{full[9]}{full[10]}"
    )


async def _create_user(
    session: AsyncSession,
    email: str = "duetest@test.com",
) -> User:
    user = User.create(
        cpf=CPF(_generate_valid_cpf()),
        email=Email(email),
        name="Due Test User",
        password_hash=hash_password("password123"),
        role=UserRole.CLIENT,
    )
    repo = UserRepository(session)
    await repo.save(user)
    await session.commit()
    return user


async def _create_plan(session: AsyncSession) -> Plan:
    plan = Plan.create(
        title="Plano Due Test",
        description="Test plan for due dates",
        min_value_cents=1_000_00,
        max_value_cents=100_000_00,
        min_duration_months=6,
        max_duration_months=24,
        admin_tax_value_cents=50_00,
        insurance_percent=Decimal("1.0"),
        guarantee_fund_percent_1=Decimal("1.0"),
        guarantee_fund_percent_2=Decimal("1.3"),
        guarantee_fund_threshold_cents=500_00,
        active=True,
    )
    repo = PlanRepository(session)
    await repo.save(plan)
    await session.commit()
    return plan


async def _create_subscription(
    session: AsyncSession,
    user: User,
    plan: Plan,
    deposit_day: int = 10,
    next_due: date | None = None,
    has_overdue: bool = False,
    overdue_at: datetime | None = None,
) -> UserPlanSubscription:
    """Helper to create a subscription with specific due-date state."""
    sub = UserPlanSubscription.create(
        user_id=user.id,
        plan_id=plan.id,
        target_amount_cents=10_000_00,
        deposit_count=12,
        monthly_amount_cents=834_00,
        admin_tax_value_cents=50_00,
        insurance_percent=Decimal("1.0"),
        guarantee_fund_percent=Decimal("1.0"),
        total_cost_cents=200_00,
        deposit_day_of_month=deposit_day,
    )
    # Activate subscription (subscriptions start INACTIVE now)
    sub.activate(deposit_day_of_month=deposit_day, today_local=date(2026, 1, 1))
    # Override for test scenario
    if next_due is not None:
        sub.next_due_date = next_due
    if has_overdue:
        sub.has_overdue_deposit = True
        sub.overdue_marked_at = overdue_at or datetime.now(timezone.utc)

    repo = SubscriptionRepository(session)
    await repo.save(sub)
    await session.commit()
    return sub


# ===================================================================
# Entity-level tests
# ===================================================================


class TestSubscriptionEntity:
    """Test entity-level due-date behaviour."""

    def test_create_sets_next_due_date(self):
        """Creating a subscription produces INACTIVE status; activate() computes next_due_date."""
        sub = UserPlanSubscription.create(
            user_id=uuid4(),
            plan_id=uuid4(),
            target_amount_cents=10_000_00,
            deposit_count=12,
            monthly_amount_cents=834_00,
            admin_tax_value_cents=50_00,
            insurance_percent=Decimal("1.0"),
            guarantee_fund_percent=Decimal("1.0"),
            total_cost_cents=200_00,
            deposit_day_of_month=15,
        )
        assert sub.deposit_day_of_month == 15
        # Created as INACTIVE — next_due_date is None until activation
        assert sub.next_due_date is None
        # Activate the subscription
        sub.activate(deposit_day_of_month=15, today_local=date(2026, 3, 10))
        assert sub.next_due_date == date(2026, 3, 15)

    def test_create_invalid_deposit_day_raises(self):
        """Invalid deposit day raises ValueError."""
        with pytest.raises(ValueError, match="deposit_day_of_month"):
            UserPlanSubscription.create(
                user_id=uuid4(),
                plan_id=uuid4(),
                target_amount_cents=10_000_00,
                deposit_count=12,
                monthly_amount_cents=834_00,
                admin_tax_value_cents=50_00,
                insurance_percent=Decimal("1.0"),
                guarantee_fund_percent=Decimal("1.0"),
                total_cost_cents=200_00,
                deposit_day_of_month=7,
            )

    def test_mark_overdue_first_time(self):
        """mark_overdue sets flag the first time and returns True."""
        sub = UserPlanSubscription.create(
            user_id=uuid4(),
            plan_id=uuid4(),
            target_amount_cents=10_000_00,
            deposit_count=12,
            monthly_amount_cents=834_00,
            admin_tax_value_cents=50_00,
            insurance_percent=Decimal("1.0"),
            guarantee_fund_percent=Decimal("1.0"),
            total_cost_cents=200_00,
        )
        assert not sub.has_overdue_deposit
        result = sub.mark_overdue()
        assert result is True
        assert sub.has_overdue_deposit is True
        assert sub.overdue_marked_at is not None

    def test_mark_overdue_idempotent(self):
        """Calling mark_overdue when already flagged returns False."""
        sub = UserPlanSubscription.create(
            user_id=uuid4(),
            plan_id=uuid4(),
            target_amount_cents=10_000_00,
            deposit_count=12,
            monthly_amount_cents=834_00,
            admin_tax_value_cents=50_00,
            insurance_percent=Decimal("1.0"),
            guarantee_fund_percent=Decimal("1.0"),
            total_cost_cents=200_00,
        )
        sub.mark_overdue()
        first_ts = sub.overdue_marked_at

        result = sub.mark_overdue()
        assert result is False
        # Timestamp should not have changed
        assert sub.overdue_marked_at == first_ts

    def test_clear_overdue_and_advance(self):
        """Payment clears overdue flag and advances due date."""
        sub = UserPlanSubscription.create(
            user_id=uuid4(),
            plan_id=uuid4(),
            target_amount_cents=10_000_00,
            deposit_count=12,
            monthly_amount_cents=834_00,
            admin_tax_value_cents=50_00,
            insurance_percent=Decimal("1.0"),
            guarantee_fund_percent=Decimal("1.0"),
            total_cost_cents=200_00,
            deposit_day_of_month=10,
        )
        sub.activate(deposit_day_of_month=10, today_local=date(2026, 3, 5))
        assert sub.next_due_date == date(2026, 3, 10)
        sub.mark_overdue()
        sub.clear_overdue_and_advance(date(2026, 3, 15))

        assert sub.has_overdue_deposit is False
        assert sub.overdue_marked_at is None
        assert sub.next_due_date == date(2026, 4, 10)

    def test_set_deposit_day_recomputes_due_date(self):
        """Changing deposit day recomputes next_due_date."""
        sub = UserPlanSubscription.create(
            user_id=uuid4(),
            plan_id=uuid4(),
            target_amount_cents=10_000_00,
            deposit_count=12,
            monthly_amount_cents=834_00,
            admin_tax_value_cents=50_00,
            insurance_percent=Decimal("1.0"),
            guarantee_fund_percent=Decimal("1.0"),
            total_cost_cents=200_00,
            deposit_day_of_month=10,
        )
        sub.activate(deposit_day_of_month=10, today_local=date(2026, 3, 15))
        # day 10 already passed on March 15 -> next is April 10
        assert sub.next_due_date == date(2026, 4, 10)

        sub.set_deposit_day(20, date(2026, 3, 15))
        assert sub.deposit_day_of_month == 20
        assert sub.next_due_date == date(2026, 3, 20)

    def test_set_deposit_day_invalid_raises(self):
        """Invalid day raises ValueError."""
        sub = UserPlanSubscription.create(
            user_id=uuid4(),
            plan_id=uuid4(),
            target_amount_cents=10_000_00,
            deposit_count=12,
            monthly_amount_cents=834_00,
            admin_tax_value_cents=50_00,
            insurance_percent=Decimal("1.0"),
            guarantee_fund_percent=Decimal("1.0"),
            total_cost_cents=200_00,
        )
        with pytest.raises(ValueError, match="deposit_day_of_month"):
            sub.set_deposit_day(13, date(2026, 3, 15))


# ===================================================================
# API integration tests
# ===================================================================


class TestCreateSubscriptionWithDepositDay:
    """Test that POST /subscriptions respects deposit_day_of_month."""

    @pytest.mark.asyncio
    async def test_create_with_deposit_day(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        user = await _create_user(test_session, email="create-day@test.com")
        plan = await _create_plan(test_session)
        token = create_access_token(user.id, user.role)

        response = await client.post(
            "/api/v1/subscriptions",
            json={
                "plan_id": str(plan.id),
                "target_amount_cents": 10_000_00,
                "deposit_count": 12,
                "monthly_amount_cents": 834_00,
                "name": "Test Day 15",
                "deposit_day_of_month": 15,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["deposit_day_of_month"] == 15
        assert data["next_due_date"] is None  # INACTIVE on creation; set after activation payment
        assert data["has_overdue_deposit"] is False

    @pytest.mark.asyncio
    async def test_create_with_invalid_deposit_day_returns_400(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        user = await _create_user(test_session, email="bad-day@test.com")
        plan = await _create_plan(test_session)
        token = create_access_token(user.id, user.role)

        response = await client.post(
            "/api/v1/subscriptions",
            json={
                "plan_id": str(plan.id),
                "target_amount_cents": 10_000_00,
                "deposit_count": 12,
                "monthly_amount_cents": 834_00,
                "name": "Test Day 7",
                "deposit_day_of_month": 7,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_create_defaults_to_day_1(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        user = await _create_user(test_session, email="default-day@test.com")
        plan = await _create_plan(test_session)
        token = create_access_token(user.id, user.role)

        response = await client.post(
            "/api/v1/subscriptions",
            json={
                "plan_id": str(plan.id),
                "target_amount_cents": 10_000_00,
                "deposit_count": 12,
                "monthly_amount_cents": 834_00,
                "name": "Test Default",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 201
        assert response.json()["deposit_day_of_month"] == 1


class TestUpdateDepositDay:
    """Test PATCH /subscriptions/{id}/deposit-day."""

    @pytest.mark.asyncio
    async def test_update_deposit_day_success(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        user = await _create_user(test_session, email="update-day@test.com")
        plan = await _create_plan(test_session)
        sub = await _create_subscription(test_session, user, plan, deposit_day=5)
        token = create_access_token(user.id, user.role)

        response = await client.patch(
            f"/api/v1/subscriptions/{sub.id}/deposit-day",
            json={"deposit_day_of_month": 20},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["deposit_day_of_month"] == 20

    @pytest.mark.asyncio
    async def test_update_deposit_day_invalid_returns_400(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        user = await _create_user(test_session, email="bad-update@test.com")
        plan = await _create_plan(test_session)
        sub = await _create_subscription(test_session, user, plan, deposit_day=5)
        token = create_access_token(user.id, user.role)

        response = await client.patch(
            f"/api/v1/subscriptions/{sub.id}/deposit-day",
            json={"deposit_day_of_month": 12},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_update_deposit_day_not_found(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        user = await _create_user(test_session, email="notfound@test.com")
        token = create_access_token(user.id, user.role)

        response = await client.patch(
            f"/api/v1/subscriptions/{uuid4()}/deposit-day",
            json={"deposit_day_of_month": 10},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404


class TestDashboardDueStatus:
    """Test GET /subscriptions/dashboard/due-status (lazy update)."""

    @pytest.mark.asyncio
    async def test_no_due_returns_empty(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        """No subscriptions due -> empty arrays."""
        user = await _create_user(test_session, email="nodue@test.com")
        plan = await _create_plan(test_session)
        # Due date far in the future
        await _create_subscription(
            test_session, user, plan, deposit_day=10,
            next_due=date(2027, 1, 10),
        )
        token = create_access_token(user.id, user.role)

        response = await client.get(
            "/api/v1/subscriptions/dashboard/due-status",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["overdue_plans"] == []
        assert data["due_today_plans"] == []

    @pytest.mark.asyncio
    async def test_overdue_detected(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        """Subscription with next_due_date in the past -> overdue."""
        user = await _create_user(test_session, email="overdue@test.com")
        plan = await _create_plan(test_session)
        await _create_subscription(
            test_session, user, plan, deposit_day=10,
            next_due=date(2025, 1, 10),  # far in the past
        )
        token = create_access_token(user.id, user.role)

        response = await client.get(
            "/api/v1/subscriptions/dashboard/due-status",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["overdue_plans"]) == 1
        assert data["overdue_plans"][0]["plan_title"] == "Plano Due Test"
        assert data["due_today_plans"] == []

    @pytest.mark.asyncio
    async def test_due_today_detected(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        """Subscription due today -> due_today list."""
        user = await _create_user(test_session, email="duetoday@test.com")
        plan = await _create_plan(test_session)

        # Patch _today_local to return a known date
        from app.application.services import subscription_service
        original_today = subscription_service.SubscriptionService._today_local

        fixed_date = date(2026, 5, 10)

        await _create_subscription(
            test_session, user, plan, deposit_day=10,
            next_due=fixed_date,
        )
        token = create_access_token(user.id, user.role)

        with patch.object(
            subscription_service.SubscriptionService,
            "_today_local",
            staticmethod(lambda: fixed_date),
        ):
            response = await client.get(
                "/api/v1/subscriptions/dashboard/due-status",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 200
        data = response.json()
        assert len(data["due_today_plans"]) == 1
        assert data["overdue_plans"] == []

    @pytest.mark.asyncio
    async def test_lazy_update_idempotent(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        """Calling dashboard endpoint twice does not rewrite overdue_marked_at."""
        user = await _create_user(test_session, email="idempotent@test.com")
        plan = await _create_plan(test_session)
        sub = await _create_subscription(
            test_session, user, plan, deposit_day=10,
            next_due=date(2025, 1, 10),  # overdue
        )
        token = create_access_token(user.id, user.role)

        # First call – flags the subscription
        resp1 = await client.get(
            "/api/v1/subscriptions/dashboard/due-status",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp1.status_code == 200
        assert len(resp1.json()["overdue_plans"]) == 1

        # Expire identity map so we get fresh data from the DB
        test_session.expire_all()
        repo = SubscriptionRepository(test_session)
        after_first = await repo.get_by_id(sub.id)
        assert after_first is not None
        assert after_first.has_overdue_deposit is True
        first_marked_at = after_first.overdue_marked_at
        assert first_marked_at is not None

        # Second call – should NOT change overdue_marked_at
        resp2 = await client.get(
            "/api/v1/subscriptions/dashboard/due-status",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp2.status_code == 200
        assert len(resp2.json()["overdue_plans"]) == 1

        test_session.expire_all()
        after_second = await repo.get_by_id(sub.id)
        assert after_second is not None
        assert after_second.overdue_marked_at == first_marked_at

    @pytest.mark.asyncio
    async def test_does_not_flag_non_overdue(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        """Future due-date subscription should not be flagged."""
        user = await _create_user(test_session, email="noflag@test.com")
        plan = await _create_plan(test_session)
        sub = await _create_subscription(
            test_session, user, plan, deposit_day=10,
            next_due=date(2027, 6, 10),
        )
        token = create_access_token(user.id, user.role)

        await client.get(
            "/api/v1/subscriptions/dashboard/due-status",
            headers={"Authorization": f"Bearer {token}"},
        )

        test_session.expire_all()
        repo = SubscriptionRepository(test_session)
        after = await repo.get_by_id(sub.id)
        assert after is not None
        assert after.has_overdue_deposit is False
        assert after.overdue_marked_at is None


class TestDepositDayAllowedValues:
    """Exhaustive validation of allowed deposit days."""

    @pytest.mark.parametrize("day", sorted(ALLOWED_DEPOSIT_DAYS))
    def test_allowed_day_accepted(self, day: int):
        """Each allowed day should be accepted."""
        sub = UserPlanSubscription.create(
            user_id=uuid4(),
            plan_id=uuid4(),
            target_amount_cents=10_000_00,
            deposit_count=12,
            monthly_amount_cents=834_00,
            admin_tax_value_cents=50_00,
            insurance_percent=Decimal("1.0"),
            guarantee_fund_percent=Decimal("1.0"),
            total_cost_cents=200_00,
            deposit_day_of_month=day,
        )
        assert sub.deposit_day_of_month == day

    @pytest.mark.parametrize("day", [2, 3, 7, 12, 28, 30, 31])
    def test_disallowed_day_rejected(self, day: int):
        """Non-allowed days should raise ValueError."""
        with pytest.raises(ValueError):
            UserPlanSubscription.create(
                user_id=uuid4(),
                plan_id=uuid4(),
                target_amount_cents=10_000_00,
                deposit_count=12,
                monthly_amount_cents=834_00,
                admin_tax_value_cents=50_00,
                insurance_percent=Decimal("1.0"),
                guarantee_fund_percent=Decimal("1.0"),
                total_cost_cents=200_00,
                deposit_day_of_month=day,
            )
