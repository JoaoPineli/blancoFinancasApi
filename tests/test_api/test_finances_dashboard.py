"""Tests for GET /v1/finances/dashboard endpoint."""

import random
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.transaction import Transaction, TransactionStatus, TransactionType
from app.domain.entities.user import User, UserRole
from app.domain.entities.wallet import Wallet
from app.domain.value_objects.cpf import CPF
from app.domain.value_objects.email import Email
from app.infrastructure.db.repositories.transaction_repository import TransactionRepository
from app.infrastructure.db.repositories.user_repository import UserRepository
from app.infrastructure.db.repositories.wallet_repository import WalletRepository
from app.infrastructure.security.jwt import create_access_token
from app.infrastructure.security.password import hash_password


def _generate_valid_cpf() -> str:
    """Generate a valid formatted CPF for testing."""
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
    email: str = "dashboard@test.com",
) -> User:
    user = User.create(
        cpf=CPF(_generate_valid_cpf()),
        email=Email(email),
        name="Test Dashboard User",
        password_hash=hash_password("password123"),
        role=UserRole.CLIENT,
    )
    repo = UserRepository(session)
    await repo.save(user)
    await session.commit()
    return user


async def _create_wallet(
    session: AsyncSession,
    user_id,
    balance_cents: int = 100_000,
) -> Wallet:
    wallet = Wallet.create(user_id)
    wallet.balance_cents = balance_cents
    repo = WalletRepository(session)
    saved = await repo.save(wallet)
    await session.commit()
    return saved


async def _create_yield_transaction(
    session: AsyncSession,
    user_id,
    amount_cents: int,
    confirmed_at: datetime,
) -> Transaction:
    tx = Transaction.create_yield(
        user_id=user_id,
        amount_cents=amount_cents,
        description="Test yield",
    )
    tx.confirmed_at = confirmed_at
    repo = TransactionRepository(session)
    saved = await repo.save(tx)
    await session.commit()
    return saved


def _auth_header(user: User) -> dict:
    token = create_access_token(subject=user.id, role=user.role)
    return {"Authorization": f"Bearer {token}"}


class TestGetDashboard:
    """Tests for GET /v1/finances/dashboard."""

    @pytest.mark.asyncio
    async def test_returns_balance_and_current_month_yield(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        """Returns wallet balance and sum of confirmed yields in current UTC month."""
        user = await _create_user(test_session, email=f"dash1_{uuid4().hex[:6]}@test.com")
        wallet = await _create_wallet(test_session, user.id, balance_cents=500_00)

        now = datetime.utcnow()

        # Two yields in current month
        await _create_yield_transaction(test_session, user.id, 1_000, confirmed_at=now)
        await _create_yield_transaction(test_session, user.id, 2_500, confirmed_at=now)

        # One yield in previous month (outside range)
        if now.month == 1:
            prev_month = now.replace(year=now.year - 1, month=12, day=15)
        else:
            prev_month = now.replace(month=now.month - 1, day=15)
        await _create_yield_transaction(test_session, user.id, 9_999, confirmed_at=prev_month)

        response = await client.get("/api/v1/finances/dashboard", headers=_auth_header(user))

        assert response.status_code == 200
        data = response.json()
        assert data["total_balance_cents"] == 500_00
        assert data["yield_this_month_cents"] == 3_500  # 1_000 + 2_500
        assert data["reference_month"] == now.strftime("%Y-%m")

    @pytest.mark.asyncio
    async def test_no_yields_this_month_returns_zero(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        """Returns zero yield when no confirmed yield transactions exist for current month."""
        user = await _create_user(test_session, email=f"dash2_{uuid4().hex[:6]}@test.com")
        await _create_wallet(test_session, user.id, balance_cents=200_00)

        response = await client.get("/api/v1/finances/dashboard", headers=_auth_header(user))

        assert response.status_code == 200
        data = response.json()
        assert data["yield_this_month_cents"] == 0

    @pytest.mark.asyncio
    async def test_no_wallet_returns_404(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        """Returns 404 when user has no wallet."""
        user = await _create_user(test_session, email=f"dash3_{uuid4().hex[:6]}@test.com")

        response = await client.get("/api/v1/finances/dashboard", headers=_auth_header(user))

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_unauthenticated_returns_401(self, client: AsyncClient):
        """Endpoint requires authentication."""
        response = await client.get("/api/v1/finances/dashboard")

        assert response.status_code == 401
