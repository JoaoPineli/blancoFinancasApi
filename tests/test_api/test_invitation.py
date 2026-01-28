"""Tests for invitation and activation API endpoints."""

import pytest
from httpx import AsyncClient
from uuid import uuid4
import random
import re
from unittest.mock import AsyncMock, patch

from app.domain.entities.user import User, UserRole, UserStatus
from app.domain.entities.wallet import Wallet
from app.domain.value_objects.cpf import CPF
from app.domain.value_objects.email import Email
from app.infrastructure.db.repositories.user_repository import UserRepository
from app.infrastructure.db.repositories.wallet_repository import WalletRepository
from app.infrastructure.email.email_sender import EmailSendResult
from app.infrastructure.security.jwt import create_access_token
from app.infrastructure.security.password import hash_password


def generate_valid_cpf() -> str:
    """Generate a valid, formatted CPF string for testing."""
    # Generate 9 random digits avoiding all-equal sequences
    while True:
        digits = [random.randint(0, 9) for _ in range(9)]
        if len(set(digits)) > 1:
            break

    # First check digit
    s1 = sum(d * w for d, w in zip(digits, range(10, 1, -1)))
    r1 = s1 % 11
    d1 = 0 if r1 < 2 else 11 - r1

    # Second check digit
    s2 = sum(d * w for d, w in zip(digits, range(11, 2, -1))) + d1 * 2
    r2 = s2 % 11
    d2 = 0 if r2 < 2 else 11 - r2

    full = digits + [d1, d2]
    return f"{full[0]}{full[1]}{full[2]}.{full[3]}{full[4]}{full[5]}.{full[6]}{full[7]}{full[8]}-{full[9]}{full[10]}"


# Store sent emails for testing
_sent_emails = []


def _mock_send_transactional(*args, **kwargs):
    """Mock email sending that records sent emails."""
    _sent_emails.append({"args": args, "kwargs": kwargs})
    return EmailSendResult(success=True, status_code=202, message_id="mock-id")


