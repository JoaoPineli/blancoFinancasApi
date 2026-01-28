"""JWT token handling using python-jose."""

from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from uuid import UUID

from jose import JWTError, jwt

from app.domain.entities.user import UserRole
from app.domain.exceptions import AuthenticationError
from app.infrastructure.config import settings


def create_access_token(
    subject: UUID,
    role: UserRole,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a JWT access token.

    Args:
        subject: User ID (UUID)
        role: User role
        expires_delta: Optional custom expiration time

    Returns:
        Encoded JWT token
    """
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes)

    to_encode: Dict[str, Any] = {
        "sub": str(subject),
        "role": role.value,
        "exp": expire,
        "iat": datetime.utcnow(),
    }
    encoded_jwt = jwt.encode(
        to_encode,
        settings.secret_key.get_secret_value(),
        algorithm=settings.algorithm,
    )
    return encoded_jwt


def decode_access_token(token: str) -> Dict[str, Any]:
    """Decode and validate a JWT access token.

    Args:
        token: JWT token string

    Returns:
        Decoded token payload

    Raises:
        AuthenticationError: If token is invalid or expired
    """
    try:
        payload = jwt.decode(
            token,
            settings.secret_key.get_secret_value(),
            algorithms=[settings.algorithm],
        )
        return payload
    except JWTError as e:
        raise AuthenticationError(f"Invalid token: {str(e)}")


def get_token_subject(token: str) -> UUID:
    """Extract subject (user ID) from token.

    Args:
        token: JWT token string

    Returns:
        User UUID from token

    Raises:
        AuthenticationError: If token is invalid
    """
    payload = decode_access_token(token)
    subject = payload.get("sub")
    if not subject:
        raise AuthenticationError("Token missing subject")
    return UUID(subject)


def get_token_role(token: str) -> UserRole:
    """Extract role from token.

    Args:
        token: JWT token string

    Returns:
        User role from token

    Raises:
        AuthenticationError: If token is invalid
    """
    payload = decode_access_token(token)
    role = payload.get("role")
    if not role:
        raise AuthenticationError("Token missing role")
    return UserRole(role)
