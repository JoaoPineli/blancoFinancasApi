"""Tests for authentication endpoints."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.user import User, UserRole, UserStatus
from app.domain.value_objects.cpf import CPF
from app.domain.value_objects.email import Email
from app.infrastructure.db.repositories.user_repository import UserRepository
from app.infrastructure.security.jwt import create_access_token
from app.infrastructure.security.password import hash_password


class TestAuthEndpoints:
    """Test authentication API endpoints."""

    @pytest.mark.asyncio
    async def test_health_check(self, client: AsyncClient):
        """Test health check endpoint."""
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}

    @pytest.mark.asyncio
    async def test_register_invalid_cpf(self, client: AsyncClient):
        """Test registration with invalid CPF returns error."""
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "cpf": "111.111.111-11",  # Invalid CPF
                "email": "test@example.com",
                "name": "Test User",
                "password": "securepassword123",
            },
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_register_invalid_email(self, client: AsyncClient):
        """Test registration with invalid email returns error."""
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "cpf": "529.982.247-25",
                "email": "invalid-email",
                "name": "Test User",
                "password": "securepassword123",
            },
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_login_missing_credentials(self, client: AsyncClient):
        """Test login with missing credentials returns error."""
        response = await client.post(
            "/api/v1/auth/login",
            json={},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_protected_endpoint_without_token(self, client: AsyncClient):
        """Test protected endpoint without token returns 401."""
        response = await client.get("/api/v1/auth/me")
        assert response.status_code == 401


class TestAuthMeEndpoint:
    """Test /auth/me endpoint for session restoration."""

    @pytest.fixture
    async def active_user(self, test_session: AsyncSession) -> User:
        """Create an active user for testing."""
        user = User.create(
            cpf=CPF("529.982.247-25"),
            email=Email("testuser@example.com"),
            name="Test User",
            password_hash=hash_password("securepassword123"),
            role=UserRole.CLIENT,
            phone="11999999999",
        )
        repo = UserRepository(test_session)
        await repo.save(user)
        await test_session.commit()
        return user

    @pytest.fixture
    async def admin_user(self, test_session: AsyncSession) -> User:
        """Create an admin user for testing."""
        user = User.create(
            cpf=CPF("234.567.890-92"),
            email=Email("admin@example.com"),
            name="Admin User",
            password_hash=hash_password("adminpassword123"),
            role=UserRole.ADMIN,
            phone="11888888888",
        )
        repo = UserRepository(test_session)
        await repo.save(user)
        await test_session.commit()
        return user

    @pytest.fixture
    async def inactive_user(self, test_session: AsyncSession) -> User:
        """Create an inactive user for testing."""
        user = User.create(
            cpf=CPF("345.678.901-75"),
            email=Email("inactive@example.com"),
            name="Inactive User",
            password_hash=hash_password("inactivepassword123"),
            role=UserRole.CLIENT,
            phone="11777777777",
        )
        # Set status to inactive after creation
        user.status = UserStatus.INACTIVE
        repo = UserRepository(test_session)
        await repo.save(user)
        await test_session.commit()
        return user

    @pytest.mark.asyncio
    async def test_me_without_token_returns_401(self, client: AsyncClient):
        """Test /me endpoint without authorization header returns 401."""
        response = await client.get("/api/v1/auth/me")
        assert response.status_code == 401
        assert "Missing authorization header" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_me_with_invalid_token_format_returns_401(self, client: AsyncClient):
        """Test /me endpoint with invalid token format returns 401."""
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "InvalidFormat token123"},
        )
        assert response.status_code == 401
        assert "Invalid authorization header format" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_me_with_malformed_jwt_returns_401(self, client: AsyncClient):
        """Test /me endpoint with malformed JWT returns 401."""
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer not.a.valid.jwt"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_me_with_expired_token_returns_401(self, client: AsyncClient):
        """Test /me endpoint with expired token returns 401."""
        # Create an expired token (negative expiration)
        from datetime import timedelta
        from uuid import uuid4

        expired_token = create_access_token(
            subject=uuid4(),
            role=UserRole.CLIENT,
            expires_delta=timedelta(seconds=-1),  # Already expired
        )
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {expired_token}"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_me_with_valid_token_returns_user_profile(
        self, client: AsyncClient, active_user: User
    ):
        """Test /me endpoint with valid token returns user profile."""
        token = create_access_token(
            subject=active_user.id,
            role=active_user.role,
        )
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(active_user.id)
        assert data["email"] == active_user.email.value
        assert data["name"] == active_user.name
        assert data["role"] == active_user.role.value
        assert data["status"] == active_user.status.value
        assert active_user.cpf is not None
        assert data["cpf"] == active_user.cpf.formatted

    @pytest.mark.asyncio
    async def test_me_with_admin_token_returns_admin_profile(
        self, client: AsyncClient, admin_user: User
    ):
        """Test /me endpoint with admin token returns admin profile."""
        token = create_access_token(
            subject=admin_user.id,
            role=admin_user.role,
        )
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(admin_user.id)
        assert data["role"] == "admin"

    @pytest.mark.asyncio
    async def test_me_with_inactive_user_returns_403(
        self, client: AsyncClient, inactive_user: User
    ):
        """Test /me endpoint with inactive user returns 403."""
        token = create_access_token(
            subject=inactive_user.id,
            role=inactive_user.role,
        )
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403
        assert "inactive" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_me_with_nonexistent_user_returns_401(self, client: AsyncClient):
        """Test /me endpoint with token for non-existent user returns 401."""
        from uuid import uuid4

        token = create_access_token(
            subject=uuid4(),  # Non-existent user ID
            role=UserRole.CLIENT,
        )
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 401
        assert "User not found" in response.json()["detail"]

    @pytest.fixture
    async def fields_test_user(self, test_session: AsyncSession) -> User:
        """Create a unique user for the required fields test."""
        user = User.create(
            cpf=CPF("456.789.012-49"),
            email=Email("fieldstest@example.com"),
            name="Fields Test User",
            password_hash=hash_password("testpassword123"),
            role=UserRole.CLIENT,
            phone="11666666666",
        )
        repo = UserRepository(test_session)
        await repo.save(user)
        await test_session.commit()
        return user

    @pytest.mark.asyncio
    async def test_me_response_contains_required_fields(
        self, client: AsyncClient, fields_test_user: User
    ):
        """Test /me endpoint response contains all required fields for session restoration."""
        token = create_access_token(
            subject=fields_test_user.id,
            role=fields_test_user.role,
        )
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()

        # Verify all required fields for session restoration are present
        required_fields = ["id", "name", "email", "cpf", "role", "status", "phone", "created_at"]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
