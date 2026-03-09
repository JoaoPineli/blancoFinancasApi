"""Tests for subscription endpoints - authorization and creation."""

import random

import pytest
from decimal import Decimal
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.plan import Plan
from app.domain.entities.user import User, UserRole
from app.domain.value_objects.cpf import CPF
from app.domain.value_objects.email import Email
from app.infrastructure.db.repositories.plan_repository import PlanRepository
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
    return f"{full[0]}{full[1]}{full[2]}.{full[3]}{full[4]}{full[5]}.{full[6]}{full[7]}{full[8]}-{full[9]}{full[10]}"


async def _create_user(
    session: AsyncSession,
    email: str = "client@test.com",
    role: UserRole = UserRole.CLIENT,
) -> User:
    """Helper to create a test user with a unique CPF."""
    user = User.create(
        cpf=CPF(_generate_valid_cpf()),
        email=Email(email),
        name="Test Client",
        password_hash=hash_password("password123"),
        role=role,
    )
    repo = UserRepository(session)
    await repo.save(user)
    await session.commit()
    return user


async def _create_plan(
    session: AsyncSession,
    min_value_cents: int = 1_000_00,
    max_value_cents: int | None = 100_000_00,
    min_duration_months: int = 6,
    max_duration_months: int | None = 24,
) -> Plan:
    """Helper to create a test plan."""
    plan = Plan.create(
        title="Plano Geral",
        description="Plano de teste",
        min_value_cents=min_value_cents,
        max_value_cents=max_value_cents,
        min_duration_months=min_duration_months,
        max_duration_months=max_duration_months,
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


class TestSubscriptionListAuthorization:
    """Test that users can only list their own subscriptions."""

    @pytest.mark.asyncio
    async def test_list_subscriptions_unauthenticated_returns_401(
        self, client: AsyncClient
    ):
        """Unauthenticated request should return 401."""
        response = await client.get("/api/v1/subscriptions")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_list_subscriptions_returns_empty_for_new_user(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        """A user with no subscriptions should get an empty list."""
        user = await _create_user(test_session)
        token = create_access_token(user.id, user.role)

        response = await client.get(
            "/api/v1/subscriptions",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["subscriptions"] == []


class TestSubscriptionCreationAuthorization:
    """Test that subscription creation enforces ownership."""

    @pytest.mark.asyncio
    async def test_create_subscription_unauthenticated_returns_401(
        self, client: AsyncClient
    ):
        """Unauthenticated creation should return 401."""
        response = await client.post(
            "/api/v1/subscriptions",
            json={
                "plan_id": str(uuid4()),
                "target_amount_cents": 10_000_00,
                "deposit_count": 12,
                "monthly_amount_cents": 834,
            },
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_create_subscription_sets_user_from_token(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        """The user_id on the subscription must match the authenticated user."""
        user = await _create_user(test_session, email="owner@test.com")
        plan = await _create_plan(test_session)
        token = create_access_token(user.id, user.role)

        response = await client.post(
            "/api/v1/subscriptions",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "plan_id": str(plan.id),
                "target_amount_cents": 10_000_00,
                "deposit_count": 12,
                "monthly_amount_cents": 834_00,
                "name": "Minha Poupança",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["user_id"] == str(user.id)
        assert data["plan_id"] == str(plan.id)
        assert data["status"] == "active"

    @pytest.mark.asyncio
    async def test_create_subscription_invalid_plan_returns_404(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        """Creating subscription with non-existent plan should return 404."""
        user = await _create_user(test_session, email="test404@test.com")
        token = create_access_token(user.id, user.role)

        response = await client.post(
            "/api/v1/subscriptions",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "plan_id": str(uuid4()),
                "target_amount_cents": 10_000_00,
                "deposit_count": 12,
                "monthly_amount_cents": 834_00,
                "name": "Test",
            },
        )

        assert response.status_code == 404


class TestSubscriptionRecommendation:
    """Test recommendation endpoint."""

    @pytest.mark.asyncio
    async def test_recommend_returns_viable_plan(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        """Recommendation should return a viable plan with cost breakdown."""
        user = await _create_user(test_session, email="rec1@test.com")
        plan = await _create_plan(test_session)
        token = create_access_token(user.id, user.role)

        response = await client.post(
            "/api/v1/subscriptions/recommend",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "target_amount_cents": 10_000_00,
                "preference": "FEWER_PAYMENTS",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["plan_id"] == str(plan.id)
        assert data["deposit_count"] >= 6
        assert data["monthly_amount_cents"] > 0
        assert data["total_cost_cents"] > 0
        assert data["admin_tax_value_cents"] == 50_00

    @pytest.mark.asyncio
    async def test_recommend_no_viable_plan_returns_422(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        """When no plan fits, return 422."""
        user = await _create_user(test_session, email="rec2@test.com")
        # Create a plan with small max
        await _create_plan(
            test_session,
            min_value_cents=1_000_00,
            max_value_cents=5_000_00,
        )
        token = create_access_token(user.id, user.role)

        response = await client.post(
            "/api/v1/subscriptions/recommend",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "target_amount_cents": 999_999_00,
                "preference": "FEWER_PAYMENTS",
            },
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_recommend_unauthenticated_returns_401(
        self, client: AsyncClient
    ):
        """Unauthenticated recommendation request should return 401."""
        response = await client.post(
            "/api/v1/subscriptions/recommend",
            json={
                "target_amount_cents": 10_000_00,
                "preference": "FEWER_PAYMENTS",
            },
        )
        assert response.status_code == 401


class TestSubscriptionCostCalculation:
    """Test cost calculation endpoint."""

    @pytest.mark.asyncio
    async def test_calculate_cost_returns_breakdown(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        """Cost calculation should return a detailed breakdown."""
        user = await _create_user(test_session, email="cost1@test.com")
        plan = await _create_plan(test_session)
        token = create_access_token(user.id, user.role)

        response = await client.post(
            "/api/v1/subscriptions/calculate-cost",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "plan_id": str(plan.id),
                "target_amount_cents": 12_000_00,
                "deposit_count": 12,
                "monthly_amount_cents": 1_000_00,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total_cost_cents"] > 0
        assert data["admin_tax_value_cents"] == 50_00
        assert data["insurance_cost_cents"] > 0
        assert data["guarantee_fund_cost_cents"] > 0

    @pytest.mark.asyncio
    async def test_calculate_cost_invalid_duration_returns_400(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        """Cost calculation with out-of-range duration should return 400."""
        user = await _create_user(test_session, email="cost2@test.com")
        plan = await _create_plan(test_session, min_duration_months=6)
        token = create_access_token(user.id, user.role)

        response = await client.post(
            "/api/v1/subscriptions/calculate-cost",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "plan_id": str(plan.id),
                "target_amount_cents": 12_000_00,
                "deposit_count": 2,  # Below min (6)
                "monthly_amount_cents": 6_000_00,
            },
        )

        assert response.status_code == 400
