"""Tests for domain entities."""

import pytest
from datetime import datetime, timedelta
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

    def test_create_registered_user(self):
        """Test creating a registered user (all fields set, REGISTERED status)."""
        user = User.create_registered(
            cpf=CPF("529.982.247-25"),
            email=Email("registered@example.com"),
            name="Registered User",
            password_hash="hashed_password",
            phone="11999999999",
        )
        
        assert user.status == UserStatus.REGISTERED
        assert user.cpf is not None
        assert user.password_hash == "hashed_password"
        assert user.phone == "11999999999"
        assert user.role == UserRole.CLIENT

    def test_create_registered_user_with_nickname(self):
        """Test creating a registered user with nickname."""
        user = User.create_registered(
            cpf=CPF("529.982.247-25"),
            email=Email("registered@example.com"),
            name="Registered User",
            password_hash="hashed_password",
            phone="11999999999",
            nickname="Nick",
        )
        
        assert user.nickname == "Nick"

    def test_is_registered(self):
        """Test is_registered helper method."""
        registered = User.create_registered(
            cpf=CPF("529.982.247-25"),
            email=Email("registered@example.com"),
            name="Registered User",
            password_hash="hashed_password",
            phone="11999999999",
        )
        active = User.create(
            cpf=CPF("529.982.247-25"),
            email=Email("active@example.com"),
            name="Active User",
            password_hash="hashed",
        )
        
        assert registered.is_registered()
        assert not active.is_registered()

    def test_complete_activation(self):
        """Test completing activation for registered user."""
        user = User.create_registered(
            cpf=CPF("529.982.247-25"),
            email=Email("registered@example.com"),
            name="Registered User",
            password_hash="hashed_password",
            phone="11999999999",
            nickname="Nick",
        )
        
        user.complete_activation()
        
        assert user.status == UserStatus.ACTIVE
        # All fields remain unchanged
        assert user.cpf is not None
        assert user.password_hash == "hashed_password"
        assert user.phone == "11999999999"
        assert user.nickname == "Nick"

    def test_complete_activation_only_for_registered_users(self):
        """Test that only registered users can complete activation."""
        user = User.create(
            cpf=CPF("529.982.247-25"),
            email=Email("active@example.com"),
            name="Active User",
            password_hash="hashed",
        )
        
        with pytest.raises(ValueError, match="Only registered users"):
            user.complete_activation()

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


class TestInstallmentPayment:
    """Test InstallmentPayment entity — is_stale logic."""

    def _make_payment(self, created_at=None, expiration_minutes=30):
        from app.domain.entities.installment_payment import InstallmentPayment, PaymentStatus, InstallmentPaymentItem
        pid = uuid4()
        return InstallmentPayment(
            id=pid,
            user_id=uuid4(),
            status=PaymentStatus.PENDING,
            total_amount_cents=50_000,
            pix_qr_code_data="qr",
            pix_transaction_id=None,
            expiration_minutes=expiration_minutes,
            items=[
                InstallmentPaymentItem(
                    id=uuid4(), payment_id=pid,
                    subscription_id=uuid4(), subscription_name="Sub",
                    plan_title="Plan", amount_cents=50_000,
                    installment_number=1,
                )
            ],
            created_at=created_at or datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

    def test_is_stale_fresh_payment(self):
        """Payment created just now is not stale."""
        p = self._make_payment()
        assert p.is_stale() is False

    def test_is_stale_after_expiration(self):
        """Payment older than expiration_minutes is stale."""
        p = self._make_payment(created_at=datetime.utcnow() - timedelta(minutes=31))
        assert p.is_stale() is True

    def test_is_stale_exact_boundary(self):
        """Payment at exactly expiration_minutes boundary is stale."""
        from datetime import timezone
        now = datetime.now(timezone.utc)
        p = self._make_payment(created_at=now - timedelta(minutes=30))
        assert p.is_stale(now=now) is True

    def test_is_stale_confirmed_not_stale(self):
        """Confirmed payment is never stale."""
        p = self._make_payment(created_at=datetime.utcnow() - timedelta(hours=2))
        p.confirm("pix_tx_1")
        assert p.is_stale() is False

    def test_is_stale_expired_not_stale(self):
        """Already-expired payment is not stale (only pending can be stale)."""
        p = self._make_payment(created_at=datetime.utcnow() - timedelta(hours=2))
        p.expire()
        assert p.is_stale() is False
