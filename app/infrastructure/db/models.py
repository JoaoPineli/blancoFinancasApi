"""SQLAlchemy ORM models."""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSON, UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """SQLAlchemy declarative base."""

    pass


class UserModel(Base):
    """SQLAlchemy model for platform users (users)."""

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    cpf: Mapped[Optional[str]] = mapped_column(String(11), unique=True, nullable=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    nickname: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    plan_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("plans.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # Relationships
    wallet: Mapped["WalletModel"] = relationship(back_populates="user", uselist=False)
    contracts: Mapped[list["ContractModel"]] = relationship(back_populates="user")
    transactions: Mapped[list["TransactionModel"]] = relationship(back_populates="user")
    plan: Mapped[Optional["PlanModel"]] = relationship(back_populates="invited_users")
    tokens: Mapped[list["UserTokenModel"]] = relationship(back_populates="user")
    subscriptions: Mapped[list["UserPlanSubscriptionModel"]] = relationship(
        back_populates="user"
    )


class PlanModel(Base):
    """SQLAlchemy model for investment plans.

    Stores plan configuration parameters:
    - Identification (title, description)
    - Constraints (value and duration ranges)
    - First installment parameters (admin tax, insurance, guarantee fund)
    """

    __tablename__ = "plans"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    title: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Constraints (based on total contracted plan value and duration)
    min_value_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    max_value_cents: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    min_duration_months: Mapped[int] = mapped_column(Integer, nullable=False)
    max_duration_months: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # First installment configuration parameters
    admin_tax_value_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    insurance_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    guarantee_fund_percent_1: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    guarantee_fund_percent_2: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    guarantee_fund_threshold_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)

    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)

    # Relationships
    contracts: Mapped[list["ContractModel"]] = relationship(back_populates="plan")
    invited_users: Mapped[list["UserModel"]] = relationship(back_populates="plan")
    subscriptions: Mapped[list["UserPlanSubscriptionModel"]] = relationship(
        back_populates="plan"
    )


class ContractModel(Base):
    """SQLAlchemy model for contracts."""

    __tablename__ = "contracts"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    plan_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("plans.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    pdf_storage_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    start_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    end_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # Relationships
    user: Mapped["UserModel"] = relationship(back_populates="contracts")
    plan: Mapped["PlanModel"] = relationship(back_populates="contracts")
    transactions: Mapped[list["TransactionModel"]] = relationship(back_populates="contract")


class WalletModel(Base):
    """SQLAlchemy model for wallets."""

    __tablename__ = "wallets"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), unique=True, nullable=False
    )
    balance_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_invested_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_yield_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    fundo_garantidor_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # Relationships
    user: Mapped["UserModel"] = relationship(back_populates="wallet")


class TransactionModel(Base):
    """SQLAlchemy model for transactions."""

    __tablename__ = "transactions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    contract_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("contracts.id"), nullable=True, index=True
    )
    subscription_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("user_plan_subscriptions.id"),
        nullable=True,
    )
    transaction_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    installment_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    installment_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    pix_key: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    pix_key_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    pix_transaction_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    bank_account: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # Payment-flow fields (SUBSCRIPTION_INSTALLMENT_PAYMENT / SUBSCRIPTION_ACTIVATION_PAYMENT)
    pix_qr_code_data: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    expiration_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    pix_transaction_fee_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    # Activation-payment breakdown snapshots
    admin_tax_cents: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    insurance_cents: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    # Relationships
    user: Mapped["UserModel"] = relationship(back_populates="transactions")
    contract: Mapped[Optional["ContractModel"]] = relationship(back_populates="transactions")
    items: Mapped[list["TransactionItemModel"]] = relationship(
        back_populates="transaction", cascade="all, delete-orphan"
    )

    # Indexes
    __table_args__ = (
        Index("ix_transactions_user_type_status", "user_id", "transaction_type", "status"),
        Index("ix_transactions_subscription_id", "subscription_id"),
        Index("ix_transactions_pix_transaction_id", "pix_transaction_id"),
    )


class TransactionItemModel(Base):
    """SQLAlchemy model for transaction line-items.

    One item per subscription within a SUBSCRIPTION_INSTALLMENT_PAYMENT or
    SUBSCRIPTION_ACTIVATION_PAYMENT transaction.
    """

    __tablename__ = "transaction_items"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    transaction_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("transactions.id", ondelete="CASCADE"),
        nullable=False,
    )
    subscription_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("user_plan_subscriptions.id"),
        nullable=False,
    )
    subscription_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    plan_title: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    installment_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Relationships
    transaction: Mapped["TransactionModel"] = relationship(back_populates="items")

    __table_args__ = (
        Index("ix_transaction_items_transaction_id", "transaction_id"),
        Index("ix_transaction_items_subscription_id", "subscription_id"),
        Index(
            "ix_transaction_items_sub_transaction",
            "subscription_id",
            "transaction_id",
        ),
    )


