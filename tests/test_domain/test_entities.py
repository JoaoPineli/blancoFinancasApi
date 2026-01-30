"""Tests for domain entities."""

import pytest
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from app.domain.entities.user import User, UserRole, UserStatus
from app.domain.entities.wallet import Wallet
from app.domain.entities.plan import Plan
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
        assert user.cpf is not None
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
            title="Plano Geral",
            description="Plano de investimento geral",
            min_value_cents=100000,  # R$ 1000.00
            max_value_cents=10000000,  # R$ 100,000.00
            min_duration_months=6,
            max_duration_months=36,
            admin_tax_value_cents=5000,  # R$ 50.00
            insurance_percent=Decimal("2.5"),
            guarantee_fund_percent_1=Decimal("1.0"),
            guarantee_fund_percent_2=Decimal("1.3"),
            guarantee_fund_threshold_cents=5000000,  # R$ 50,000.00
        )
        
        assert plan.active
        assert plan.title == "Plano Geral"
        assert plan.min_value_cents == 100000
        assert plan.max_value_cents == 10000000

    def test_plan_percentage_validation(self):
        """Test percentage validation (0-100 range)."""
        # Valid percentages
        plan = Plan.create(
            title="Plan Valid",
            description="Test",
            min_value_cents=100000,
            max_value_cents=1000000,
            min_duration_months=6,
            max_duration_months=12,
            admin_tax_value_cents=5000,
            insurance_percent=Decimal("2.5"),
            guarantee_fund_percent_1=Decimal("1.0"),
            guarantee_fund_percent_2=Decimal("1.3"),
            guarantee_fund_threshold_cents=500000,
        )
        assert plan.guarantee_fund_percent_1 == Decimal("1.0")
        assert plan.guarantee_fund_percent_2 == Decimal("1.3")

    def test_plan_invalid_percentage_raises_error(self):
        """Test invalid percentage raises error."""
        with pytest.raises(ValueError):
            Plan.create(
                title="Invalid Plan",
                description="Test",
                min_value_cents=100000,
                max_value_cents=1000000,
                min_duration_months=6,
                max_duration_months=12,
                admin_tax_value_cents=5000,
                insurance_percent=Decimal("150"),  # Above 100%
                guarantee_fund_percent_1=Decimal("1.0"),
                guarantee_fund_percent_2=Decimal("1.3"),
                guarantee_fund_threshold_cents=500000,
            )

    def test_plan_min_max_value_constraint(self):
        """Test min/max value constraint validation."""
        with pytest.raises(ValueError, match="Minimum value cannot exceed maximum value"):
            Plan.create(
                title="Invalid Plan",
                description="Test",
                min_value_cents=1000000,  # Greater than max
                max_value_cents=100000,
                min_duration_months=6,
                max_duration_months=12,
                admin_tax_value_cents=5000,
                insurance_percent=Decimal("2.5"),
                guarantee_fund_percent_1=Decimal("1.0"),
                guarantee_fund_percent_2=Decimal("1.3"),
                guarantee_fund_threshold_cents=500000,
            )

    def test_soft_delete_plan(self):
        """Test soft deleting a plan."""
        plan = Plan.create(
            title="Plan to Delete",
            description="Test plan for soft delete",
            min_value_cents=100000,
            max_value_cents=1000000,
            min_duration_months=6,
            max_duration_months=12,
            admin_tax_value_cents=5000,
            insurance_percent=Decimal("2.5"),
            guarantee_fund_percent_1=Decimal("1.0"),
            guarantee_fund_percent_2=Decimal("1.3"),
            guarantee_fund_threshold_cents=500000,
        )

        assert plan.deleted_at is None
        assert not plan.is_deleted()

        plan.soft_delete()

        assert plan.deleted_at is not None
        assert plan.is_deleted()

    def test_soft_delete_already_deleted_raises_error(self):
        """Test soft deleting an already deleted plan raises error."""
        plan = Plan.create(
            title="Already Deleted Plan",
            description="Test plan",
            min_value_cents=100000,
            max_value_cents=1000000,
            min_duration_months=6,
            max_duration_months=12,
            admin_tax_value_cents=5000,
            insurance_percent=Decimal("2.5"),
            guarantee_fund_percent_1=Decimal("1.0"),
            guarantee_fund_percent_2=Decimal("1.3"),
            guarantee_fund_threshold_cents=500000,
        )

        plan.soft_delete()

        with pytest.raises(ValueError, match="Plan is already deleted"):
            plan.soft_delete()

    def test_is_active_returns_false_when_deleted(self):
        """Test is_active returns False when plan is soft deleted."""
        plan = Plan.create(
            title="Active Plan",
            description="Test plan",
            min_value_cents=100000,
            max_value_cents=1000000,
            min_duration_months=6,
            max_duration_months=12,
            admin_tax_value_cents=5000,
            insurance_percent=Decimal("2.5"),
            guarantee_fund_percent_1=Decimal("1.0"),
            guarantee_fund_percent_2=Decimal("1.3"),
            guarantee_fund_threshold_cents=500000,
        )

        assert plan.is_active()

        plan.soft_delete()

        # Even though active flag is True, is_active() should return False
        assert plan.active is True
        assert not plan.is_active()

    def test_is_active_returns_false_when_deactivated(self):
        """Test is_active returns False when plan is deactivated."""
        plan = Plan.create(
            title="Deactivated Plan",
            description="Test plan",
            min_value_cents=100000,
            max_value_cents=1000000,
            min_duration_months=6,
            max_duration_months=12,
            admin_tax_value_cents=5000,
            insurance_percent=Decimal("2.5"),
            guarantee_fund_percent_1=Decimal("1.0"),
            guarantee_fund_percent_2=Decimal("1.3"),
            guarantee_fund_threshold_cents=500000,
        )

        plan.deactivate()

        assert not plan.is_active()
        assert not plan.is_deleted()


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
