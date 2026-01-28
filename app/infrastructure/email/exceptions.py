"""Email infrastructure exceptions."""


class EmailError(Exception):
    """Base exception for email errors."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class EmailServiceUnavailableError(EmailError):
    """Raised when email service is unavailable."""

    def __init__(self, message: str = "Email service is unavailable") -> None:
        super().__init__(message)


class EmailInvalidApiKeyError(EmailError):
    """Raised when the API key is invalid."""

    def __init__(self, message: str = "Invalid API key") -> None:
        super().__init__(message)


class EmailSendFailedError(EmailError):
    """Raised when email sending fails."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(message)


class EmailInvalidRecipientError(EmailError):
    """Raised when recipient email is invalid."""

    def __init__(self, email: str) -> None:
        super().__init__(f"Invalid recipient email: {email}")
