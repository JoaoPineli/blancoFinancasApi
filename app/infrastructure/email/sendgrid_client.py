"""SendGrid email client implementation.

This module provides the SendGrid implementation of the EmailSender interface.
Uses the official sendgrid-python library with the Mail helper.

Reference: https://github.com/sendgrid/sendgrid-python
"""

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Email, Mail, To

from app.infrastructure.config import settings
from app.infrastructure.email.email_sender import (
    EmailMessage,
    EmailRecipient,
    EmailSender,
    EmailSendResult,
)
from app.infrastructure.email.exceptions import (
    EmailInvalidApiKeyError,
    EmailSendFailedError,
    EmailServiceUnavailableError,
)


class SendGridClient(EmailSender):
    """SendGrid email client.

    Implements EmailSender interface using SendGrid API.
    Uses the Mail helper for building email messages.
    """

    # HTTP status codes
    _SUCCESS_CODES = {200, 201, 202}
    _UNAUTHORIZED = 401
    _FORBIDDEN = 403

    def __init__(self, api_key: str | None = None) -> None:
        """Initialize SendGrid client.

        Args:
            api_key: SendGrid API key. If not provided, uses settings.
        """
        self._api_key = api_key or settings.sendgrid_api_key.get_secret_value()
        print(self._api_key)
        self._client = SendGridAPIClient(api_key=self._api_key)
        self._from_email = settings.sendgrid_from_email
        self._from_name = settings.sendgrid_from_name

    def _build_mail(self, message: EmailMessage) -> Mail:
        """Build Mail object from EmailMessage.

        Args:
            message: The email message to convert

        Returns:
            SendGrid Mail object
        """
        from_email = Email(
            email=message.from_email,
            name=message.from_name,
        )

        to_list = [
            To(email=recipient.email, name=recipient.name)
            for recipient in message.to
        ]

        mail = Mail(
            from_email=from_email,
            to_emails=to_list,
            subject=message.subject,
            html_content=message.html_content,
            plain_text_content=message.plain_content,
        )

        if message.reply_to:
            mail.reply_to = Email(email=message.reply_to)

        return mail

    async def send(self, message: EmailMessage) -> EmailSendResult:
        """Send an email message via SendGrid.

        Args:
            message: The email message to send

        Returns:
            EmailSendResult with send status

        Raises:
            EmailServiceUnavailableError: If SendGrid is unavailable
            EmailInvalidApiKeyError: If API key is invalid
            EmailSendFailedError: If sending fails
        """
        print(1)
        mail = self._build_mail(message)

        try:
            response = self._client.send(mail)
        except Exception as e:
            # Handle connection errors
            print(2)
            raise EmailServiceUnavailableError(
                f"Failed to connect to SendGrid: {e!s}"
            ) from e

        status_code = response.status_code

        # Check for authentication errors
        if status_code in (self._UNAUTHORIZED, self._FORBIDDEN):
            raise EmailInvalidApiKeyError()

        # Check for success
        if status_code in self._SUCCESS_CODES:
            # Extract message ID from headers if available
            message_id = None
            if response.headers:
                message_id = response.headers.get("X-Message-Id")

            return EmailSendResult(
                success=True,
                status_code=status_code,
                message_id=message_id,
            )

        # Handle other failures
        body = response.body.decode() if response.body else "Unknown error"
        raise EmailSendFailedError(
            message=f"SendGrid returned error: {body}",
            status_code=status_code,
        )

    async def send_transactional(
        self,
        to_email: str,
        to_name: str | None,
        subject: str,
        html_content: str,
        plain_content: str | None = None,
    ) -> EmailSendResult:
        """Send a transactional email (simplified interface).

        Uses configured from_email and from_name from settings.

        Args:
            to_email: Recipient email address
            to_name: Recipient name (optional)
            subject: Email subject
            html_content: HTML body content
            plain_content: Plain text body (optional)

        Returns:
            EmailSendResult with send status
        """
        message = EmailMessage(
            from_email=self._from_email,
            from_name=self._from_name,
            to=[EmailRecipient(email=to_email, name=to_name)],
            subject=subject,
            html_content=html_content,
            plain_content=plain_content,
        )

        return await self.send(message)
