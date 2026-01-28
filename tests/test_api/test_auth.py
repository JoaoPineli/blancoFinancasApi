"""Tests for authentication endpoints."""

import pytest
from httpx import AsyncClient


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
        response = await client.get("/api/v1/users/me")
        assert response.status_code == 401
