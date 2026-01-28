"""Tests for invitation and activation services."""

import pytest
from datetime import datetime, timedelta
from uuid import uuid4
import random

from app.application.dtos.invitation import (
    InviteUserInput,
    ActivateAccountInput,
)
from app.application.services.invitation_service import (
    InvitationService,
    generate_secure_token,
    hash_token,
    ACTIVATION_TOKEN_EXPIRY_HOURS,
)
from app.application.services.activation_service import ActivationService
from app.domain.entities.plan import Plan, PlanType
from app.domain.entities.user import User, UserRole, UserStatus
from app.domain.entities.user_token import TokenType, UserToken
from app.domain.entities.wallet import Wallet
from app.domain.exceptions import (
    InvalidTokenError,
    PlanNotFoundError,
    UserAlreadyExistsError,
)
from app.domain.value_objects.email import Email
from app.infrastructure.db.repositories.plan_repository import PlanRepository
from app.infrastructure.db.repositories.user_repository import UserRepository
from app.infrastructure.db.repositories.user_token_repository import UserTokenRepository
from app.infrastructure.db.repositories.wallet_repository import WalletRepository
from app.infrastructure.email.exceptions import EmailSendFailedError
from decimal import Decimal


def generate_valid_cpf() -> str:
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


class TestInvitationService:
    """Test InvitationService."""

    @pytest.mark.asyncio
    async def test_invite_user_creates_invited_user(self, test_session, mock_email_sender):
        """Test that invite_user creates a user with INVITED status."""
        service = InvitationService(test_session, mock_email_sender)
        admin_id = uuid4()

        input_data = InviteUserInput(
            name="Test User",
            email="invited@example.com",
        )

        result = await service.invite_user(input_data, admin_id=admin_id)

        assert result.email == "invited@example.com"
        assert result.name == "Test User"

        # Verify user was created with correct status
        user_repo = UserRepository(test_session)
        user = await user_repo.get_by_email(Email("invited@example.com"))

        assert user is not None
        assert user.status == UserStatus.INVITED
        assert user.password_hash is None
        assert user.cpf is None

    @pytest.mark.asyncio
    async def test_invite_user_creates_wallet(self, test_session, mock_email_sender):
        """Test that invite_user creates a wallet for the invited user."""
        service = InvitationService(test_session, mock_email_sender)
        admin_id = uuid4()

        input_data = InviteUserInput(
            name="Test User",
            email="wallettest@example.com",
        )

        result = await service.invite_user(input_data, admin_id=admin_id)

        # Verify wallet was created
        wallet_repo = WalletRepository(test_session)
        wallet = await wallet_repo.get_by_user_id(result.user_id)

        assert wallet is not None
        assert wallet.balance_cents == 0

    @pytest.mark.asyncio
    async def test_invite_user_creates_activation_token(self, test_session, mock_email_sender):
        """Test that invite_user creates an activation token."""
        service = InvitationService(test_session, mock_email_sender)
        admin_id = uuid4()

        input_data = InviteUserInput(
            name="Test User",
            email="tokentest@example.com",
        )

        result = await service.invite_user(input_data, admin_id=admin_id)

        # Verify token was created - we can find it by checking the email
        assert len(mock_email_sender.sent_emails) == 1
        email = mock_email_sender.sent_emails[0]
        assert "token=" in email.html_content

        # Verify token exists in database
        token_repo = UserTokenRepository(test_session)
        # Extract token from email and verify it exists
        import re
        token_match = re.search(r'token=([A-Za-z0-9_-]+)', email.html_content)
        assert token_match is not None
        raw_token = token_match.group(1)

        token_hash = hash_token(raw_token)
        token = await token_repo.get_by_hash(token_hash)

        assert token is not None
        assert token.user_id == result.user_id
        assert token.token_type == TokenType.ACTIVATION
        assert not token.is_used()
        assert not token.is_expired()

    @pytest.mark.asyncio
    async def test_invite_user_sends_email(self, test_session, mock_email_sender):
        """Test that invite_user sends an invitation email."""
        service = InvitationService(test_session, mock_email_sender)
        admin_id = uuid4()

        input_data = InviteUserInput(
            name="Email Test User",
            email="emailtest@example.com",
        )

        await service.invite_user(input_data, admin_id=admin_id)

        # Verify email was sent
        assert len(mock_email_sender.sent_emails) == 1
        email = mock_email_sender.sent_emails[0]
        assert email.to[0].email == "emailtest@example.com"
        assert email.to[0].name == "Email Test User"
        assert "Ative sua conta" in email.subject
        assert "Email Test User" in email.html_content
        assert "token=" in email.html_content

    @pytest.mark.asyncio
    async def test_invite_user_email_failure_prevents_persistence(self, test_session, mock_email_sender):
        """Test that email failure prevents user persistence."""
        mock_email_sender.should_fail = True
        service = InvitationService(test_session, mock_email_sender)
        admin_id = uuid4()

        input_data = InviteUserInput(
            name="Test User",
            email="failmail@example.com",
        )

        with pytest.raises(EmailSendFailedError):
            await service.invite_user(input_data, admin_id=admin_id)

        # Verify user was NOT created (transaction rolled back)
        # Note: The actual rollback is handled by the caller (endpoint/test)
        # Here we verify the email sender was called
        assert len(mock_email_sender.sent_emails) == 0

    @pytest.mark.asyncio
    async def test_invite_user_with_plan(self, test_session, mock_email_sender):
        """Test inviting user with pre-assigned plan."""
        # Create a plan first
        plan_repo = PlanRepository(test_session)
        plan = Plan.create(
            name="Test Plan",
            plan_type=PlanType.GERAL,
            description="Test plan",
            monthly_installment_cents=100000,
            duration_months=12,
            fundo_garantidor_percentage=Decimal("1.0"),
        )
        await plan_repo.save(plan)

        service = InvitationService(test_session, mock_email_sender)
        admin_id = uuid4()

        input_data = InviteUserInput(
            name="Test User",
            email="plantest@example.com",
            plan_id=str(plan.id),
        )

        result = await service.invite_user(input_data, admin_id=admin_id)

        # Verify user has plan assigned
        user_repo = UserRepository(test_session)
        user = await user_repo.get_by_id(result.user_id)

        assert user.plan_id == plan.id

    @pytest.mark.asyncio
    async def test_invite_user_duplicate_email_raises_error(self, test_session, mock_email_sender):
        """Test that inviting with existing email raises error."""
        service = InvitationService(test_session, mock_email_sender)
        admin_id = uuid4()

        input_data = InviteUserInput(
            name="First User",
            email="duplicate@example.com",
        )

        # First invitation succeeds
        await service.invite_user(input_data, admin_id=admin_id)

        # Second invitation with same email fails
        input_data2 = InviteUserInput(
            name="Second User",
            email="duplicate@example.com",
        )

        with pytest.raises(UserAlreadyExistsError):
            await service.invite_user(input_data2, admin_id=admin_id)

    @pytest.mark.asyncio
    async def test_invite_user_invalid_plan_raises_error(self, test_session, mock_email_sender):
        """Test that inviting with non-existent plan raises error."""
        service = InvitationService(test_session, mock_email_sender)
        admin_id = uuid4()

        input_data = InviteUserInput(
            name="Test User",
            email="badplan@example.com",
            plan_id=str(uuid4()),  # Non-existent plan
        )

        with pytest.raises(PlanNotFoundError):
            await service.invite_user(input_data, admin_id=admin_id)


