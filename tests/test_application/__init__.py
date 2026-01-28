"""Tests for invitation service token generation."""

import pytest
import hashlib

from app.application.services.invitation_service import (
    generate_secure_token,
    hash_token,
)


class TestTokenGeneration:
    """Test token generation utilities."""

    def test_generate_secure_token_length(self):
        """Test that generated tokens have appropriate length."""
        token = generate_secure_token()
        
        # URL-safe base64 of 32 bytes should be ~43 characters
        assert len(token) >= 40
        assert len(token) <= 50

    def test_generate_secure_token_uniqueness(self):
        """Test that generated tokens are unique."""
        tokens = [generate_secure_token() for _ in range(100)]
        
        # All tokens should be unique
        assert len(set(tokens)) == 100

    def test_generate_secure_token_is_url_safe(self):
        """Test that tokens are URL-safe."""
        for _ in range(10):
            token = generate_secure_token()
            
            # Should not contain URL-unsafe characters
            assert '+' not in token
            assert '/' not in token
            
            # Should only contain alphanumeric, dash, underscore
            for char in token:
                assert char.isalnum() or char in '-_'

    def test_hash_token_produces_hex_string(self):
        """Test that hash_token produces a valid hex string."""
        token = "test_token_123"
        hashed = hash_token(token)
        
        # SHA-256 produces 64 hex characters
        assert len(hashed) == 64
        
        # All characters should be valid hex
        int(hashed, 16)  # Should not raise

    def test_hash_token_is_deterministic(self):
        """Test that the same token always produces the same hash."""
        token = "test_token_123"
        
        hash1 = hash_token(token)
        hash2 = hash_token(token)
        
        assert hash1 == hash2

    def test_hash_token_different_inputs_different_outputs(self):
        """Test that different tokens produce different hashes."""
        token1 = "token_one"
        token2 = "token_two"
        
        hash1 = hash_token(token1)
        hash2 = hash_token(token2)
        
        assert hash1 != hash2

    def test_hash_token_uses_sha256(self):
        """Test that hash_token uses SHA-256."""
        token = "test_token"
        
        expected = hashlib.sha256(token.encode("utf-8")).hexdigest()
        actual = hash_token(token)
        
        assert actual == expected

    def test_cannot_reverse_hash_to_token(self):
        """Verify that hashing is one-way (conceptual test)."""
        token = generate_secure_token()
        hashed = hash_token(token)
        
        # The hash should not contain the original token
        assert token not in hashed
        # The hash should be fixed length regardless of input
        assert len(hashed) == 64
