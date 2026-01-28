"""UserToken repository implementation."""

from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.user_token import TokenType, UserToken
from app.infrastructure.db.models import UserTokenModel


class UserTokenRepository:
    """Repository for UserToken entity persistence.

    Handles mapping between Domain Entity and ORM Model.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with database session."""
        self._session = session

    async def get_by_id(self, token_id: UUID) -> Optional[UserToken]:
        """Get token by ID.

        Args:
            token_id: Token UUID

        Returns:
            UserToken entity or None
        """
        result = await self._session.execute(
            select(UserTokenModel).where(UserTokenModel.id == token_id)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_by_hash(self, token_hash: str) -> Optional[UserToken]:
        """Get token by its hash.

        Args:
            token_hash: Hash of the token

        Returns:
            UserToken entity or None
        """
        result = await self._session.execute(
            select(UserTokenModel).where(UserTokenModel.token_hash == token_hash)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_valid_activation_token_for_user(
        self, user_id: UUID
    ) -> Optional[UserToken]:
        """Get a valid (unused, not expired) activation token for a user.

        Args:
            user_id: User UUID

        Returns:
            UserToken entity or None
        """
        from datetime import datetime

        result = await self._session.execute(
            select(UserTokenModel)
            .where(UserTokenModel.user_id == user_id)
            .where(UserTokenModel.token_type == TokenType.ACTIVATION.value)
            .where(UserTokenModel.used_at.is_(None))
            .where(UserTokenModel.expires_at > datetime.utcnow())
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def save(self, token: UserToken) -> UserToken:
        """Save token (create or update).

        Args:
            token: UserToken entity to save

        Returns:
            Saved UserToken entity
        """
        model = self._to_model(token)
        merged = await self._session.merge(model)
        await self._session.flush()
        return self._to_entity(merged)

    async def delete(self, token_id: UUID) -> bool:
        """Delete token by ID.

        Args:
            token_id: Token UUID

        Returns:
            True if deleted, False if not found
        """
        result = await self._session.execute(
            select(UserTokenModel).where(UserTokenModel.id == token_id)
        )
        model = result.scalar_one_or_none()
        if model:
            await self._session.delete(model)
            return True
        return False

    def _to_entity(self, model: UserTokenModel) -> UserToken:
        """Map ORM model to domain entity."""
        return UserToken(
            id=model.id,
            user_id=model.user_id,
            token_hash=model.token_hash,
            token_type=TokenType(model.token_type),
            expires_at=model.expires_at,
            used_at=model.used_at,
            created_at=model.created_at,
        )

    def _to_model(self, entity: UserToken) -> UserTokenModel:
        """Map domain entity to ORM model."""
        return UserTokenModel(
            id=entity.id,
            user_id=entity.user_id,
            token_hash=entity.token_hash,
            token_type=entity.token_type.value,
            expires_at=entity.expires_at,
            used_at=entity.used_at,
            created_at=entity.created_at,
        )
