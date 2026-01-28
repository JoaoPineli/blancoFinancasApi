"""Client repository implementation."""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.user import User, UserRole, UserStatus
from app.domain.value_objects.cpf import CPF
from app.domain.value_objects.email import Email
from app.infrastructure.db.models import UserModel


class UserRepository:
    """Repository for User entity persistence.

    Handles mapping between Domain Entity and ORM Model.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with database session."""
        self._session = session

    async def get_by_id(self, user_id: UUID) -> Optional[User]:
        """Get user by ID.

        Args:
            user_id: User UUID
        Returns:
            User entity or None
        """
        result = await self._session.execute(
            select(UserModel).where(UserModel.id == user_id)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_by_cpf(self, cpf: CPF) -> Optional[User]:
        """Get user by CPF.

        Args:
            cpf: User CPF value object
        Returns:
            User entity or None
        """
        result = await self._session.execute(
            select(UserModel).where(UserModel.cpf == cpf.value)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_by_email(self, email: Email) -> Optional[User]:
        """Get user by email.

        Args:
            email: User email value object
        Returns:
            User entity or None
        """
        result = await self._session.execute(
            select(UserModel).where(UserModel.email == email.value)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_all(
        self,
        status: Optional[UserStatus] = None,
        role: Optional[UserRole] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[User]:
        """Get all users with optional filtering.
        Args:
            status: Filter by status
            role: Filter by role
            limit: Maximum results
            offset: Pagination offset

        Returns:
            List of Client entities
        """
        query = select(UserModel)

        if status:
            query = query.where(UserModel.status == status.value)
        if role:
            query = query.where(UserModel.role == role.value)

        query = query.limit(limit).offset(offset)
        result = await self._session.execute(query)
        models = result.scalars().all()
        return [self._to_entity(model) for model in models]

    async def save(self, user: User) -> User:
        """Save client (create or update).

        Args:
            client: Client entity to save

        Returns:
            Saved User entity
        """
        model = self._to_model(user) 
        merged = await self._session.merge(model)
        await self._session.flush()
        return self._to_entity(merged)

    async def delete(self, user_id: UUID) -> bool:
        """Delete user by ID.

        Args:
            user_id: User UUID
        Returns:
            True if deleted, False if not found
        """
        result = await self._session.execute(
            select(UserModel).where(UserModel.id == user_id)
        )
        model = result.scalar_one_or_none()
        if model:
            await self._session.delete(model)
            return True
        return False

    def _to_entity(self, model: UserModel) -> User:
        """Map ORM model to domain entity."""
        return User(
            id=model.id,
            cpf=CPF(model.cpf) if model.cpf else None,
            email=Email(model.email),
            name=model.name,
            password_hash=model.password_hash,
            role=UserRole(model.role),
            status=UserStatus(model.status),
            phone=model.phone,
            nickname=model.nickname,
            plan_id=model.plan_id,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    def _to_model(self, entity: User) -> UserModel:
        """Map domain entity to ORM model."""
        return UserModel(
            id=entity.id,
            cpf=entity.cpf.value if entity.cpf else None,
            email=entity.email.value,
            name=entity.name,
            password_hash=entity.password_hash,
            role=entity.role.value,
            status=entity.status.value,
            phone=entity.phone,
            nickname=entity.nickname,
            plan_id=entity.plan_id,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )
