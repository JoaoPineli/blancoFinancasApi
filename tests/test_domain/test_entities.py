"""Tests for domain entities."""

import pytest
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from app.domain.entities.user import User, UserRole, UserStatus
from app.domain.entities.wallet import Wallet
from app.domain.entities.plan import Plan, PlanType, PlanStatus
from app.domain.entities.transaction import Transaction, TransactionType, InstallmentType
from app.domain.exceptions import InsufficientBalanceError, InvalidTransactionStatusError
from app.domain.value_objects.cpf import CPF
from app.domain.value_objects.email import Email
from app.domain.value_objects.money import Money


class TestUser:
    """Test User entity."""

    def test_create_user(self):
        """Test user creation."""
        user = User.create(
            cpf=CPF("529.982.247-25"),
            email=Email("test@example.com"),
            name="Test User",
            password_hash="hashed_password",
        )
        
        assert user.status == UserStatus.ACTIVE
        assert user.role == UserRole.CLIENT
        assert user.cpf.formatted == "529.982.247-25"

    def test_create_user_with_nickname_and_plan(self):
        """Test user creation with optional nickname and plan_id."""
        from uuid import uuid4
        plan_id = uuid4()
        
        user = User.create(
            cpf=CPF("529.982.247-25"),
            email=Email("test@example.com"),
            name="Test User",
            password_hash="hashed_password",
            nickname="TestNick",
            plan_id=plan_id,
        )
        
        assert user.nickname == "TestNick"
        assert user.plan_id == plan_id

    def test_create_invited_user(self):
        """Test creating an invited user (no password, no CPF)."""
        user = User.create_invited(
            email=Email("invited@example.com"),
            name="Invited User",
        )
        
        assert user.status == UserStatus.INVITED
        assert user.cpf is None
        assert user.password_hash is None
        assert user.phone is None
        assert user.role == UserRole.CLIENT

    def test_create_invited_user_with_plan(self):
        """Test creating an invited user with pre-assigned plan."""
        from uuid import uuid4
        plan_id = uuid4()
        
        user = User.create_invited(
            email=Email("invited@example.com"),
            name="Invited User",
            plan_id=plan_id,
        )
        
        assert user.plan_id == plan_id

    def test_is_invited(self):
        """Test is_invited helper method."""
        invited = User.create_invited(
            email=Email("invited@example.com"),
            name="Invited User",
        )
        active = User.create(
            cpf=CPF("529.982.247-25"),
            email=Email("active@example.com"),
            name="Active User",
            password_hash="hashed",
        )
        
        assert invited.is_invited()
        assert not active.is_invited()

    def test_complete_activation(self):
        """Test completing activation for invited user."""
        user = User.create_invited(
            email=Email("invited@example.com"),
            name="Invited User",
        )
        
        user.complete_activation(
            cpf=CPF("529.982.247-25"),
            password_hash="new_hashed_password",
            phone="11999999999",
            nickname="Nick",
        )
        
        assert user.status == UserStatus.ACTIVE
        assert user.cpf is not None
        assert user.cpf.formatted == "529.982.247-25"
        assert user.password_hash == "new_hashed_password"
        assert user.phone == "11999999999"
        assert user.nickname == "Nick"

    def test_complete_activation_without_nickname(self):
        """Test activation without providing nickname."""
        user = User.create_invited(
            email=Email("invited@example.com"),
            name="Invited User",
        )
        
        user.complete_activation(
            cpf=CPF("529.982.247-25"),
            password_hash="new_hashed_password",
            phone="11999999999",
        )
        
        assert user.status == UserStatus.ACTIVE
        assert user.nickname is None

    def test_complete_activation_only_for_invited_users(self):
        """Test that only invited users can complete activation."""
        user = User.create(
            cpf=CPF("529.982.247-25"),
            email=Email("active@example.com"),
            name="Active User",
            password_hash="hashed",
        )
        
        with pytest.raises(ValueError, match="Only invited users"):
            user.complete_activation(
                cpf=CPF("123.456.789-09"),
                password_hash="new_hash",
                phone="11999999999",
            )

    def test_user_activation(self):
        """Test user activation/deactivation."""
        user = User.create(
            cpf=CPF("529.982.247-25"),
            email=Email("test@example.com"),
            name="Test User",
            password_hash="hashed_password",
        )
        
        user.deactivate()
        assert user.status == UserStatus.INACTIVE
        assert not user.is_active()
        
        user.activate()
        assert user.status == UserStatus.ACTIVE
        assert user.is_active()
    def test_mark_as_defaulting(self):
        """Test marking user as defaulting."""
        user = User.create(
            cpf=CPF("529.982.247-25"),
            email=Email("test@example.com"),
            name="Test User",
            password_hash="hashed_password",
        )
        
        user.mark_as_defaulting()
        assert user.status == UserStatus.DEFAULTING


