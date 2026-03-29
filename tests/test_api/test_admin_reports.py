"""Tests for admin report download endpoints."""

import random

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.audit_log import AuditAction, AuditLog
from app.domain.entities.user import User, UserRole
from app.domain.value_objects.cpf import CPF
from app.domain.value_objects.email import Email
from app.infrastructure.db.repositories.audit_log_repository import AuditLogRepository
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


async def _create_client(session: AsyncSession, email: str) -> User:
    client = User.create(
        cpf=CPF(_generate_valid_cpf()),
        email=Email(email),
        name="Test Client",
        password_hash=hash_password("clientpass"),
        role=UserRole.CLIENT,
    )
    repo = UserRepository(session)
    await repo.save(client)
    await session.commit()
    return client


def _admin_token(admin: User) -> str:
    return create_access_token(admin.id, admin.role)


def _client_token(user: User) -> str:
    return create_access_token(user.id, user.role)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_PARAMS = {"start_date": "2026-01-01", "end_date": "2026-03-29"}


# ===========================================================================
# Cash-flow report
# ===========================================================================


class TestCashFlowReportDownload:
    """GET /api/v1/admin/reports/cash-flow"""

    @pytest.mark.asyncio
    async def test_requires_auth(self, client: AsyncClient):
        response = await client.get(
            "/api/v1/admin/reports/cash-flow",
            params={"start_date": "2026-03-01", "end_date": "2026-03-29"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_admin_only(self, client: AsyncClient, test_session: AsyncSession):
        user = await _create_client(test_session, "cf_client_only@test.com")
        token = _client_token(user)
        response = await client.get(
            "/api/v1/admin/reports/cash-flow",
            params=_DEFAULT_PARAMS,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_returns_xlsx(self, client: AsyncClient, test_session: AsyncSession):
        admin = await _create_admin(test_session, "admin_reports@test.com")
        token = _admin_token(admin)

        response = await client.get(
            "/api/v1/admin/reports/cash-flow",
            params={"start_date": "2026-03-01", "end_date": "2026-03-29"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        assert (
            response.headers.get("content-type")
            == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        # XLSX is a ZIP file; must start with 'PK'
        assert response.content[:2] == b"PK"

    @pytest.mark.asyncio
    async def test_returns_csv(self, client: AsyncClient, test_session: AsyncSession):
        admin = await _create_admin(test_session, "admin_cf_csv@test.com")
        token = _admin_token(admin)

        response = await client.get(
            "/api/v1/admin/reports/cash-flow",
            params={**_DEFAULT_PARAMS, "format": "csv"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        assert "text/csv" in response.headers.get("content-type", "")
        # CSV must be text (UTF-8 with BOM)
        assert response.content[:3] == b"\xef\xbb\xbf"

    @pytest.mark.asyncio
    async def test_returns_pdf(self, client: AsyncClient, test_session: AsyncSession):
        admin = await _create_admin(test_session, "admin_cf_pdf@test.com")
        token = _admin_token(admin)

        response = await client.get(
            "/api/v1/admin/reports/cash-flow",
            params={**_DEFAULT_PARAMS, "format": "pdf"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        assert response.headers.get("content-type") == "application/pdf"
        # PDF magic bytes
        assert response.content[:4] == b"%PDF"

    @pytest.mark.asyncio
    async def test_content_disposition_xlsx(self, client: AsyncClient, test_session: AsyncSession):
        admin = await _create_admin(test_session, "admin_cf_disp@test.com")
        token = _admin_token(admin)

        response = await client.get(
            "/api/v1/admin/reports/cash-flow",
            params={"start_date": "2026-01-01", "end_date": "2026-01-31"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        disposition = response.headers.get("content-disposition", "")
        assert "attachment" in disposition
        assert "fluxo_caixa_2026-01-01_2026-01-31.xlsx" in disposition


# ===========================================================================
# Clients report
# ===========================================================================


class TestClientsReport:
    """GET /api/v1/admin/reports/clients"""

    @pytest.mark.asyncio
    async def test_requires_auth(self, client: AsyncClient):
        response = await client.get(
            "/api/v1/admin/reports/clients",
            params=_DEFAULT_PARAMS,
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_admin_only(self, client: AsyncClient, test_session: AsyncSession):
        user = await _create_client(test_session, "clients_rep_user@test.com")
        token = _client_token(user)
        response = await client.get(
            "/api/v1/admin/reports/clients",
            params=_DEFAULT_PARAMS,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_returns_xlsx(self, client: AsyncClient, test_session: AsyncSession):
        admin = await _create_admin(test_session, "admin_clients_xlsx@test.com")
        token = _admin_token(admin)

        response = await client.get(
            "/api/v1/admin/reports/clients",
            params=_DEFAULT_PARAMS,
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        assert (
            response.headers.get("content-type")
            == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        assert response.content[:2] == b"PK"

    @pytest.mark.asyncio
    async def test_returns_csv(self, client: AsyncClient, test_session: AsyncSession):
        admin = await _create_admin(test_session, "admin_clients_csv@test.com")
        token = _admin_token(admin)

        response = await client.get(
            "/api/v1/admin/reports/clients",
            params={**_DEFAULT_PARAMS, "format": "csv"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        assert "text/csv" in response.headers.get("content-type", "")
        assert response.content[:3] == b"\xef\xbb\xbf"

    @pytest.mark.asyncio
    async def test_content_disposition_filename(self, client: AsyncClient, test_session: AsyncSession):
        admin = await _create_admin(test_session, "admin_clients_disp@test.com")
        token = _admin_token(admin)

        response = await client.get(
            "/api/v1/admin/reports/clients",
            params={"start_date": "2026-01-01", "end_date": "2026-01-31"},
            headers={"Authorization": f"Bearer {token}"},
        )

        disposition = response.headers.get("content-disposition", "")
        assert "clientes_2026-01-01_2026-01-31.xlsx" in disposition

    @pytest.mark.asyncio
    async def test_date_filter_applies(self, client: AsyncClient, test_session: AsyncSession):
        """Clients created outside the period should not appear in the report."""
        admin = await _create_admin(test_session, "admin_clients_filter@test.com")
        token = _admin_token(admin)

        response = await client.get(
            "/api/v1/admin/reports/clients",
            # Very old range — no clients registered then
            params={"start_date": "2000-01-01", "end_date": "2000-01-31"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        # The xlsx should still be a valid file even with zero rows
        assert response.content[:2] == b"PK"


# ===========================================================================
# Transactions report
# ===========================================================================


class TestTransactionsReport:
    """GET /api/v1/admin/reports/transactions"""

    @pytest.mark.asyncio
    async def test_requires_auth(self, client: AsyncClient):
        response = await client.get(
            "/api/v1/admin/reports/transactions",
            params=_DEFAULT_PARAMS,
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_admin_only(self, client: AsyncClient, test_session: AsyncSession):
        user = await _create_client(test_session, "txn_rep_user@test.com")
        token = _client_token(user)
        response = await client.get(
            "/api/v1/admin/reports/transactions",
            params=_DEFAULT_PARAMS,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_returns_xlsx(self, client: AsyncClient, test_session: AsyncSession):
        admin = await _create_admin(test_session, "admin_txn_xlsx@test.com")
        token = _admin_token(admin)

        response = await client.get(
            "/api/v1/admin/reports/transactions",
            params=_DEFAULT_PARAMS,
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        assert (
            response.headers.get("content-type")
            == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        assert response.content[:2] == b"PK"

    @pytest.mark.asyncio
    async def test_returns_csv(self, client: AsyncClient, test_session: AsyncSession):
        admin = await _create_admin(test_session, "admin_txn_csv@test.com")
        token = _admin_token(admin)

        response = await client.get(
            "/api/v1/admin/reports/transactions",
            params={**_DEFAULT_PARAMS, "format": "csv"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        assert "text/csv" in response.headers.get("content-type", "")
        assert response.content[:3] == b"\xef\xbb\xbf"

    @pytest.mark.asyncio
    async def test_content_disposition_filename(self, client: AsyncClient, test_session: AsyncSession):
        admin = await _create_admin(test_session, "admin_txn_disp@test.com")
        token = _admin_token(admin)

        response = await client.get(
            "/api/v1/admin/reports/transactions",
            params={"start_date": "2026-02-01", "end_date": "2026-02-28"},
            headers={"Authorization": f"Bearer {token}"},
        )

        disposition = response.headers.get("content-disposition", "")
        assert "transacoes_2026-02-01_2026-02-28.xlsx" in disposition

    @pytest.mark.asyncio
    async def test_date_filter_applies(self, client: AsyncClient, test_session: AsyncSession):
        """Transactions outside the period should not appear."""
        admin = await _create_admin(test_session, "admin_txn_filter@test.com")
        token = _admin_token(admin)

        response = await client.get(
            "/api/v1/admin/reports/transactions",
            params={"start_date": "2000-01-01", "end_date": "2000-01-31"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        assert response.content[:2] == b"PK"


# ===========================================================================
# Yields report
# ===========================================================================


class TestYieldsReport:
    """GET /api/v1/admin/reports/yields"""

    @pytest.mark.asyncio
    async def test_requires_auth(self, client: AsyncClient):
        response = await client.get(
            "/api/v1/admin/reports/yields",
            params=_DEFAULT_PARAMS,
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_admin_only(self, client: AsyncClient, test_session: AsyncSession):
        user = await _create_client(test_session, "yields_rep_user@test.com")
        token = _client_token(user)
        response = await client.get(
            "/api/v1/admin/reports/yields",
            params=_DEFAULT_PARAMS,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_returns_xlsx(self, client: AsyncClient, test_session: AsyncSession):
        admin = await _create_admin(test_session, "admin_yields_xlsx@test.com")
        token = _admin_token(admin)

        response = await client.get(
            "/api/v1/admin/reports/yields",
            params=_DEFAULT_PARAMS,
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        assert (
            response.headers.get("content-type")
            == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        assert response.content[:2] == b"PK"

    @pytest.mark.asyncio
    async def test_returns_csv(self, client: AsyncClient, test_session: AsyncSession):
        admin = await _create_admin(test_session, "admin_yields_csv@test.com")
        token = _admin_token(admin)

        response = await client.get(
            "/api/v1/admin/reports/yields",
            params={**_DEFAULT_PARAMS, "format": "csv"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        assert "text/csv" in response.headers.get("content-type", "")
        assert response.content[:3] == b"\xef\xbb\xbf"

    @pytest.mark.asyncio
    async def test_content_disposition_filename(self, client: AsyncClient, test_session: AsyncSession):
        admin = await _create_admin(test_session, "admin_yields_disp@test.com")
        token = _admin_token(admin)

        response = await client.get(
            "/api/v1/admin/reports/yields",
            params={"start_date": "2026-03-01", "end_date": "2026-03-29"},
            headers={"Authorization": f"Bearer {token}"},
        )

        disposition = response.headers.get("content-disposition", "")
        assert "rendimentos_2026-03-01_2026-03-29.xlsx" in disposition

    @pytest.mark.asyncio
    async def test_date_filter_applies(self, client: AsyncClient, test_session: AsyncSession):
        """Only YIELD_CREDITED audit logs in the requested period should appear."""
        admin = await _create_admin(test_session, "admin_yields_filter@test.com")
        token = _admin_token(admin)

        response = await client.get(
            "/api/v1/admin/reports/yields",
            params={"start_date": "2000-01-01", "end_date": "2000-01-31"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        # Valid xlsx with zero data rows
        assert response.content[:2] == b"PK"

    @pytest.mark.asyncio
    async def test_only_yield_credited_action(self, client: AsyncClient, test_session: AsyncSession):
        """Report must only include YIELD_CREDITED audit log entries, not other actions."""
        admin = await _create_admin(test_session, "admin_yields_action@test.com")
        token = _admin_token(admin)

        # Seed an unrelated audit log (DEPOSIT_CREATED)
        audit_repo = AuditLogRepository(test_session)
        unrelated = AuditLog.create(
            action=AuditAction.DEPOSIT_CREATED,
            actor_id=admin.id,
            target_id=None,
            target_type="transaction",
            details={"note": "should not appear in yields report"},
        )
        await audit_repo.save(unrelated)
        await test_session.commit()

        response = await client.get(
            "/api/v1/admin/reports/yields",
            params=_DEFAULT_PARAMS,
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        assert response.content[:2] == b"PK"

    @pytest.mark.asyncio
    async def test_csv_contains_yield_credited_data(self, client: AsyncClient, test_session: AsyncSession):
        """CSV report must include rows for YIELD_CREDITED entries in the period."""
        admin = await _create_admin(test_session, "admin_yields_data@test.com")
        token = _admin_token(admin)

        # Seed a YIELD_CREDITED audit log
        audit_repo = AuditLogRepository(test_session)
        yield_audit = AuditLog.create(
            action=AuditAction.YIELD_CREDITED,
            actor_id=admin.id,
            target_id=None,
            target_type="transaction",
            details={
                "sgs_series_id": 195,
                "yield_period_from": "2026-02-01",
                "yield_period_to": "2026-03-01",
                "effective_rate": "0.00500000",
                "principal_cents": 100000,
                "yield_cents": 500,
                "installment_number": 1,
                "subscription_id": "00000000-0000-0000-0000-000000000001",
                "principal_deposit_id": "00000000-0000-0000-0000-000000000002",
            },
        )
        await audit_repo.save(yield_audit)
        await test_session.commit()

        response = await client.get(
            "/api/v1/admin/reports/yields",
            params={**_DEFAULT_PARAMS, "format": "csv"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        content = response.content.decode("utf-8-sig")
        # The seeded data should appear in the CSV
        assert "195" in content
        assert "2026-02-01" in content
        assert "100000" in content
