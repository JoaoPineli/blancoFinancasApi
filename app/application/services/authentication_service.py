"""Authentication service."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos.auth import LoginInput, LoginResult
from app.domain.entities.audit_log import AuditAction, AuditLog
from app.domain.entities.user import User, UserRole
from app.domain.exceptions import AuthenticationError, UserNotFoundError
from app.domain.value_objects.email import Email
from app.infrastructure.db.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.db.repositories.user_repository import UserRepository
from app.infrastructure.security.jwt import create_access_token
from app.infrastructure.security.password import verify_password


class AuthenticationService:
    """Service for authentication operations.

    Stateless service that orchestrates authentication-related use cases.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize service with database session."""
        self._session = session
        self._user_repo = UserRepository(session)
        self._audit_repo = AuditLogRepository(session)

    async def login(self, input_data: LoginInput) -> LoginResult:
        """Authenticate a user and return access token.

        Args:
            input_data: Login credentials

        Returns:
            LoginResult with access token

        Raises:
            AuthenticationError: If credentials are invalid
        """
        # Find user by email
        email = Email(input_data.email)
        user = await self._user_repo.get_by_email(email)

        if not user:
            raise AuthenticationError("Invalid email or password")

        # Users without password cannot authenticate
        if user.password_hash is None:
            raise AuthenticationError("Invalid email or password")

        # Verify password
        if not verify_password(input_data.password, user.password_hash):
            raise AuthenticationError("Invalid email or password")

        # Check if user is active or registered (registered users can log in
        # to access the email confirmation page)
        if not user.is_active() and not user.is_registered():
            raise AuthenticationError("Account is inactive")

        # Create access token
        access_token = create_access_token(
            subject=user.id,
            role=user.role,
        )

        # Create audit log for admin logins
        if user.is_admin():
            audit = AuditLog.create(
                action=AuditAction.ADMIN_LOGIN,
                actor_id=user.id,
            )
            await self._audit_repo.save(audit)

        return LoginResult(
            access_token=access_token,
            token_type="bearer",
            user_id=user.id,
            role=user.role,
            name=user.name,
        )

    async def get_current_user(self, user_id: str) -> User:
        """Get current authenticated user.
        Args:
            user_id: User UUID string

        Returns:
            User entity

        Raises:
            UserNotFoundError: If user not found
        """
        from uuid import UUID

        user = await self._user_repo.get_by_id(UUID(user_id))
        if not user:
            raise UserNotFoundError(user_id)
        return user