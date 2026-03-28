"""Tests for admin notification API endpoints.

Covers:
- GET /v1/admin/notifications
- GET /v1/admin/notifications/unread-count
- PATCH /v1/admin/notifications/{id}/read
- POST /v1/admin/notifications/mark-all-read
"""

import random
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import uuid4

from app.domain.entities.notification import Notification
from app.domain.entities.user import User, UserRole
from app.domain.value_objects.cpf import CPF
from app.domain.value_objects.email import Email
from app.infrastructure.db.repositories.notification_repository import NotificationRepository
from app.infrastructure.db.repositories.user_repository import UserRepository
from app.infrastructure.security.jwt import create_access_token
from app.infrastructure.security.password import hash_password


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


async def _create_admin(session: AsyncSession) -> User:
    repo = UserRepository(session)
    user = User.create(
        cpf=CPF(_generate_valid_cpf()),
        email=Email(f"{uuid4().hex[:8]}@admin.com"),
        name="Admin User",
        password_hash=hash_password("password123"),
        role=UserRole.ADMIN,
    )
    saved = await repo.save(user)
    await session.commit()
    return saved


async def _save_notification(session: AsyncSession) -> Notification:
    repo = NotificationRepository(session)
    n = Notification.create_withdrawal_requested(
        target_id=uuid4(),
        client_name="Test Client",
        plan_title="Plano Teste",
        amount_cents=100_000,
    )
    saved = await repo.save(n)
    await session.flush()
    return saved


def _auth_header(user: User) -> dict:
    token = create_access_token(subject=user.id, role=user.role)
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestListNotifications:
    """Tests for GET /v1/admin/notifications."""

    @pytest.mark.asyncio
    async def test_returns_200_with_list(self, client: AsyncClient, test_session: AsyncSession):
        admin = await _create_admin(test_session)
        await _save_notification(test_session)
        await test_session.commit()

        response = await client.get(
            "/api/v1/admin/notifications",
            headers=_auth_header(admin),
        )
        assert response.status_code == 200
        data = response.json()
        assert "notifications" in data
        assert "unread_count" in data
        assert isinstance(data["notifications"], list)

    @pytest.mark.asyncio
    async def test_requires_authentication(self, client: AsyncClient):
        response = await client.get("/api/v1/admin/notifications")
        assert response.status_code == 401


class TestGetUnreadCount:
    """Tests for GET /v1/admin/notifications/unread-count."""

    @pytest.mark.asyncio
    async def test_returns_unread_count(self, client: AsyncClient, test_session: AsyncSession):
        admin = await _create_admin(test_session)
        await _save_notification(test_session)
        await test_session.commit()

        response = await client.get(
            "/api/v1/admin/notifications/unread-count",
            headers=_auth_header(admin),
        )
        assert response.status_code == 200
        data = response.json()
        assert "unread_count" in data
        assert data["unread_count"] >= 1

    @pytest.mark.asyncio
    async def test_requires_authentication(self, client: AsyncClient):
        response = await client.get("/api/v1/admin/notifications/unread-count")
        assert response.status_code == 401


class TestMarkAsRead:
    """Tests for PATCH /v1/admin/notifications/{id}/read."""

    @pytest.mark.asyncio
    async def test_marks_notification_as_read(self, client: AsyncClient, test_session: AsyncSession):
        admin = await _create_admin(test_session)
        n = await _save_notification(test_session)
        await test_session.commit()

        response = await client.patch(
            f"/api/v1/admin/notifications/{n.id}/read",
            headers=_auth_header(admin),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_read"] is True
        assert data["read_at"] is not None

    @pytest.mark.asyncio
    async def test_returns_404_for_unknown(self, client: AsyncClient, test_session: AsyncSession):
        admin = await _create_admin(test_session)

        response = await client.patch(
            f"/api/v1/admin/notifications/{uuid4()}/read",
            headers=_auth_header(admin),
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_requires_authentication(self, client: AsyncClient):
        response = await client.patch(f"/api/v1/admin/notifications/{uuid4()}/read")
        assert response.status_code == 401


class TestMarkAllAsRead:
    """Tests for POST /v1/admin/notifications/mark-all-read."""

    @pytest.mark.asyncio
    async def test_marks_all_as_read(self, client: AsyncClient, test_session: AsyncSession):
        admin = await _create_admin(test_session)
        await _save_notification(test_session)
        await _save_notification(test_session)
        await test_session.commit()

        response = await client.post(
            "/api/v1/admin/notifications/mark-all-read",
            headers=_auth_header(admin),
        )
        assert response.status_code == 200
        data = response.json()
        assert "marked_as_read" in data
        assert data["marked_as_read"] >= 2

        # Unread count should now be zero
        count_resp = await client.get(
            "/api/v1/admin/notifications/unread-count",
            headers=_auth_header(admin),
        )
        assert count_resp.json()["unread_count"] == 0

    @pytest.mark.asyncio
    async def test_requires_authentication(self, client: AsyncClient):
        response = await client.post("/api/v1/admin/notifications/mark-all-read")
        assert response.status_code == 401
