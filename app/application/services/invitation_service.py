"""Invitation service for admin-initiated user invitations."""

import hashlib
import secrets
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos.invitation import InviteUserInput, InviteUserResult
from app.domain.entities.audit_log import AuditAction, AuditLog
from app.domain.entities.user import User, UserRole
from app.domain.entities.user_token import TokenType, UserToken
from app.domain.entities.wallet import Wallet
from app.domain.exceptions import UserAlreadyExistsError, PlanNotFoundError
from app.domain.value_objects.email import Email
from app.infrastructure.config import settings
from app.infrastructure.db.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.db.repositories.plan_repository import PlanRepository
from app.infrastructure.db.repositories.user_repository import UserRepository
from app.infrastructure.db.repositories.user_token_repository import UserTokenRepository
from app.infrastructure.db.repositories.wallet_repository import WalletRepository
from app.infrastructure.email.email_sender import EmailSender


# Token expiration in hours (48 hours = 2 days)
ACTIVATION_TOKEN_EXPIRY_HOURS = 48


def generate_secure_token() -> str:
    """Generate a cryptographically secure random token.

    Returns:
        A URL-safe base64-encoded token (32 bytes = 256 bits of entropy).
    """
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Hash a token for storage.

    Uses SHA-256 for token hashing. This is appropriate for tokens
    with high entropy (unlike passwords which need bcrypt).

    Args:
        token: The raw token to hash.

    Returns:
        The SHA-256 hash of the token as a hex string.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def build_activation_url(token: str) -> str:
    """Build the activation URL for the frontend.

    Args:
        token: The raw activation token.

    Returns:
        Full activation URL including the token.
    """
    frontend_url = settings.frontend_url.rstrip("/")
    return f"{frontend_url}/activate?token={token}"


def build_invitation_email_html(name: str, activation_url: str) -> str:
    """Build the HTML content for the invitation email.

    Args:
        name: The user's name.
        activation_url: The activation URL.

    Returns:
        HTML email content.
    """
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Ative sua conta - Blanco Finanças</title>
    </head>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            <h1 style="color: #2c5aa0;">Bem-vindo(a) a Blanco Finanças!</h1>
            <p>Olá {name},</p>
            <p>Você foi convidado(a) para ativar sua conta na Blanco Finanças.</p>
            <p>Clique no botão abaixo para ativar sua conta e definir sua senha:</p>
            <p style="text-align: center; margin: 30px 0;">
                <a href="{activation_url}"
                   style="background-color: #2c5aa0; color: white; padding: 12px 30px;
                          text-decoration: none; border-radius: 5px; display: inline-block;">
                    Ativar Minha Conta
                </a>
            </p>
            <p style="font-size: 14px; color: #666;">
                Se o botão não funcionar, copie e cole este link no seu navegador:
            </p>
            <p style="font-size: 12px; word-break: break-all; color: #888;">
                {activation_url}
            </p>
            <p style="font-size: 14px; color: #666; margin-top: 30px;">
                Este link é válido por 48 horas.
            </p>
            <hr style="border: none; border-top: 1px solid #eee; margin: 30px 0;">
            <p style="font-size: 12px; color: #999;">
                Se você não solicitou esta conta, ignore este email.
            </p>
        </div>
    </body>
    </html>
    """


def build_invitation_email_plain(name: str, activation_url: str) -> str:
    """Build the plain text content for the invitation email.

    Args:
        name: The user's name.
        activation_url: The activation URL.

    Returns:
        Plain text email content.
    """
    return f"""Bem-vindo(a) a Blanco Finanças!

Olá {name},

Você foi convidado(a) para ativar sua conta na Blanco Finanças.

Acesse o link abaixo para ativar sua conta e definir sua senha:

{activation_url}

Este link é válido por 48 horas.

Se você não solicitou esta conta, ignore este email.

---
Blanco Finanças
"""


class InvitationService:
    """Service for inviting users (admin-only operation).

    Creates users with INVITED status, generates activation tokens,
    and sends invitation emails. The entire operation is transactional:
    if email sending fails, no user or token is persisted.
    """

    def __init__(self, session: AsyncSession, email_sender: EmailSender) -> None:
        """Initialize service with database session and email sender.

        Args:
            session: Database session for persistence.
            email_sender: Email sender abstraction for sending invitation emails.
        """
        self._session = session
        self._email_sender = email_sender
        self._user_repo = UserRepository(session)
        self._token_repo = UserTokenRepository(session)
        self._plan_repo = PlanRepository(session)
        self._wallet_repo = WalletRepository(session)
        self._audit_repo = AuditLogRepository(session)

    async def invite_user(
        self,
        input_data: InviteUserInput,
        admin_id: UUID,
    ) -> InviteUserResult:
        """Invite a new user (admin-only).

        Creates a user with INVITED status and generates an activation token.
        The user cannot authenticate until they complete activation.

        Args:
            input_data: Invitation data (name, email, optional plan_id).
            admin_id: UUID of the admin performing the invitation.

        Returns:
            InviteUserResult with user details and raw activation token.

        Raises:
            UserAlreadyExistsError: If email already exists.
            PlanNotFoundError: If plan_id is provided but plan doesn't exist.
        """
        # Validate email format
        email = Email(input_data.email)

        # Check if user already exists
        existing_user = await self._user_repo.get_by_email(email)
        if existing_user:
            raise UserAlreadyExistsError("Email already registered")

        # Validate plan if provided
        plan_uuid: Optional[UUID] = None
        if input_data.plan_id:
            plan_uuid = UUID(input_data.plan_id)
            plan = await self._plan_repo.get_by_id(plan_uuid)
            if not plan:
                raise PlanNotFoundError(input_data.plan_id)

        # Create invited user (no password, no CPF)
        user = User.create_invited(
            email=email,
            name=input_data.name,
            role=UserRole.CLIENT,
            plan_id=plan_uuid,
        )

        # Save user
        saved_user = await self._user_repo.save(user)

        # Create wallet for user
        wallet = Wallet.create(user_id=saved_user.id)
        await self._wallet_repo.save(wallet)

        # Generate activation token
        raw_token = generate_secure_token()
        token_hash = hash_token(raw_token)

        # Create and save token entity
        token = UserToken.create(
            user_id=saved_user.id,
            token_hash=token_hash,
            token_type=TokenType.ACTIVATION,
            expires_in_hours=ACTIVATION_TOKEN_EXPIRY_HOURS,
        )
        await self._token_repo.save(token)

        # Create audit log
        audit = AuditLog.create(
            action=AuditAction.USER_INVITED,
            actor_id=admin_id,
            target_id=saved_user.id,
            target_type="user",
            details={
                "email": saved_user.email.value,
                "name": saved_user.name,
                "plan_id": str(plan_uuid) if plan_uuid else None,
            },
        )
        await self._audit_repo.save(audit)

        # Send invitation email with activation token
        # If email fails, the entire transaction will be rolled back
        activation_url = build_activation_url(raw_token)
        html_content = build_invitation_email_html(saved_user.name, activation_url)
        plain_content = build_invitation_email_plain(saved_user.name, activation_url)

        await self._email_sender.send_transactional(
            to_email=saved_user.email.value,
            to_name=saved_user.name,
            subject="Ative sua conta - Blanco Finanças",
            html_content=html_content,
            plain_content=plain_content,
        )
        print('5')

        return InviteUserResult(
            user_id=saved_user.id,
            email=saved_user.email.value,
            name=saved_user.name,
        )
