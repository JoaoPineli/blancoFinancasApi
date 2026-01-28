"""Activation service for completing user account setup."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos.invitation import ActivateAccountInput, ActivateAccountResult
from app.application.services.invitation_service import hash_token
from app.domain.entities.audit_log import AuditAction, AuditLog
from app.domain.entities.user import UserStatus
from app.domain.exceptions import InvalidTokenError, UserNotFoundError
from app.domain.value_objects.cpf import CPF
from app.infrastructure.db.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.db.repositories.user_repository import UserRepository
from app.infrastructure.db.repositories.user_token_repository import UserTokenRepository
from app.infrastructure.security.password import hash_password


class ActivationService:
    """Service for completing user account activation.

    Validates activation tokens and sets user credentials.
    All operations occur in a single transaction.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize service with database session."""
        self._session = session
        self._user_repo = UserRepository(session)
        self._token_repo = UserTokenRepository(session)
        self._audit_repo = AuditLogRepository(session)

    async def activate_account(
        self,
        input_data: ActivateAccountInput,
    ) -> ActivateAccountResult:
        """Complete account activation for an invited user.

        Validates the activation token and sets the user's password,
        CPF, phone, and optionally nickname. Transitions user status
        from INVITED to ACTIVE.

        Args:
            input_data: Activation data (token, password, CPF, phone, nickname).

        Returns:
            ActivateAccountResult with user details.

        Raises:
            InvalidTokenError: If token is invalid, expired, or already used.
            UserNotFoundError: If associated user doesn't exist.
            ValueError: If user is not in INVITED status or CPF already exists.

        Note:
            This endpoint intentionally does not reveal whether a token
            or user exists - all failures return a generic error.
        """
        # Hash the provided token and look it up
        token_hash = hash_token(input_data.token)
        token = await self._token_repo.get_by_hash(token_hash)

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

        # Validate user is in INVITED status
        if user.status != UserStatus.INVITED:
            raise InvalidTokenError()

        # Validate and create CPF
        cpf = CPF(input_data.cpf)

        # Check if CPF already exists for another user
        existing_user = await self._user_repo.get_by_cpf(cpf)
        if existing_user and existing_user.id != user.id:
            raise ValueError("CPF already registered")

        # Hash the password
        password_hash = hash_password(input_data.password)

        # Complete activation (domain method handles state transition)
        user.complete_activation(
            cpf=cpf,
            password_hash=password_hash,
            phone=input_data.phone,
            nickname=input_data.nickname,
        )

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
