"""SQLAlchemy ORM models."""

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
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


class PlanModel(Base):
    """SQLAlchemy model for investment plans."""

    __tablename__ = "plans"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    plan_type: Mapped[str] = mapped_column(String(30), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    monthly_installment_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    duration_months: Mapped[int] = mapped_column(Integer, nullable=False)
    fundo_garantidor_percentage: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # Relationships
    contracts: Mapped[list["ContractModel"]] = relationship(back_populates="plan")
    invited_users: Mapped[list["UserModel"]] = relationship(back_populates="plan")


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
    transaction_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    installment_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    installment_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    pix_key: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    pix_transaction_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    bank_account: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relationships
    user: Mapped["UserModel"] = relationship(back_populates="transactions")
    contract: Mapped[Optional["ContractModel"]] = relationship(back_populates="transactions")

    # Indexes
    __table_args__ = (
        Index("ix_transactions_user_type_status", "user_id", "transaction_type", "status"),
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