class TestWallet:
    """Test Wallet entity."""

    def test_create_wallet(self):
        """Test wallet creation with zero balance."""
        user_id = uuid4()
        wallet = Wallet.create(user_id)
        
        assert wallet.balance_cents == 0
        assert wallet.total_invested_cents == 0
        assert wallet.total_yield_cents == 0
        assert wallet.fundo_garantidor_cents == 0

    def test_credit_investment(self):
        """Test crediting investment to wallet."""
        wallet = Wallet.create(uuid4())
        amount = Money("1000.00")
        
        wallet.credit_investment(amount)
        
        assert wallet.balance_cents == 100000
        assert wallet.total_invested_cents == 100000

    def test_credit_yield(self):
        """Test crediting yield to wallet."""
        wallet = Wallet.create(uuid4())
        wallet.credit_investment(Money("1000.00"))
        
        yield_amount = Money("50.00")
        wallet.credit_yield(yield_amount)
        
        assert wallet.balance_cents == 105000
        assert wallet.total_yield_cents == 5000

    def test_debit_successful(self):
        """Test successful debit from wallet."""
        wallet = Wallet.create(uuid4())
        wallet.credit_investment(Money("1000.00"))
        
        wallet.debit(Money("500.00"))
        
        assert wallet.balance_cents == 50000

    def test_debit_insufficient_balance_raises_error(self):
        """Test debit with insufficient balance raises error."""
        wallet = Wallet.create(uuid4())
        wallet.credit_investment(Money("100.00"))
        
        with pytest.raises(InsufficientBalanceError):
            wallet.debit(Money("200.00"))

    def test_can_withdraw(self):
        """Test checking if withdrawal is possible."""
        wallet = Wallet.create(uuid4())
        wallet.credit_investment(Money("1000.00"))
        
        assert wallet.can_withdraw(Money("500.00"))
        assert wallet.can_withdraw(Money("1000.00"))
        assert not wallet.can_withdraw(Money("1500.00"))


class TestPlan:
    """Test Plan entity."""

    def test_create_plan(self):
        """Test plan creation."""
        plan = Plan.create(
            name="Plano Geral",
            plan_type=PlanType.GERAL,
            description="Plano de investimento geral",
            monthly_installment_cents=100000,  # R$ 1000.00
            duration_months=12,
            fundo_garantidor_percentage=Decimal("1.0"),
        )
        
        assert plan.status == PlanStatus.ACTIVE
        assert plan.monthly_installment_amount == Decimal("1000.00")

    def test_plan_fundo_garantidor_validation(self):
        """Test Fundo Garantidor percentage validation."""
        # Valid minimum
        plan1 = Plan.create(
            name="Plan 1",
            plan_type=PlanType.GERAL,
            description="Test",
            monthly_installment_cents=100000,
            duration_months=12,
            fundo_garantidor_percentage=Decimal("1.0"),
        )
        assert plan1.fundo_garantidor_percentage == Decimal("1.0")
        
        # Valid maximum
        plan2 = Plan.create(
            name="Plan 2",
            plan_type=PlanType.PEQUENO_AGRICULTOR,
            description="Test",
            monthly_installment_cents=50000,
            duration_months=24,
            fundo_garantidor_percentage=Decimal("1.3"),
        )
        assert plan2.fundo_garantidor_percentage == Decimal("1.3")

    def test_plan_invalid_fundo_garantidor_raises_error(self):
        """Test invalid Fundo Garantidor percentage raises error."""
        with pytest.raises(ValueError):
            Plan.create(
                name="Invalid Plan",
                plan_type=PlanType.GERAL,
                description="Test",
                monthly_installment_cents=100000,
                duration_months=12,
                fundo_garantidor_percentage=Decimal("2.0"),  # Above 1.3%
            )


class TestTransaction:
    """Test Transaction entity."""

    def test_create_deposit(self):
        """Test deposit transaction creation."""
        transaction = Transaction.create_deposit(
            user_id=uuid4(),
            contract_id=uuid4(),
            amount_cents=100000,
            installment_number=1,
            installment_type=InstallmentType.FIRST,
        )
        
        assert transaction.transaction_type == TransactionType.DEPOSIT
        assert transaction.is_pending()

    def test_confirm_transaction(self):
        """Test confirming a transaction."""
        transaction = Transaction.create_deposit(
            user_id=uuid4(),
            contract_id=uuid4(),
            amount_cents=100000,
            installment_number=1,
            installment_type=InstallmentType.FIRST,
        )
        
        transaction.confirm(pix_transaction_id="PIX123")
        
        assert transaction.is_confirmed()
        assert transaction.pix_transaction_id == "PIX123"
        assert transaction.confirmed_at is not None

    def test_confirm_non_pending_raises_error(self):
        """Test confirming non-pending transaction raises error."""
        transaction = Transaction.create_deposit(
            user_id=uuid4(),
            contract_id=uuid4(),
            amount_cents=100000,
            installment_number=1,
            installment_type=InstallmentType.FIRST,
        )
        transaction.confirm()
        
        with pytest.raises(InvalidTransactionStatusError):
            transaction.confirm()

    def test_create_withdrawal(self):
        """Test withdrawal transaction creation."""
        transaction = Transaction.create_withdrawal(
            user_id=uuid4(),
            amount_cents=50000,
            bank_account="0001 12345-6",
        )
        
        assert transaction.transaction_type == TransactionType.WITHDRAWAL
        assert transaction.is_pending()
        assert transaction.bank_account == "0001 12345-6"
