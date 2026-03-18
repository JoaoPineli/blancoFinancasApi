"""Registration service for self-service user registration."""

import hashlib
import secrets
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos.registration import RegisterUserInput, RegisterUserResult
from app.domain.entities.audit_log import AuditAction, AuditLog
from app.domain.entities.user import User, UserRole
from app.domain.entities.user_token import TokenType, UserToken
from app.domain.entities.wallet import Wallet
from app.domain.exceptions import UserAlreadyExistsError
from app.domain.value_objects.cpf import CPF
from app.domain.value_objects.email import Email
from app.infrastructure.config import settings
from app.infrastructure.db.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.db.repositories.user_repository import UserRepository
from app.infrastructure.db.repositories.user_token_repository import UserTokenRepository
from app.infrastructure.db.repositories.wallet_repository import WalletRepository
from app.infrastructure.email.email_sender import EmailSender
from app.infrastructure.security.password import hash_password


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


def build_confirmation_email_html(name: str, activation_url: str) -> str:
    """Build the HTML content for the registration confirmation email.

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
        <title>Confirme sua conta - Blanco Finanças</title>
    </head>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            <h1 style="color: #2c5aa0;">Bem-vindo(a) a Blanco Finanças!</h1>
            <p>Olá {name},</p>
            <p>Obrigado por se registrar na Blanco Finanças.</p>
            <p>Clique no botão abaixo para confirmar seu email e ativar sua conta:</p>
            <p style="text-align: center; margin: 30px 0;">
                <a href="{activation_url}"
                   style="background-color: #2c5aa0; color: white; padding: 12px 30px;
                          text-decoration: none; border-radius: 5px; display: inline-block;">
                    Confirmar Minha Conta
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
                Se você não criou esta conta, ignore este email.
            </p>
        </div>
    </body>
    </html>
    """


def build_confirmation_email_plain(name: str, activation_url: str) -> str:
    """Build the plain text content for the registration confirmation email.

    Args:
        name: The user's name.
        activation_url: The activation URL.

    Returns:
        Plain text email content.
    """
    return f"""Bem-vindo(a) a Blanco Finanças!

Olá {name},

Obrigado por se registrar na Blanco Finanças.

Acesse o link abaixo para confirmar seu email e ativar sua conta:

{activation_url}

Este link é válido por 48 horas.

Se você não criou esta conta, ignore este email.

---
Blanco Finanças
"""


class RegistrationService:
    """Service for self-service user registration.

    Creates users with REGISTERED status, generates activation tokens,
    and sends confirmation emails. The entire operation is transactional:
    if email sending fails, no user or token is persisted.
    """

    def __init__(self, session: AsyncSession, email_sender: EmailSender) -> None:
        """Initialize service with database session and email sender.

        Args:
            session: Database session for persistence.
            email_sender: Email sender abstraction for sending confirmation emails.
        """
        self._session = session
        self._email_sender = email_sender
        self._user_repo = UserRepository(session)
        self._token_repo = UserTokenRepository(session)
        self._wallet_repo = WalletRepository(session)
        self._audit_repo = AuditLogRepository(session)

    async def register_user(
        self,
        input_data: RegisterUserInput,
    ) -> RegisterUserResult:
        """Register a new user (self-service).

        Creates a user with REGISTERED status and generates an activation token.
        The user can authenticate but cannot access protected resources
        until they confirm their email.

        Args:
            input_data: Registration data (name, email, password, cpf, phone, nickname).

        Returns:
            RegisterUserResult with user details.

        Raises:
            UserAlreadyExistsError: If email or CPF already exists.
        """
        # Validate email and CPF format
        email = Email(input_data.email)
        cpf = CPF(input_data.cpf)

        # Check if user already exists
        existing_by_email = await self._user_repo.get_by_email(email)
        if existing_by_email:
            raise UserAlreadyExistsError("Email already registered")

        existing_by_cpf = await self._user_repo.get_by_cpf(cpf)
        if existing_by_cpf:
            raise UserAlreadyExistsError("CPF already registered")

        # Hash password
        password_hash_value = hash_password(input_data.password)

        # Create registered user (all fields set, REGISTERED status)
        user = User.create_registered(
            cpf=cpf,
            email=email,
            name=input_data.name,
            password_hash=password_hash_value,
            phone=input_data.phone,
            nickname=input_data.nickname,
            role=UserRole.CLIENT,
        )

        # Save user
        saved_user = await self._user_repo.save(user)

        # Create wallet for user
        wallet = Wallet.create(user_id=saved_user.id)
        await self._wallet_repo.save(wallet)

        # Generate activation token
        raw_token = generate_secure_token()
        token_hash_value = hash_token(raw_token)

        # Create and save token entity
        token = UserToken.create(
            user_id=saved_user.id,
            token_hash=token_hash_value,
            token_type=TokenType.ACTIVATION,
            expires_in_hours=ACTIVATION_TOKEN_EXPIRY_HOURS,
        )
        await self._token_repo.save(token)

        # Create audit log
        audit = AuditLog.create(
            action=AuditAction.USER_REGISTERED,
            actor_id=saved_user.id,
            target_id=saved_user.id,
            target_type="user",
            details={
                "email": saved_user.email.value,
                "name": saved_user.name,
            },
        )
        await self._audit_repo.save(audit)

        # Send confirmation email with activation token
        # If email fails, the entire transaction will be rolled back
        activation_url = build_activation_url(raw_token)
        html_content = build_confirmation_email_html(saved_user.name, activation_url)
        plain_content = build_confirmation_email_plain(saved_user.name, activation_url)

        await self._email_sender.send_transactional(
            to_email=saved_user.email.value,
            to_name=saved_user.name,
            subject="Confirme sua conta - Blanco Finanças",
            html_content=html_content,
            plain_content=plain_content,
        )

        return RegisterUserResult(
            user_id=saved_user.id,
            email=saved_user.email.value,
            name=saved_user.name,
        )
