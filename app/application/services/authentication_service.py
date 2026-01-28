"""Authentication service."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos.auth import LoginInput, LoginResult, RegisterUserInput
from app.domain.entities.audit_log import AuditAction, AuditLog
from app.domain.entities.user import User, UserRole
from app.domain.entities.wallet import Wallet
from app.domain.exceptions import AuthenticationError, UserNotFoundError
from app.domain.value_objects.cpf import CPF
from app.domain.value_objects.email import Email
from app.infrastructure.db.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.db.repositories.user_repository import UserRepository
from app.infrastructure.db.repositories.wallet_repository import WalletRepository
from app.infrastructure.security.jwt import create_access_token
from app.infrastructure.security.password import hash_password, verify_password


class AuthenticationService:
    """Service for authentication operations.

    Stateless service that orchestrates authentication-related use cases.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize service with database session."""
        self._session = session
        self._user_repo = UserRepository(session)
        self._wallet_repo = WalletRepository(session)
        self._audit_repo = AuditLogRepository(session)

    async def register_user(self, input_data: RegisterUserInput) -> User:
        """Register a new user.

        Args:
            input_data: Registration data

        Returns:
            Created User entity

        Raises:
            ValueError: If CPF or email already exists
        """
        # Validate and create value objects
        cpf = CPF(input_data.cpf)
        email = Email(input_data.email)

        # Check for existing user
        existing_by_cpf = await self._user_repo.get_by_cpf(cpf)
        if existing_by_cpf:
            raise ValueError("CPF already registered")

        existing_by_email = await self._user_repo.get_by_email(email)
        if existing_by_email:
            raise ValueError("Email already registered")

        # Create user
        password_hash = hash_password(input_data.password)
        print(password_hash)
        user = User.create(
            cpf=cpf,
            email=email,
            name=input_data.name,
            password_hash=password_hash,
            role=UserRole.CLIENT,
            phone=input_data.phone,
        )

        # Save user
        saved_user = await self._user_repo.save(user)

        # Create wallet for user
        wallet = Wallet.create(user_id=saved_user.id)
        await self._wallet_repo.save(wallet)

        # Create audit log
        audit = AuditLog.create(
            action=AuditAction.USER_CREATED,
            actor_id=saved_user.id,
            target_id=saved_user.id,
            target_type="user",
            details={"name": saved_user.name, "email": saved_user.email.value},
        )
        await self._audit_repo.save(audit)

        return saved_user
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

        # Invited users cannot authenticate (no password set)
        if user.is_invited() or user.password_hash is None:
            raise AuthenticationError("Invalid email or password")

        # Verify password
        if not verify_password(input_data.password, user.password_hash):
            raise AuthenticationError("Invalid email or password")

        # Check if user is active
        if not user.is_active():
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