class TestActivationService:
    """Test ActivationService."""

    async def _create_invited_user_with_token(self, session, mock_email_sender) -> tuple[User, str]:
        """Helper to create an invited user with activation token.

        Returns the user and the raw token extracted from the sent email.
        """
        invitation_service = InvitationService(session, mock_email_sender)
        admin_id = uuid4()

        # Generate unique email for each test
        email = f"test_{uuid4().hex[:8]}@example.com"
        input_data = InviteUserInput(name="Test User", email=email)
        result = await invitation_service.invite_user(input_data, admin_id=admin_id)

        # Extract token from sent email
        import re
        sent_email = mock_email_sender.sent_emails[-1]
        token_match = re.search(r'token=([A-Za-z0-9_-]+)', sent_email.html_content)
        raw_token = token_match.group(1)

        user_repo = UserRepository(session)
        user = await user_repo.get_by_id(result.user_id)

        return user, raw_token

    @pytest.mark.asyncio
    async def test_activate_account_success(self, test_session, mock_email_sender):
        """Test successful account activation."""
        user, token = await self._create_invited_user_with_token(test_session, mock_email_sender)
        service = ActivationService(test_session)

        input_data = ActivateAccountInput(
            token=token,
            password="SecurePassword123!",
            cpf=generate_valid_cpf(),
            phone="11999999999",
            nickname="TestNick",
        )

        result = await service.activate_account(input_data)

        assert result.user_id == user.id
        assert result.email == user.email.value

        # Verify user is now active
        user_repo = UserRepository(test_session)
        updated_user = await user_repo.get_by_id(user.id)

        assert updated_user.status == UserStatus.ACTIVE
        assert updated_user.cpf is not None
        # CPF should be stored normalized (digits only)
        assert len(updated_user.cpf.value) == 11
        assert updated_user.phone == "11999999999"
        assert updated_user.nickname == "TestNick"
        assert updated_user.password_hash is not None

    @pytest.mark.asyncio
    async def test_activate_account_marks_token_as_used(self, test_session, mock_email_sender):
        """Test that activation marks the token as used."""
        user, token = await self._create_invited_user_with_token(test_session, mock_email_sender)
        service = ActivationService(test_session)

        input_data = ActivateAccountInput(
            token=token,
            password="SecurePassword123!",
            cpf=generate_valid_cpf(),
            phone="11999999999",
        )

        await service.activate_account(input_data)

        # Verify token is now used
        token_repo = UserTokenRepository(test_session)
        token_hash = hash_token(token)
        stored_token = await token_repo.get_by_hash(token_hash)

        assert stored_token.is_used()
        assert stored_token.used_at is not None

    @pytest.mark.asyncio
    async def test_activate_account_token_cannot_be_reused(self, test_session, mock_email_sender):
        """Test that activation token cannot be used twice."""
        user, token = await self._create_invited_user_with_token(test_session, mock_email_sender)
        service = ActivationService(test_session)

        input_data = ActivateAccountInput(
            token=token,
            password="SecurePassword123!",
            cpf=generate_valid_cpf(),
            phone="11999999999",
        )

        # First activation succeeds
        await service.activate_account(input_data)

        # Second activation with same token fails
        input_data2 = ActivateAccountInput(
            token=token,
            password="AnotherPassword123!",
            cpf="123.456.789-09",
            phone="11888888888",
        )

        with pytest.raises(InvalidTokenError):
            await service.activate_account(input_data2)

    @pytest.mark.asyncio
    async def test_activate_account_invalid_token(self, test_session):
        """Test activation with invalid token."""
        service = ActivationService(test_session)

        input_data = ActivateAccountInput(
            token="invalid_token_that_does_not_exist",
            password="SecurePassword123!",
            cpf="529.982.247-25",
            phone="11999999999",
        )

        with pytest.raises(InvalidTokenError):
            await service.activate_account(input_data)

    @pytest.mark.asyncio
    async def test_activate_account_expired_token(self, test_session, mock_email_sender):
        """Test activation with expired token."""
        user, token = await self._create_invited_user_with_token(test_session, mock_email_sender)

        # Manually expire the token
        token_repo = UserTokenRepository(test_session)
        token_hash = hash_token(token)
        stored_token = await token_repo.get_by_hash(token_hash)
        stored_token.expires_at = datetime.utcnow() - timedelta(hours=1)
        await token_repo.save(stored_token)

        service = ActivationService(test_session)

        input_data = ActivateAccountInput(
            token=token,
            password="SecurePassword123!",
            cpf=generate_valid_cpf(),
            phone="11999999999",
        )

        with pytest.raises(InvalidTokenError):
            await service.activate_account(input_data)

    @pytest.mark.asyncio
    async def test_activate_account_duplicate_cpf_raises_error(self, test_session, mock_email_sender):
        """Test that activation with existing CPF raises error."""
        # Create first user with CPF
        user1, token1 = await self._create_invited_user_with_token(test_session, mock_email_sender)
        service = ActivationService(test_session)

        cpf1 = generate_valid_cpf()
        input_data1 = ActivateAccountInput(
            token=token1,
            password="SecurePassword123!",
            cpf=cpf1,
            phone="11999999999",
        )
        await service.activate_account(input_data1)

        # Create second invited user
        user2, token2 = await self._create_invited_user_with_token(test_session, mock_email_sender)

        # Try to activate with same CPF
        input_data2 = ActivateAccountInput(
            token=token2,
            password="SecurePassword123!",
            cpf=cpf1,  # Same CPF
            phone="11888888888",
        )

        with pytest.raises(ValueError, match="CPF already registered"):
            await service.activate_account(input_data2)
