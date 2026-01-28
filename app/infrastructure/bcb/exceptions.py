"""BCB API exceptions."""


class BCBError(Exception):
    """Base exception for BCB API errors."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class BCBUnavailableError(BCBError):
    """Raised when BCB API is unavailable."""

    def __init__(self, message: str = "BCB API is unavailable") -> None:
        super().__init__(message)


class BCBInvalidSeriesError(BCBError):
    """Raised when an invalid series is requested."""

    def __init__(self, series_id: int) -> None:
        super().__init__(f"Invalid SGS series: {series_id}")


class BCBInvalidDateRangeError(BCBError):
    """Raised when an invalid date range is requested."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
