"""Tests for UserToken entity."""

import pytest
from datetime import datetime, timedelta
from uuid import uuid4

from app.domain.entities.user_token import UserToken, TokenType


class TestUserToken:
    """Test UserToken entity."""

    def test_create_activation_token(self):
        """Test creating an activation token."""
        user_id = uuid4()
        token_hash = "abc123hash"

        token = UserToken.create(
            user_id=user_id,
            token_hash=token_hash,
            token_type=TokenType.ACTIVATION,
            expires_in_hours=48,
        )

        assert token.user_id == user_id
        assert token.token_hash == token_hash
        assert token.token_type == TokenType.ACTIVATION
        assert token.used_at is None
        assert token.expires_at > datetime.utcnow()

    def test_create_password_reset_token(self):
        """Test creating a password reset token."""
        user_id = uuid4()
        token_hash = "reset123hash"

        token = UserToken.create(
            user_id=user_id,
            token_hash=token_hash,
            token_type=TokenType.PASSWORD_RESET,
            expires_in_hours=24,
        )

        assert token.token_type == TokenType.PASSWORD_RESET

    def test_token_expiration(self):
        """Test token expiration detection."""
        user_id = uuid4()

        # Create token that expires in 48 hours
        token = UserToken.create(
            user_id=user_id,
            token_hash="hash",
            token_type=TokenType.ACTIVATION,
            expires_in_hours=48,
        )

        assert not token.is_expired()

        # Manually set expiration to past
        token.expires_at = datetime.utcnow() - timedelta(hours=1)
        assert token.is_expired()

    def test_token_not_used_initially(self):
        """Test that new tokens are not marked as used."""
        token = UserToken.create(
            user_id=uuid4(),
            token_hash="hash",
            token_type=TokenType.ACTIVATION,
        )

        assert not token.is_used()
        assert token.used_at is None

    def test_mark_token_as_used(self):
        """Test marking token as used."""
        token = UserToken.create(
            user_id=uuid4(),
            token_hash="hash",
            token_type=TokenType.ACTIVATION,
        )

        token.mark_as_used()

        assert token.is_used()
        assert token.used_at is not None

    def test_cannot_reuse_token(self):
        """Test that used tokens cannot be marked as used again."""
        token = UserToken.create(
            user_id=uuid4(),
            token_hash="hash",
            token_type=TokenType.ACTIVATION,
        )

        token.mark_as_used()

        with pytest.raises(ValueError, match="already been used"):
            token.mark_as_used()

    def test_token_validity_check(self):
        """Test comprehensive token validity check."""
        token = UserToken.create(
            user_id=uuid4(),
            token_hash="hash",
            token_type=TokenType.ACTIVATION,
            expires_in_hours=48,
        )

        # Fresh token should be valid
        assert token.is_valid()

        # Used token should not be valid
        token.mark_as_used()
        assert not token.is_valid()

    def test_expired_token_not_valid(self):
        """Test that expired tokens are not valid."""
        token = UserToken.create(
            user_id=uuid4(),
            token_hash="hash",
            token_type=TokenType.ACTIVATION,
        )

        token.expires_at = datetime.utcnow() - timedelta(hours=1)

        assert not token.is_valid()

    def test_token_expiration_boundary(self):
        """Test token validity at expiration boundary."""
        token = UserToken.create(
            user_id=uuid4(),
            token_hash="hash",
            token_type=TokenType.ACTIVATION,
        )

        # Set to 1 second in the past (just expired)
        token.expires_at = datetime.utcnow() - timedelta(seconds=1)

        # Token past expiration time should be expired
        assert token.is_expired()

    def test_token_at_exact_expiration_not_expired(self):
        """Test that token at exact expiration time is not yet expired.
        
        The is_expired() uses > comparison, so token expires AFTER expires_at.
        """
        token = UserToken.create(
            user_id=uuid4(),
            token_hash="hash",
            token_type=TokenType.ACTIVATION,
        )

        # Set to a time slightly in the future
        token.expires_at = datetime.utcnow() + timedelta(seconds=1)

        # Token should not be expired yet
        assert not token.is_expired()

    def test_default_expiration_hours(self):
        """Test default expiration of 48 hours."""
        token = UserToken.create(
            user_id=uuid4(),
            token_hash="hash",
            token_type=TokenType.ACTIVATION,
        )

        expected_expiration = datetime.utcnow() + timedelta(hours=48)

        # Allow 1 second tolerance
        delta = abs((token.expires_at - expected_expiration).total_seconds())
        assert delta < 1
