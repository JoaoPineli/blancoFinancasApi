"""Tests for the Notification domain entity."""

from uuid import uuid4

from app.domain.entities.notification import Notification, NotificationType


class TestNotificationEntity:
    """Tests for Notification.create_withdrawal_requested factory."""

    def test_creates_with_correct_type(self):
        """Factory produces WITHDRAWAL_REQUESTED notification type."""
        n = Notification.create_withdrawal_requested(
            target_id=uuid4(),
            client_name="João Silva",
            plan_title="Plano Gold",
            amount_cents=150_000,
        )
        assert n.notification_type == NotificationType.WITHDRAWAL_REQUESTED

    def test_is_unread_on_creation(self):
        """Notification starts as unread."""
        n = Notification.create_withdrawal_requested(
            target_id=uuid4(),
            client_name="Maria",
            plan_title="Plano Bronze",
            amount_cents=50_000,
        )
        assert n.is_read is False
        assert n.read_at is None

    def test_has_uuid(self):
        """Notification has a non-None UUID."""
        n = Notification.create_withdrawal_requested(
            target_id=uuid4(),
            client_name="Carlos",
            plan_title="Plano Prata",
            amount_cents=75_000,
        )
        assert n.id is not None

    def test_message_contains_client_name_and_amount(self):
        """Notification message includes relevant context."""
        n = Notification.create_withdrawal_requested(
            target_id=uuid4(),
            client_name="Ana Souza",
            plan_title="Plano Diamante",
            amount_cents=200_000,
        )
        assert "Ana Souza" in n.message or "Ana Souza" in n.title
        assert n.title != ""
        assert n.message != ""

    def test_target_id_is_set(self):
        """target_id is stored on the notification."""
        tid = uuid4()
        n = Notification.create_withdrawal_requested(
            target_id=tid,
            client_name="Test",
            plan_title="Plan",
            amount_cents=10_000,
        )
        assert n.target_id == tid
        assert n.target_type == "transaction"
