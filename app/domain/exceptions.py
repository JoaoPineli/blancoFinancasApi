"""Domain exceptions - Business rule violations."""


class DomainError(Exception):
    """Base exception for domain errors."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class InvalidCPFError(DomainError):
    """Raised when CPF is invalid."""

    def __init__(self, cpf: str) -> None:
        super().__init__(f"Invalid CPF: {cpf}")


class InvalidEmailError(DomainError):
    """Raised when email is invalid."""

    def __init__(self, email: str) -> None:
        super().__init__(f"Invalid email: {email}")


class InvalidMoneyError(DomainError):
    """Raised when money value is invalid."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class InsufficientBalanceError(DomainError):
    """Raised when withdrawal exceeds available balance."""

    def __init__(self, requested: str, available: str) -> None:
        super().__init__(
            f"Insufficient balance. Requested: {requested}, Available: {available}"
        )


class InvalidWithdrawalError(DomainError):
    """Raised when withdrawal request is invalid."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class ContractNotFoundError(DomainError):
    """Raised when contract is not found."""

    def __init__(self, contract_id: str) -> None:
        super().__init__(f"Contract not found: {contract_id}")


class UserNotFoundError(DomainError):
    """Raised when user is not found."""

    def __init__(self, user_id: str) -> None:
        super().__init__(f"User not found: {user_id}")

class PlanNotFoundError(DomainError):
    """Raised when plan is not found."""

    def __init__(self, plan_id: str) -> None:
        super().__init__(f"Plan not found: {plan_id}")


class TransactionNotFoundError(DomainError):
    """Raised when transaction is not found."""

    def __init__(self, transaction_id: str) -> None:
        super().__init__(f"Transaction not found: {transaction_id}")


class InvalidTransactionStatusError(DomainError):
    """Raised when transaction status transition is invalid."""

    def __init__(self, current_status: str, target_status: str) -> None:
        super().__init__(
            f"Invalid status transition from {current_status} to {target_status}"
        )


class YieldCalculationError(DomainError):
    """Raised when yield calculation fails."""

    def __init__(self, message: str) -> None:
        super().__init__(f"Yield calculation error: {message}")


class AuthenticationError(DomainError):
    """Raised when authentication fails."""

    def __init__(self, message: str = "Authentication failed") -> None:
        super().__init__(message)


class AuthorizationError(DomainError):
    """Raised when authorization fails."""

    def __init__(self, message: str = "Access denied") -> None:
        super().__init__(message)


class InvalidTokenError(DomainError):
    """Raised when a token is invalid, expired, or already used."""

    def __init__(self, message: str = "Invalid or expired token") -> None:
        super().__init__(message)


class UserNotActivatedError(DomainError):
    """Raised when an operation requires an activated user."""

    def __init__(self, message: str = "User account not activated") -> None:
        super().__init__(message)


class SubscriptionNotFoundError(DomainError):
    """Raised when subscription is not found."""

    def __init__(self, subscription_id: str) -> None:
        super().__init__(f"Subscription not found: {subscription_id}")


class NoViablePlanError(DomainError):
    """Raised when no plan can satisfy the user's target amount."""

    def __init__(self, target_amount_cents: int) -> None:
        super().__init__(
            f"No viable plan found for target amount: {target_amount_cents} cents"
        )


class InvalidSubscriptionError(DomainError):
    """Raised when subscription parameters are invalid."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class UserAlreadyExistsError(DomainError):
    """Raised when attempting to create a user that already exists."""

    def __init__(self, message: str = "User already exists") -> None:
        super().__init__(message)


class PaymentNotFoundError(DomainError):
    """Raised when an installment payment is not found."""

    def __init__(self, payment_id: str) -> None:
        super().__init__(f"Payment not found: {payment_id}")


class InvalidPaymentError(DomainError):
    """Raised when a payment request is invalid."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class DuplicatePaymentError(DomainError):
    """Raised when a duplicate payment is detected."""

    def __init__(self, message: str = "Duplicate payment detected") -> None:
        super().__init__(message)


class NotificationNotFoundError(DomainError):
    """Raised when a notification is not found."""

    def __init__(self, notification_id: str) -> None:
        super().__init__(f"Notification not found: {notification_id}")
