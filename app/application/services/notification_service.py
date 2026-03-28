"""Notification service for admin read-side operations."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos.notification import NotificationDTO, NotificationListResult
from app.domain.exceptions import NotificationNotFoundError
from app.infrastructure.db.repositories.notification_repository import NotificationRepository


class NotificationService:
    """Service for admin notification read and mark operations.

    Creation of notifications lives in domain-specific services
    (e.g., InstallmentPaymentService) to stay atomic with the trigger.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._notification_repo = NotificationRepository(session)

    async def get_all(
        self,
        unread_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> NotificationListResult:
        """List notifications for the admin."""
        notifications = await self._notification_repo.get_all(
            unread_only=unread_only,
            limit=limit,
            offset=offset,
        )
        unread_count = await self._notification_repo.get_unread_count()
        return NotificationListResult(
            notifications=[self._to_dto(n) for n in notifications],
            total=len(notifications),
            unread_count=unread_count,
        )

    async def get_unread_count(self) -> int:
        """Return the number of unread notifications."""
        return await self._notification_repo.get_unread_count()

    async def mark_as_read(self, notification_id: UUID) -> NotificationDTO:
        """Mark a single notification as read."""
        notification = await self._notification_repo.mark_as_read(notification_id)
        if not notification:
            raise NotificationNotFoundError(str(notification_id))
        await self._session.commit()
        return self._to_dto(notification)

    async def mark_all_as_read(self) -> int:
        """Mark all notifications as read. Returns count updated."""
        count = await self._notification_repo.mark_all_as_read()
        await self._session.commit()
        return count

    def _to_dto(self, notification) -> NotificationDTO:
        return NotificationDTO(
            id=notification.id,
            notification_type=notification.notification_type.value,
            title=notification.title,
            message=notification.message,
            is_read=notification.is_read,
            target_id=notification.target_id,
            target_type=notification.target_type,
            data=notification.data,
            created_at=notification.created_at,
            read_at=notification.read_at,
        )