class UserPlanSubscriptionModel(Base):
    """SQLAlchemy model for user plan subscriptions.

    A user can have zero, one, or many subscriptions,
    including multiple subscriptions to the same plan.
    """

    __tablename__ = "user_plan_subscriptions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    plan_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("plans.id"), nullable=False, index=True
    )

    # Cosmetic user-given name
    name: Mapped[str] = mapped_column(String(120), nullable=False, default="")

    # User-chosen parameters
    target_amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    deposit_count: Mapped[int] = mapped_column(Integer, nullable=False)
    monthly_amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Snapshot of plan fees at time of subscription creation
    admin_tax_value_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    insurance_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    guarantee_fund_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)

    # Pre-calculated total cost
    total_cost_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Payment tracking
    deposits_paid: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Deposit due-date fields
    deposit_day_of_month: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    next_due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    has_overdue_deposit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    overdue_marked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Whether activation fees (admin_tax + insurance) were paid via activation payment
    covers_activation_fees: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # Relationships
    user: Mapped["UserModel"] = relationship(back_populates="subscriptions")
    plan: Mapped["PlanModel"] = relationship(back_populates="subscriptions")

    __table_args__ = (
        Index("ix_user_plan_subscriptions_user_status", "user_id", "status"),
        Index("ix_user_plan_subscriptions_user_due", "user_id", "next_due_date"),
        Index(
            "ix_user_plan_subscriptions_user_overdue_due",
            "user_id",
            "has_overdue_deposit",
            "next_due_date",
        ),
        CheckConstraint(
            "deposit_day_of_month IN (1, 5, 10, 15, 20, 25)",
            name="ck_subscriptions_deposit_day",
        ),
    )


class AuditLogModel(Base):
    """SQLAlchemy model for audit logs."""

    __tablename__ = "audit_logs"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    actor_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    target_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    target_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)


class YieldDataModel(Base):
    """SQLAlchemy model for BCB yield data."""

    __tablename__ = "yield_data"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    series_id: Mapped[int] = mapped_column(Integer, nullable=False)
    reference_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint("series_id", "reference_date", name="uq_yield_data_series_date"),
        Index("ix_yield_data_series_date", "series_id", "reference_date"),
    )


class PrincipalDepositModel(Base):
    """SQLAlchemy model for per-installment principal deposit tracking.

    Each confirmed SUBSCRIPTION_INSTALLMENT_PAYMENT TransactionItem produces
    one PrincipalDeposit. deposited_at is the anchor date for poupança
    anniversary calculation. last_yield_run_date enables idempotent yield
    crediting.
    """

    __tablename__ = "principal_deposits"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    subscription_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("user_plan_subscriptions.id"),
        nullable=False,
    )
    transaction_item_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("transaction_items.id"),
        nullable=False,
        unique=True,  # one deposit per transaction item
    )
    installment_number: Mapped[int] = mapped_column(Integer, nullable=False)
    principal_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    deposited_at: Mapped[date] = mapped_column(Date, nullable=False)
    last_yield_run_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        Index("ix_principal_deposits_user_id", "user_id"),
        Index("ix_principal_deposits_subscription_id", "subscription_id"),
        Index("ix_principal_deposits_deposited_at", "deposited_at"),
        Index("ix_principal_deposits_last_yield_run", "last_yield_run_date"),
    )


class UserTokenModel(Base):
    """SQLAlchemy model for user tokens (activation, password reset)."""

    __tablename__ = "user_tokens"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    token_type: Mapped[str] = mapped_column(String(20), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # Relationships
    user: Mapped["UserModel"] = relationship(back_populates="tokens")

    __table_args__ = (
        Index("ix_user_tokens_user_type", "user_id", "token_type"),
    )


class NotificationModel(Base):
    """SQLAlchemy model for admin notifications."""

    __tablename__ = "notifications"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    notification_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    target_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    target_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_notifications_notification_type", "notification_type"),
        Index("ix_notifications_is_read", "is_read"),
        Index("ix_notifications_created_at", "created_at"),
    )
