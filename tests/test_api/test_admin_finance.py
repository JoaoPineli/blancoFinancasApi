"""Tests for admin finance endpoints — status code and response shape."""

import random
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.user import User, UserRole
from app.domain.value_objects.cpf import CPF
from app.domain.value_objects.email import Email
from app.infrastructure.db.repositories.user_repository import UserRepository
from app.infrastructure.security.jwt import create_access_token
from app.infrastructure.security.password import hash_password


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


async def _create_admin(session: AsyncSession, email: str = "admin@test.com") -> User:
    admin = User.create(
        cpf=CPF(_generate_valid_cpf()),
        email=Email(email),
        name="Test Admin",
        password_hash=hash_password("adminpass"),
        role=UserRole.ADMIN,
    )
    repo = UserRepository(session)
    await repo.save(admin)
    await session.commit()
    return admin


def _admin_token(admin: User) -> str:
    return create_access_token(admin.id, admin.role)


class TestFinanceSummaryEndpoint:
    """GET /api/v1/admin/finance/summary"""

    @pytest.mark.asyncio
    async def test_requires_auth(self, client: AsyncClient):
        response = await client.get(
            "/api/v1/admin/finance/summary",
            params={"start_date": "2026-01-01", "end_date": "2026-01-31"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_returns_200_with_correct_shape(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        admin = await _create_admin(test_session, "admin_summary@test.com")
        token = _admin_token(admin)

        response = await client.get(
            "/api/v1/admin/finance/summary",
            params={"start_date": "2026-01-01", "end_date": "2026-01-31"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "fundo_garantidor_cents" in data
        assert "total_inflow_cents" in data
        assert "total_outflow_cents" in data
        assert "net_balance_cents" in data
        assert "period_start" in data
        assert "period_end" in data
        assert isinstance(data["fundo_garantidor_cents"], int)
        assert isinstance(data["total_inflow_cents"], int)
        assert isinstance(data["total_outflow_cents"], int)
        assert isinstance(data["net_balance_cents"], int)
        assert data["period_start"] == "2026-01-01"
        assert data["period_end"] == "2026-01-31"

    @pytest.mark.asyncio
    async def test_net_balance_equals_inflow_minus_outflow(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        admin = await _create_admin(test_session, "admin_net@test.com")
        token = _admin_token(admin)

        response = await client.get(
            "/api/v1/admin/finance/summary",
            params={"start_date": "2026-01-01", "end_date": "2026-01-31"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["net_balance_cents"] == data["total_inflow_cents"] - data["total_outflow_cents"]


class TestCashFlowEndpoint:
    """GET /api/v1/admin/finance/cash-flow"""

    @pytest.mark.asyncio
    async def test_requires_auth(self, client: AsyncClient):
        response = await client.get(
            "/api/v1/admin/finance/cash-flow",
            params={"start_date": "2026-01-01", "end_date": "2026-01-31"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_returns_200_with_correct_shape(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        admin = await _create_admin(test_session, "admin_cashflow@test.com")
        token = _admin_token(admin)

        response = await client.get(
            "/api/v1/admin/finance/cash-flow",
            params={"start_date": "2026-01-01", "end_date": "2026-01-31"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "entries" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert isinstance(data["entries"], list)
        assert isinstance(data["total"], int)
        assert data["page"] == 1

    @pytest.mark.asyncio
    async def test_pagination_params_respected(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        admin = await _create_admin(test_session, "admin_cashflow_page@test.com")
        token = _admin_token(admin)

        response = await client.get(
            "/api/v1/admin/finance/cash-flow",
            params={"start_date": "2026-01-01", "end_date": "2026-01-31", "page": 2, "page_size": 10},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 2
        assert data["page_size"] == 10


class TestReconciliationSummaryEndpoint:
    """GET /api/v1/admin/finance/reconciliation/summary"""

    @pytest.mark.asyncio
    async def test_requires_auth(self, client: AsyncClient):
        response = await client.get("/api/v1/admin/finance/reconciliation/summary")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_returns_200_with_correct_shape(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        admin = await _create_admin(test_session, "admin_recon@test.com")
        token = _admin_token(admin)

        response = await client.get(
            "/api/v1/admin/finance/reconciliation/summary",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "conciliado" in data
        assert "pendente" in data
        assert "divergente" in data
        assert "total" in data
        assert isinstance(data["conciliado"], int)
        assert isinstance(data["pendente"], int)
        assert isinstance(data["divergente"], int)
        assert data["total"] == data["conciliado"] + data["pendente"] + data["divergente"]
