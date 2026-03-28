"""Notification repository implementation."""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.notification import Notification, NotificationType
from app.infrastructure.db.models import NotificationModel


class NotificationRepository:
    """Repository for Notification entity persistence."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with database session."""
        self._session = session

    async def save(self, notification: Notification) -> Notification:
        """Save a new notification."""
        model = self._to_model(notification)
        self._session.add(model)
        await self._session.flush()
        return self._to_entity(model)

    async def get_by_id(self, notification_id: UUID) -> Optional[Notification]:
        """Get a notification by ID."""
        result = await self._session.execute(
            select(NotificationModel).where(NotificationModel.id == notification_id)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_all(
        self,
        unread_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Notification]:
        """List notifications, optionally filtered to unread only."""
        query = select(NotificationModel)
        if unread_only:
            query = query.where(NotificationModel.is_read.is_(False))
        query = query.order_by(NotificationModel.created_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(query)
        return [self._to_entity(m) for m in result.scalars().all()]

    async def get_unread_count(self) -> int:
        """Return the count of unread notifications."""
        result = await self._session.execute(
            select(func.count(NotificationModel.id)).where(
                NotificationModel.is_read.is_(False)
            )
        )
        return result.scalar() or 0

    async def mark_as_read(self, notification_id: UUID) -> Optional[Notification]:
        """Mark a single notification as read. Returns None if not found."""
        model = (
            await self._session.execute(
                select(NotificationModel).where(NotificationModel.id == notification_id)
            )
        ).scalar_one_or_none()

        if not model:
            return None

        model.is_read = True
        model.read_at = datetime.utcnow()
        await self._session.flush()
        return self._to_entity(model)

    async def mark_all_as_read(self) -> int:
        """Mark all unread notifications as read. Returns count updated."""
        now = datetime.utcnow()
        result = await self._session.execute(
            update(NotificationModel)
            .where(NotificationModel.is_read.is_(False))
            .values(is_read=True, read_at=now)
        )
        await self._session.flush()
        return result.rowcount

    def _to_entity(self, model: NotificationModel) -> Notification:
        """Map ORM model to domain entity."""
        return Notification(
            id=model.id,
            notification_type=NotificationType(model.notification_type),
            title=model.title,
            message=model.message,
            is_read=model.is_read,
            target_id=model.target_id,
            target_type=model.target_type,
            data=model.data or {},
            created_at=model.created_at,
            read_at=model.read_at,
        )

    def _to_model(self, entity: Notification) -> NotificationModel:
        """Map domain entity to ORM model."""
        return NotificationModel(
            id=entity.id,
            notification_type=entity.notification_type.value,
            title=entity.title,
            message=entity.message,
            is_read=entity.is_read,
            target_id=entity.target_id,
            target_type=entity.target_type,
            data=entity.data,
            created_at=entity.created_at,
            read_at=entity.read_at,
        )
