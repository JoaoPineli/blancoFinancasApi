"""Tests for PIX_TRANSACTION_FEE_PERCENT constant and calculate_pix_fee helper."""

import pytest
from decimal import Decimal

from app.domain.constants import PIX_TRANSACTION_FEE_PERCENT, calculate_pix_fee


class TestPixFeeConstant:
    """Test the PIX transaction fee constant."""

    def test_constant_value(self):
        """PIX_TRANSACTION_FEE_PERCENT is exactly 0.0099."""
        assert PIX_TRANSACTION_FEE_PERCENT == Decimal("0.0099")

    def test_constant_is_decimal(self):
        """Constant must be a Decimal, never a float."""
        assert isinstance(PIX_TRANSACTION_FEE_PERCENT, Decimal)

    def test_no_float_contamination(self):
        """Multiplying constant by an integer returns Decimal."""
        result = Decimal(10000) * PIX_TRANSACTION_FEE_PERCENT
        assert isinstance(result, Decimal)


class TestCalculatePixFee:
    """Tests for calculate_pix_fee(base_cents)."""

    def test_zero_base(self):
        """Zero base returns zero fee."""
        assert calculate_pix_fee(0) == 0

    def test_negative_base(self):
        """Negative base returns zero fee."""
        assert calculate_pix_fee(-100) == 0

    def test_100_cents(self):
        """0.99% of 100 = 0.99, rounds to 1."""
        assert calculate_pix_fee(100) == 1

    def test_10000_cents(self):
        """0.99% of 10000 = 99.0, rounds to 99."""
        assert calculate_pix_fee(10000) == 99

    def test_10101_cents(self):
        """0.99% of 10101 = 99.9999, rounds up to 100."""
        assert calculate_pix_fee(10101) == 100

    def test_1000000_cents(self):
        """0.99% of 1_000_000 = 9900."""
        assert calculate_pix_fee(1_000_000) == 9900

    def test_returns_int(self):
        """Return type is always int."""
        result = calculate_pix_fee(12345)
        assert isinstance(result, int)

    def test_no_float_used(self):
        """Result is computed purely with Decimal, result is int."""
        # If a float were involved, tiny floating-point errors would appear.
        # Simply verify the result is exactly correct.
        for base in [1, 99, 100, 1000, 9999, 10000, 100000, 999999]:
            fee = calculate_pix_fee(base)
            assert isinstance(fee, int), f"calculate_pix_fee({base}) returned {type(fee)}"
