"""Notification DTOs."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID


@dataclass
class NotificationDTO:
    """Notification data transfer object."""

    id: UUID
    notification_type: str
    title: str
    message: str
    is_read: bool
    target_id: Optional[UUID]
    target_type: Optional[str]
    data: Dict[str, Any]
    created_at: datetime
    read_at: Optional[datetime] = None


@dataclass
class NotificationListResult:
    """Result of listing notifications."""

    notifications: List[NotificationDTO]
    total: int
    unread_count: int
