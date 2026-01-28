"""Tests for email infrastructure."""

from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.email.email_sender import (
    EmailMessage,
    EmailRecipient,
    EmailSendResult,
)
from app.infrastructure.email.exceptions import (
    EmailInvalidApiKeyError,
    EmailSendFailedError,
    EmailServiceUnavailableError,
)
from app.infrastructure.email.sendgrid_client import SendGridClient


class TestEmailMessage:
    """Tests for EmailMessage dataclass."""

    def test_email_message_requires_content(self) -> None:
        """Test that at least one content type is required."""
        with pytest.raises(ValueError, match="Either html_content or plain_content"):
            EmailMessage(
                from_email="test@example.com",
                to=[EmailRecipient(email="recipient@example.com")],
                subject="Test",
            )

    def test_email_message_requires_recipients(self) -> None:
        """Test that at least one recipient is required."""
        with pytest.raises(ValueError, match="At least one recipient"):
            EmailMessage(
                from_email="test@example.com",
                to=[],
                subject="Test",
                html_content="<p>Hello</p>",
            )

    def test_email_message_with_html_only(self) -> None:
        """Test message with HTML content only."""
        message = EmailMessage(
            from_email="test@example.com",
            to=[EmailRecipient(email="recipient@example.com")],
            subject="Test",
            html_content="<p>Hello</p>",
        )
        assert message.html_content == "<p>Hello</p>"
        assert message.plain_content is None

    def test_email_message_with_plain_only(self) -> None:
        """Test message with plain text content only."""
        message = EmailMessage(
            from_email="test@example.com",
            to=[EmailRecipient(email="recipient@example.com")],
            subject="Test",
            plain_content="Hello",
        )
        assert message.plain_content == "Hello"
        assert message.html_content is None

    def test_email_message_with_both_contents(self) -> None:
        """Test message with both HTML and plain text."""
        message = EmailMessage(
            from_email="test@example.com",
            to=[EmailRecipient(email="recipient@example.com")],
            subject="Test",
            html_content="<p>Hello</p>",
            plain_content="Hello",
        )
        assert message.html_content == "<p>Hello</p>"
        assert message.plain_content == "Hello"

    def test_email_message_with_multiple_recipients(self) -> None:
        """Test message with multiple recipients."""
        recipients = [
            EmailRecipient(email="one@example.com", name="One"),
            EmailRecipient(email="two@example.com", name="Two"),
        ]
        message = EmailMessage(
            from_email="test@example.com",
            to=recipients,
            subject="Test",
            html_content="<p>Hello</p>",
        )
        assert len(message.to) == 2


class TestEmailRecipient:
    """Tests for EmailRecipient dataclass."""

    def test_recipient_with_email_only(self) -> None:
        """Test recipient with email only."""
        recipient = EmailRecipient(email="test@example.com")
        assert recipient.email == "test@example.com"
        assert recipient.name is None

    def test_recipient_with_name(self) -> None:
        """Test recipient with name."""
        recipient = EmailRecipient(email="test@example.com", name="Test User")
        assert recipient.email == "test@example.com"
        assert recipient.name == "Test User"


class TestEmailSendResult:
    """Tests for EmailSendResult dataclass."""

    def test_successful_result(self) -> None:
        """Test successful send result."""
        result = EmailSendResult(
            success=True,
            status_code=202,
            message_id="abc123",
        )
        assert result.success is True
        assert result.status_code == 202
        assert result.message_id == "abc123"

    def test_result_without_message_id(self) -> None:
        """Test result without message ID."""
        result = EmailSendResult(success=True, status_code=200)
        assert result.message_id is None


