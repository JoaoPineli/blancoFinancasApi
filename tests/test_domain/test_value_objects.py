"""Tests for domain value objects."""

import pytest
from decimal import Decimal

from app.domain.value_objects.money import Money
from app.domain.value_objects.cpf import CPF
from app.domain.value_objects.email import Email
from app.domain.exceptions import InvalidCPFError, InvalidEmailError, InvalidMoneyError


class TestMoney:
    """Test Money value object."""

    def test_create_from_string(self):
        """Test creating Money from decimal string."""
        money = Money("100.50")
        assert money.cents == 10050
        assert money.amount == Decimal("100.50")

    def test_create_from_cents(self):
        """Test creating Money from cents."""
        money = Money.from_cents(10050)
        assert money.cents == 10050
        assert money.amount == Decimal("100.50")

    def test_zero(self):
        """Test creating zero Money."""
        money = Money.zero()
        assert money.cents == 0
        assert money.is_zero()

    def test_add(self):
        """Test adding Money values."""
        a = Money("100.00")
        b = Money("50.25")
        result = a.add(b)
        assert result.cents == 15025

    def test_subtract(self):
        """Test subtracting Money values."""
        a = Money("100.00")
        b = Money("25.50")
        result = a.subtract(b)
        assert result.cents == 7450

    def test_subtract_negative_raises_error(self):
        """Test that subtracting more than available raises error."""
        a = Money("50.00")
        b = Money("100.00")
        with pytest.raises(InvalidMoneyError):
            a.subtract(b)

    def test_multiply(self):
        """Test multiplying Money by factor."""
        money = Money("100.00")
        result = money.multiply(Decimal("1.5"))
        assert result.cents == 15000

    def test_percentage(self):
        """Test calculating percentage of Money."""
        money = Money("1000.00")
        result = money.percentage(Decimal("1.3"))  # 1.3%
        assert result.cents == 1300  # R$ 13.00

    def test_comparison(self):
        """Test Money comparison operations."""
        a = Money("100.00")
        b = Money("50.00")
        c = Money("100.00")

        assert a.is_greater_than(b)
        assert b.is_less_than(a)
        assert a == c
        assert a.is_greater_or_equal(c)

    def test_negative_amount_raises_error(self):
        """Test that negative amounts raise error."""
        with pytest.raises(InvalidMoneyError):
            Money("-100.00")

    def test_rounding(self):
        """Test that Money rounds correctly."""
        money = Money("100.005")
        assert money.cents == 10001  # Rounds up


class TestCPF:
    """Test CPF value object."""

    def test_valid_cpf(self):
        """Test valid CPF creation."""
        cpf = CPF("529.982.247-25")
        assert cpf.value == "52998224725"
        assert cpf.formatted == "529.982.247-25"

    def test_valid_cpf_without_formatting(self):
        """Test valid CPF without formatting."""
        cpf = CPF("52998224725")
        assert cpf.value == "52998224725"

    def test_invalid_cpf_raises_error(self):
        """Test invalid CPF raises error."""
        with pytest.raises(InvalidCPFError):
            CPF("111.111.111-11")  # All same digits

    def test_invalid_cpf_wrong_check_digit(self):
        """Test CPF with wrong check digit raises error."""
        with pytest.raises(InvalidCPFError):
            CPF("529.982.247-26")  # Wrong check digit

    def test_cpf_too_short_raises_error(self):
        """Test CPF too short raises error."""
        with pytest.raises(InvalidCPFError):
            CPF("1234567890")

    def test_cpf_equality(self):
        """Test CPF equality comparison."""
        cpf1 = CPF("529.982.247-25")
        cpf2 = CPF("52998224725")
        assert cpf1 == cpf2


class TestEmail:
    """Test Email value object."""

    def test_valid_email(self):
        """Test valid email creation."""
        email = Email("test@example.com")
        assert email.value == "test@example.com"

    def test_email_lowercase(self):
        """Test email is converted to lowercase."""
        email = Email("Test@EXAMPLE.COM")
        assert email.value == "test@example.com"

    def test_invalid_email_raises_error(self):
        """Test invalid email raises error."""
        with pytest.raises(InvalidEmailError):
            Email("invalid-email")

    def test_empty_email_raises_error(self):
        """Test empty email raises error."""
        with pytest.raises(InvalidEmailError):
            Email("")

    def test_email_equality(self):
        """Test email equality comparison."""
        email1 = Email("test@example.com")
        email2 = Email("TEST@example.com")
        assert email1 == email2