class TestInvitationEndpoint:
    """Test admin invitation endpoint."""

    @pytest.mark.asyncio
    @patch("app.api.v1.endpoints.admin.SendGridClient")
    async def test_invite_user_success(self, mock_sendgrid_class, client: AsyncClient, test_session_factory):
        """Test successful user invitation by admin."""
        # Setup mock
        mock_instance = AsyncMock()
        mock_instance.send_transactional.return_value = EmailSendResult(
            success=True, status_code=202, message_id="mock-id"
        )
        mock_sendgrid_class.return_value = mock_instance

        async with test_session_factory() as session:
            user_repo = UserRepository(session)
            wallet_repo = WalletRepository(session)

            admin = User.create(
                cpf=CPF(generate_valid_cpf()),
                email=Email(f"admin_{uuid4().hex[:8]}@example.com"),
                name="Admin User",
                password_hash=hash_password("adminpassword"),
                role=UserRole.ADMIN,
            )
            saved_admin = await user_repo.save(admin)

            wallet = Wallet.create(user_id=saved_admin.id)
            await wallet_repo.save(wallet)
            await session.commit()

            token = create_access_token(subject=saved_admin.id, role=saved_admin.role)

        response = await client.post(
            "/api/v1/admin/invite",
            json={
                "name": "New User",
                "email": "newuser@example.com",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "newuser@example.com"
        assert data["name"] == "New User"
        # Token should NOT be in response
        assert "activation_token" not in data
        assert "message" in data

        # Verify email was sent
        mock_instance.send_transactional.assert_called_once()
        call_kwargs = mock_instance.send_transactional.call_args
        assert call_kwargs.kwargs["to_email"] == "newuser@example.com"
        assert "token=" in call_kwargs.kwargs["html_content"]

    @pytest.mark.asyncio
    async def test_invite_user_requires_admin(self, client: AsyncClient, test_session_factory):
        """Test that invitation requires admin role."""
        async with test_session_factory() as session:
            user_repo = UserRepository(session)
            wallet_repo = WalletRepository(session)

            # Create a regular client user
            client_user = User.create(
                cpf=CPF(generate_valid_cpf()),
                email=Email(f"client_{uuid4().hex[:8]}@example.com"),
                name="Client User",
                password_hash=hash_password("clientpassword"),
                role=UserRole.CLIENT,
            )
            saved_client = await user_repo.save(client_user)

            wallet = Wallet.create(user_id=saved_client.id)
            await wallet_repo.save(wallet)
            await session.commit()

            token = create_access_token(subject=saved_client.id, role=saved_client.role)

        response = await client.post(
            "/api/v1/admin/invite",
            json={
                "name": "New User",
                "email": "shouldfail@example.com",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_invite_user_without_auth(self, client: AsyncClient):
        """Test that invitation without auth returns 401."""
        response = await client.post(
            "/api/v1/admin/invite",
            json={
                "name": "New User",
                "email": "noauth@example.com",
            },
        )

        assert response.status_code == 401

    @pytest.mark.asyncio
    @patch("app.api.v1.endpoints.admin.SendGridClient")
    async def test_invite_user_duplicate_email(self, mock_sendgrid_class, client: AsyncClient, test_session_factory):
        """Test that inviting duplicate email returns 409."""
        # Setup mock
        mock_instance = AsyncMock()
        mock_instance.send_transactional.return_value = EmailSendResult(
            success=True, status_code=202, message_id="mock-id"
        )
        mock_sendgrid_class.return_value = mock_instance

        async with test_session_factory() as session:
            user_repo = UserRepository(session)
            wallet_repo = WalletRepository(session)

            admin = User.create(
                cpf=CPF(generate_valid_cpf()),
                email=Email(f"admin_{uuid4().hex[:8]}@example.com"),
                name="Admin User",
                password_hash=hash_password("adminpassword"),
                role=UserRole.ADMIN,
            )
            saved_admin = await user_repo.save(admin)

            wallet = Wallet.create(user_id=saved_admin.id)
            await wallet_repo.save(wallet)
            await session.commit()

            token = create_access_token(subject=saved_admin.id, role=saved_admin.role)

        email = f"duplicate_{uuid4().hex[:8]}@example.com"

        # First invitation
        await client.post(
            "/api/v1/admin/invite",
            json={"name": "First User", "email": email},
            headers={"Authorization": f"Bearer {token}"},
        )

        # Second invitation with same email
        response = await client.post(
            "/api/v1/admin/invite",
            json={"name": "Second User", "email": email},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 409


class TestActivationEndpoint:
    """Test public activation endpoint."""

    @pytest.mark.asyncio
    @patch("app.api.v1.endpoints.admin.SendGridClient")
    async def test_activate_account_success(
        self, mock_sendgrid_class, client: AsyncClient, test_session_factory
    ):
        """Test successful account activation."""
        # Setup mock that captures sent email
        mock_instance = AsyncMock()
        sent_emails = []

        async def capture_email(*args, **kwargs):
            sent_emails.append(kwargs)
            return EmailSendResult(success=True, status_code=202, message_id="mock-id")

        mock_instance.send_transactional.side_effect = capture_email
        mock_sendgrid_class.return_value = mock_instance

        # Create admin and invite user
        async with test_session_factory() as session:
            user_repo = UserRepository(session)
            wallet_repo = WalletRepository(session)

            admin = User.create(
                cpf=CPF(generate_valid_cpf()),
                email=Email(f"admin_{uuid4().hex[:8]}@example.com"),
                name="Admin User",
                password_hash=hash_password("adminpassword"),
                role=UserRole.ADMIN,
            )
            saved_admin = await user_repo.save(admin)

            wallet = Wallet.create(user_id=saved_admin.id)
            await wallet_repo.save(wallet)
            await session.commit()

            admin_token = create_access_token(subject=saved_admin.id, role=saved_admin.role)

        email = f"activate_{uuid4().hex[:8]}@example.com"
        invite_response = await client.post(
            "/api/v1/admin/invite",
            json={"name": "Test User", "email": email},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert invite_response.status_code == 201

        # Extract token from mock email
        assert len(sent_emails) == 1
        html_content = sent_emails[0]["html_content"]
        token_match = re.search(r'token=([A-Za-z0-9_-]+)', html_content)
        assert token_match is not None
        activation_token = token_match.group(1)

        # Activate the account
        response = await client.post(
            "/api/v1/auth/activate",
            json={
                "token": activation_token,
                "password": "SecurePassword123!",
                "cpf": generate_valid_cpf(),
                "phone": "11999999999",
                "nickname": "TestNick",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["email"] == email
        assert data["message"] == "Account activated successfully"

    @pytest.mark.asyncio
    async def test_activate_account_invalid_token(self, client: AsyncClient):
        """Test activation with invalid token returns 400."""
        response = await client.post(
            "/api/v1/auth/activate",
            json={
                "token": "invalid_token_that_is_long_enough_to_pass_validation",
                "password": "SecurePassword123!",
                "cpf": "529.982.247-25",
                "phone": "11999999999",
            },
        )

        assert response.status_code == 400
        assert "Invalid or expired" in response.json()["detail"]

    @pytest.mark.asyncio
    @patch("app.api.v1.endpoints.admin.SendGridClient")
    async def test_activate_account_token_reuse_fails(
        self, mock_sendgrid_class, client: AsyncClient, test_session_factory
    ):
        """Test that reusing activation token fails."""
        # Setup mock that captures sent email
        mock_instance = AsyncMock()
        sent_emails = []

        async def capture_email(*args, **kwargs):
            sent_emails.append(kwargs)
            return EmailSendResult(success=True, status_code=202, message_id="mock-id")

        mock_instance.send_transactional.side_effect = capture_email
        mock_sendgrid_class.return_value = mock_instance

        # Create admin and invite user
        async with test_session_factory() as session:
            user_repo = UserRepository(session)
            wallet_repo = WalletRepository(session)

            admin = User.create(
                cpf=CPF(generate_valid_cpf()),
                email=Email(f"admin_{uuid4().hex[:8]}@example.com"),
                name="Admin User",
                password_hash=hash_password("adminpassword"),
                role=UserRole.ADMIN,
            )
            saved_admin = await user_repo.save(admin)

            wallet = Wallet.create(user_id=saved_admin.id)
            await wallet_repo.save(wallet)
            await session.commit()

            admin_token = create_access_token(subject=saved_admin.id, role=saved_admin.role)

        email = f"reuse_{uuid4().hex[:8]}@example.com"
        await client.post(
            "/api/v1/admin/invite",
            json={"name": "Test User", "email": email},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        # Extract token from mock email
        html_content = sent_emails[0]["html_content"]
        token_match = re.search(r'token=([A-Za-z0-9_-]+)', html_content)
        activation_token = token_match.group(1)

        # First activation succeeds
        response1 = await client.post(
            "/api/v1/auth/activate",
            json={
                "token": activation_token,
                "password": "SecurePassword123!",
                "cpf": generate_valid_cpf(),
                "phone": "11999999999",
            },
        )
        assert response1.status_code == 200

        # Second activation with same token fails
        response2 = await client.post(
            "/api/v1/auth/activate",
            json={
                "token": activation_token,
                "password": "AnotherPassword!",
                "cpf": generate_valid_cpf(),
                "phone": "11888888888",
            },
        )
        assert response2.status_code == 400

    @pytest.mark.asyncio
    @patch("app.api.v1.endpoints.admin.SendGridClient")
    async def test_activate_account_invalid_cpf(
        self, mock_sendgrid_class, client: AsyncClient, test_session_factory
    ):
        """Test activation with invalid CPF returns error."""
        # Setup mock
        mock_instance = AsyncMock()
        sent_emails = []

        async def capture_email(*args, **kwargs):
            sent_emails.append(kwargs)
            return EmailSendResult(success=True, status_code=202, message_id="mock-id")

        mock_instance.send_transactional.side_effect = capture_email
        mock_sendgrid_class.return_value = mock_instance

        # Create admin and invite user
        async with test_session_factory() as session:
            user_repo = UserRepository(session)
            wallet_repo = WalletRepository(session)

            admin = User.create(
                cpf=CPF(generate_valid_cpf()),
                email=Email(f"admin_{uuid4().hex[:8]}@example.com"),
                name="Admin User",
                password_hash=hash_password("adminpassword"),
                role=UserRole.ADMIN,
            )
            saved_admin = await user_repo.save(admin)

            wallet = Wallet.create(user_id=saved_admin.id)
            await wallet_repo.save(wallet)
            await session.commit()

            admin_token = create_access_token(subject=saved_admin.id, role=saved_admin.role)

        email = f"badcpf_{uuid4().hex[:8]}@example.com"
        await client.post(
            "/api/v1/admin/invite",
            json={"name": "Test User", "email": email},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        # Extract token from mock email
        html_content = sent_emails[0]["html_content"]
        token_match = re.search(r'token=([A-Za-z0-9_-]+)', html_content)
        activation_token = token_match.group(1)

        response = await client.post(
            "/api/v1/auth/activate",
            json={
                "token": activation_token,
                "password": "SecurePassword123!",
                "cpf": "111.111.111-11",  # Invalid CPF
                "phone": "11999999999",
            },
        )

        assert response.status_code == 400

    @pytest.mark.asyncio
    @patch("app.api.v1.endpoints.admin.SendGridClient")
    async def test_activate_account_does_not_require_jwt(
        self, mock_sendgrid_class, client: AsyncClient, test_session_factory
    ):
        """Test that activation endpoint is public (no JWT required)."""
        # Setup mock
        mock_instance = AsyncMock()
        sent_emails = []

        async def capture_email(*args, **kwargs):
            sent_emails.append(kwargs)
            return EmailSendResult(success=True, status_code=202, message_id="mock-id")

        mock_instance.send_transactional.side_effect = capture_email
        mock_sendgrid_class.return_value = mock_instance

        # Create admin and invite user
        async with test_session_factory() as session:
            user_repo = UserRepository(session)
            wallet_repo = WalletRepository(session)

            admin = User.create(
                cpf=CPF(generate_valid_cpf()),
                email=Email(f"admin_{uuid4().hex[:8]}@example.com"),
                name="Admin User",
                password_hash=hash_password("adminpassword"),
                role=UserRole.ADMIN,
            )
            saved_admin = await user_repo.save(admin)

            wallet = Wallet.create(user_id=saved_admin.id)
            await wallet_repo.save(wallet)
            await session.commit()

            admin_token = create_access_token(subject=saved_admin.id, role=saved_admin.role)

        email = f"nojwt_{uuid4().hex[:8]}@example.com"
        await client.post(
            "/api/v1/admin/invite",
            json={"name": "Test User", "email": email},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        # Extract token from mock email
        html_content = sent_emails[0]["html_content"]
        token_match = re.search(r'token=([A-Za-z0-9_-]+)', html_content)
        activation_token = token_match.group(1)

        # No Authorization header - this is a public endpoint
        response = await client.post(
            "/api/v1/auth/activate",
            json={
                "token": activation_token,
                "password": "SecurePassword123!",
                "cpf": generate_valid_cpf(),
                "phone": "11999999999",
            },
        )

        # Should not return 401 (public endpoint)
        assert response.status_code != 401
        assert response.status_code == 200


class TestInvitedUserCannotLogin:
    """Test that invited users cannot use normal login."""

    @pytest.mark.asyncio
    @patch("app.api.v1.endpoints.admin.SendGridClient")
    async def test_invited_user_cannot_login(
        self, mock_sendgrid_class, client: AsyncClient, test_session_factory
    ):
        """Test that invited users cannot authenticate via login."""
        # Setup mock
        mock_instance = AsyncMock()
        mock_instance.send_transactional.return_value = EmailSendResult(
            success=True, status_code=202, message_id="mock-id"
        )
        mock_sendgrid_class.return_value = mock_instance

        async with test_session_factory() as session:
            user_repo = UserRepository(session)
            wallet_repo = WalletRepository(session)

            admin = User.create(
                cpf=CPF(generate_valid_cpf()),
                email=Email(f"admin_{uuid4().hex[:8]}@example.com"),
                name="Admin User",
                password_hash=hash_password("adminpassword"),
                role=UserRole.ADMIN,
            )
            saved_admin = await user_repo.save(admin)

            wallet = Wallet.create(user_id=saved_admin.id)
            await wallet_repo.save(wallet)
            await session.commit()

            token = create_access_token(subject=saved_admin.id, role=saved_admin.role)

        # Invite a user
        email = f"nologin_{uuid4().hex[:8]}@example.com"
        await client.post(
            "/api/v1/admin/invite",
            json={"name": "Test User", "email": email},
            headers={"Authorization": f"Bearer {token}"},
        )

        # Try to login (should fail with generic error)
        response = await client.post(
            "/api/v1/auth/login",
            json={
                "email": email,
                "password": "anypassword",
            },
        )

        assert response.status_code == 401
        # Should not reveal that user exists but is invited
        assert "Invalid email or password" in response.json()["detail"]