class TestSendGridClient:
    """Tests for SendGridClient."""

    @pytest.fixture
    def mock_settings(self) -> MagicMock:
        """Create mock settings."""
        mock = MagicMock()
        mock.sendgrid_api_key.get_secret_value.return_value = "test_api_key"
        mock.sendgrid_from_email = "noreply@blancofinancas.com.br"
        mock.sendgrid_from_name = "Blanco Finanças"
        return mock

    @pytest.fixture
    def client(self, mock_settings: MagicMock) -> SendGridClient:
        """Create client with mocked settings."""
        with patch(
            "app.infrastructure.email.sendgrid_client.settings",
            mock_settings,
        ):
            return SendGridClient(api_key="test_api_key")

    def test_build_mail_simple(self, client: SendGridClient) -> None:
        """Test building simple mail object."""
        message = EmailMessage(
            from_email="sender@example.com",
            to=[EmailRecipient(email="recipient@example.com")],
            subject="Test Subject",
            html_content="<p>Test Content</p>",
        )
        mail = client._build_mail(message)

        assert mail.subject.get() == "Test Subject"
        assert mail.from_email.email == "sender@example.com"

    def test_build_mail_with_names(self, client: SendGridClient) -> None:
        """Test building mail with display names."""
        message = EmailMessage(
            from_email="sender@example.com",
            from_name="Sender Name",
            to=[EmailRecipient(email="recipient@example.com", name="Recipient Name")],
            subject="Test Subject",
            html_content="<p>Test</p>",
        )
        mail = client._build_mail(message)

        assert mail.from_email.name == "Sender Name"

    def test_build_mail_with_reply_to(self, client: SendGridClient) -> None:
        """Test building mail with reply-to."""
        message = EmailMessage(
            from_email="sender@example.com",
            to=[EmailRecipient(email="recipient@example.com")],
            subject="Test",
            html_content="<p>Test</p>",
            reply_to="reply@example.com",
        )
        mail = client._build_mail(message)

        assert mail.reply_to.email == "reply@example.com"

    @pytest.mark.asyncio
    async def test_send_success(self, client: SendGridClient) -> None:
        """Test successful email send."""
        message = EmailMessage(
            from_email="sender@example.com",
            to=[EmailRecipient(email="recipient@example.com")],
            subject="Test",
            html_content="<p>Test</p>",
        )

        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.headers = {"X-Message-Id": "msg123"}

        with patch.object(client._client, "send", return_value=mock_response):
            result = await client.send(message)

        assert result.success is True
        assert result.status_code == 202
        assert result.message_id == "msg123"

    @pytest.mark.asyncio
    async def test_send_unauthorized(self, client: SendGridClient) -> None:
        """Test unauthorized API key error."""
        message = EmailMessage(
            from_email="sender@example.com",
            to=[EmailRecipient(email="recipient@example.com")],
            subject="Test",
            html_content="<p>Test</p>",
        )

        mock_response = MagicMock()
        mock_response.status_code = 401

        with (
            patch.object(client._client, "send", return_value=mock_response),
            pytest.raises(EmailInvalidApiKeyError),
        ):
            await client.send(message)

    @pytest.mark.asyncio
    async def test_send_forbidden(self, client: SendGridClient) -> None:
        """Test forbidden API key error."""
        message = EmailMessage(
            from_email="sender@example.com",
            to=[EmailRecipient(email="recipient@example.com")],
            subject="Test",
            html_content="<p>Test</p>",
        )

        mock_response = MagicMock()
        mock_response.status_code = 403

        with (
            patch.object(client._client, "send", return_value=mock_response),
            pytest.raises(EmailInvalidApiKeyError),
        ):
            await client.send(message)

    @pytest.mark.asyncio
    async def test_send_server_error(self, client: SendGridClient) -> None:
        """Test server error handling."""
        message = EmailMessage(
            from_email="sender@example.com",
            to=[EmailRecipient(email="recipient@example.com")],
            subject="Test",
            html_content="<p>Test</p>",
        )

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.body = b"Internal Server Error"

        with (
            patch.object(client._client, "send", return_value=mock_response),
            pytest.raises(EmailSendFailedError) as exc_info,
        ):
            await client.send(message)

        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_send_connection_error(self, client: SendGridClient) -> None:
        """Test connection error handling."""
        message = EmailMessage(
            from_email="sender@example.com",
            to=[EmailRecipient(email="recipient@example.com")],
            subject="Test",
            html_content="<p>Test</p>",
        )

        with (
            patch.object(
                client._client,
                "send",
                side_effect=Exception("Connection refused"),
            ),
            pytest.raises(EmailServiceUnavailableError),
        ):
            await client.send(message)

    @pytest.mark.asyncio
    async def test_send_transactional(
        self,
        client: SendGridClient,
        mock_settings: MagicMock,
    ) -> None:
        """Test transactional email sending."""
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.headers = {"X-Message-Id": "trans123"}

        with (
            patch(
                "app.infrastructure.email.sendgrid_client.settings",
                mock_settings,
            ),
            patch.object(client._client, "send", return_value=mock_response),
        ):
            result = await client.send_transactional(
                to_email="recipient@example.com",
                to_name="Recipient Name",
                subject="Welcome",
                html_content="<p>Welcome!</p>",
            )

        assert result.success is True
        assert result.status_code == 202

    @pytest.mark.asyncio
    async def test_send_with_no_headers(self, client: SendGridClient) -> None:
        """Test send when response has no headers."""
        message = EmailMessage(
            from_email="sender@example.com",
            to=[EmailRecipient(email="recipient@example.com")],
            subject="Test",
            html_content="<p>Test</p>",
        )

        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.headers = None

        with patch.object(client._client, "send", return_value=mock_response):
            result = await client.send(message)

        assert result.success is True
        assert result.message_id is None
