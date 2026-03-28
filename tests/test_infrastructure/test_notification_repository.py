"""Tests for NotificationRepository."""

import pytest
from uuid import uuid4

from app.domain.entities.notification import Notification, NotificationType
from app.infrastructure.db.repositories.notification_repository import NotificationRepository


def _make_notification() -> Notification:
    return Notification.create_withdrawal_requested(
        target_id=uuid4(),
        client_name="Test User",
        plan_title="Plano Teste",
        amount_cents=100_000,
    )


class TestNotificationRepository:
    """Tests for NotificationRepository CRUD operations."""

    @pytest.mark.asyncio
    async def test_save_and_get_by_id(self, test_session):
        """Saved notification can be retrieved by ID."""
        repo = NotificationRepository(test_session)
        n = _make_notification()
        saved = await repo.save(n)
        await test_session.commit()

        fetched = await repo.get_by_id(saved.id)
        assert fetched is not None
        assert fetched.id == saved.id
        assert fetched.notification_type == NotificationType.WITHDRAWAL_REQUESTED
        assert fetched.is_read is False

    @pytest.mark.asyncio
    async def test_get_by_id_unknown_returns_none(self, test_session):
        """get_by_id returns None for unknown UUID."""
        repo = NotificationRepository(test_session)
        result = await repo.get_by_id(uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_get_all_returns_saved(self, test_session):
        """get_all returns all saved notifications."""
        repo = NotificationRepository(test_session)
        n1 = await repo.save(_make_notification())
        n2 = await repo.save(_make_notification())
        await test_session.commit()

        results = await repo.get_all(unread_only=False, limit=50, offset=0)
        ids = [r.id for r in results]
        assert n1.id in ids
        assert n2.id in ids

    @pytest.mark.asyncio
    async def test_get_all_unread_only_filters_read(self, test_session):
        """unread_only=True excludes read notifications."""
        repo = NotificationRepository(test_session)
        unread = await repo.save(_make_notification())
        read = await repo.save(_make_notification())
        await test_session.flush()

        # Mark one as read directly via mark_as_read
        await repo.mark_as_read(read.id)
        await test_session.commit()

        results = await repo.get_all(unread_only=True, limit=50, offset=0)
        ids = [r.id for r in results]
        assert unread.id in ids
        assert read.id not in ids

    @pytest.mark.asyncio
    async def test_get_unread_count(self, test_session):
        """get_unread_count returns correct count."""
        repo = NotificationRepository(test_session)
        # Save 2 unread notifications
        n1 = await repo.save(_make_notification())
        n2 = await repo.save(_make_notification())
        await test_session.flush()

        count_before = await repo.get_unread_count()

        # Mark one as read
        await repo.mark_as_read(n1.id)
        await test_session.flush()

        count_after = await repo.get_unread_count()
        assert count_after == count_before - 1

    @pytest.mark.asyncio
    async def test_mark_as_read_sets_is_read_and_read_at(self, test_session):
        """mark_as_read sets is_read=True and read_at timestamp."""
        repo = NotificationRepository(test_session)
        n = await repo.save(_make_notification())
        await test_session.flush()

        updated = await repo.mark_as_read(n.id)
        assert updated is not None
        assert updated.is_read is True
        assert updated.read_at is not None

    @pytest.mark.asyncio
    async def test_mark_as_read_unknown_returns_none(self, test_session):
        """mark_as_read returns None for unknown UUID."""
        repo = NotificationRepository(test_session)
        result = await repo.mark_as_read(uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_mark_all_as_read(self, test_session):
        """mark_all_as_read marks every unread notification."""
        repo = NotificationRepository(test_session)
        await repo.save(_make_notification())
        await repo.save(_make_notification())
        await test_session.flush()

        count = await repo.mark_all_as_read()
        assert count >= 2

        remaining_unread = await repo.get_unread_count()
        assert remaining_unread == 0
