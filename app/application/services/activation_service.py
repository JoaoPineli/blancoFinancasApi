"""Activation service for completing user email confirmation."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos.registration import ActivateAccountInput, ActivateAccountResult
from app.application.services.registration_service import (
    ACTIVATION_TOKEN_EXPIRY_HOURS,
    build_activation_url,
    build_confirmation_email_html,
    build_confirmation_email_plain,
    generate_secure_token,
    hash_token,
)
from app.domain.entities.audit_log import AuditAction, AuditLog
from app.domain.entities.user import UserStatus
from app.domain.entities.user_token import TokenType, UserToken
from app.domain.exceptions import InvalidTokenError, UserNotFoundError
from app.infrastructure.db.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.db.repositories.user_repository import UserRepository
from app.infrastructure.db.repositories.user_token_repository import UserTokenRepository
from app.infrastructure.email.email_sender import EmailSender


class ActivationService:
    """Service for completing user email confirmation.

    Validates activation tokens and transitions user status
    from REGISTERED to ACTIVE. Also handles resending confirmation emails.
    """

    def __init__(self, session: AsyncSession, email_sender: EmailSender | None = None) -> None:
        """Initialize service with database session.

        Args:
            session: Database session for persistence.
            email_sender: Email sender (required for resend_confirmation).
        """
        self._session = session
        self._email_sender = email_sender
        self._user_repo = UserRepository(session)
        self._token_repo = UserTokenRepository(session)
        self._audit_repo = AuditLogRepository(session)

    async def activate_account(
        self,
        input_data: ActivateAccountInput,
    ) -> ActivateAccountResult:
        """Complete account activation by confirming email.

        Validates the activation token and transitions user status
        from REGISTERED to ACTIVE.

        Args:
            input_data: Activation data (token).

        Returns:
            ActivateAccountResult with user details.

        Raises:
            InvalidTokenError: If token is invalid, expired, or already used.
            UserNotFoundError: If associated user doesn't exist.
            ValueError: If user is not in REGISTERED status.

        Note:
            This endpoint intentionally does not reveal whether a token
            or user exists - all failures return a generic error.
        """
        # Hash the provided token and look it up
        token_hash_value = hash_token(input_data.token)
        token = await self._token_repo.get_by_hash(token_hash_value)

        # Validate token exists
        if not token:
            raise InvalidTokenError()

        # Validate token is valid (not expired, not used)
        if not token.is_valid():
            raise InvalidTokenError()

        # Get the associated user
        user = await self._user_repo.get_by_id(token.user_id)
        if not user:
            raise UserNotFoundError(str(token.user_id))

        # Validate user is in REGISTERED status
        if user.status != UserStatus.REGISTERED:
            raise InvalidTokenError()

        # Complete activation (domain method handles state transition)
        user.complete_activation()

        # Mark token as used
        token.mark_as_used()

        # Save both entities
        await self._user_repo.save(user)
        await self._token_repo.save(token)

        # Create audit log
        audit = AuditLog.create(
            action=AuditAction.USER_ACTIVATED,
            actor_id=user.id,
            target_id=user.id,
            target_type="user",
            details={
                "email": user.email.value,
                "name": user.name,
            },
        )
        await self._audit_repo.save(audit)

        return ActivateAccountResult(
            user_id=user.id,
            email=user.email.value,
            name=user.name,
        )

    async def resend_confirmation(self, user_id: UUID) -> None:
        """Resend the confirmation email to a registered user.

        Invalidates any existing activation tokens and generates a new one.

        Args:
            user_id: UUID of the user requesting resend.

        Raises:
            UserNotFoundError: If user doesn't exist.
            ValueError: If user is not in REGISTERED status.
            RuntimeError: If email sender is not configured.
        """
        if self._email_sender is None:
            raise RuntimeError("Email sender is required for resend_confirmation")

        user = await self._user_repo.get_by_id(user_id)
        if not user:
            raise UserNotFoundError(str(user_id))

        if user.status != UserStatus.REGISTERED:
            raise ValueError("Only registered users can resend confirmation")

        # Invalidate existing activation tokens by marking them as used
        existing_token = await self._token_repo.get_valid_activation_token_for_user(user_id)
        if existing_token:
            existing_token.mark_as_used()
            await self._token_repo.save(existing_token)

        # Generate new activation token
        raw_token = generate_secure_token()
        token_hash_value = hash_token(raw_token)

        token = UserToken.create(
            user_id=user_id,
            token_hash=token_hash_value,
            token_type=TokenType.ACTIVATION,
            expires_in_hours=ACTIVATION_TOKEN_EXPIRY_HOURS,
        )
        await self._token_repo.save(token)

        # Send confirmation email
        activation_url = build_activation_url(raw_token)
        html_content = build_confirmation_email_html(user.name, activation_url)
        plain_content = build_confirmation_email_plain(user.name, activation_url)

        await self._email_sender.send_transactional(
            to_email=user.email.value,
            to_name=user.name,
            subject="Confirme sua conta - Blanco Finanças",
            html_content=html_content,
            plain_content=plain_content,
        )
