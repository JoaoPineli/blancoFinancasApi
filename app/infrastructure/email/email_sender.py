"""Abstract email sender interface.

This module defines the common interface for email sending.
Implementations should not be called directly by Application or Domain layers;
they should use this interface through dependency injection.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class EmailRecipient:
    """Email recipient data."""

    email: str
    name: str | None = None


@dataclass(frozen=True)
class EmailMessage:
    """Email message to be sent.

    Attributes:
        from_email: Sender email address
        from_name: Sender display name (optional)
        to: List of recipients
        subject: Email subject line
        html_content: HTML body content (optional)
        plain_content: Plain text body content (optional)
        reply_to: Reply-to email address (optional)
    """

    from_email: str
    to: List[EmailRecipient]
    subject: str
    html_content: str | None = None
    plain_content: str | None = None
    from_name: str | None = None
    reply_to: str | None = None

    def __post_init__(self) -> None:
        """Validate email message."""
        if not self.html_content and not self.plain_content:
            raise ValueError("Either html_content or plain_content must be provided")
        if not self.to:
            raise ValueError("At least one recipient is required")


@dataclass(frozen=True)
class EmailSendResult:
    """Result of an email send operation.

    Attributes:
        success: Whether the email was sent successfully
        message_id: ID returned by the email service (if available)
        status_code: HTTP status code from the service
    """

    success: bool
    status_code: int
    message_id: str | None = None


class EmailSender(ABC):
    """Abstract interface for email sending.

    All email implementations must implement this interface.
    Application services should depend on this abstraction,
    not on concrete implementations.
    """

    @abstractmethod
    async def send(self, message: EmailMessage) -> EmailSendResult:
        """Send an email message.

        Args:
            message: The email message to send

        Returns:
            EmailSendResult with send status

        Raises:
            EmailServiceUnavailableError: If the service is unavailable
            EmailInvalidApiKeyError: If the API key is invalid
            EmailSendFailedError: If sending fails
        """
        ...

    @abstractmethod
    async def send_transactional(
        self,
        to_email: str,
        to_name: str | None,
        subject: str,
        html_content: str,
        plain_content: str | None = None,
    ) -> EmailSendResult:
        """Send a transactional email (simplified interface).

        Args:
            to_email: Recipient email address
            to_name: Recipient name (optional)
            subject: Email subject
            html_content: HTML body content
            plain_content: Plain text body (optional)

        Returns:
            EmailSendResult with send status
        """
        ...
