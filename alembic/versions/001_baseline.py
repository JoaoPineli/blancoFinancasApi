"""Baseline migration — creates the full schema from scratch.

Revision ID: 001_baseline
Revises:
Create Date: 2026-04-17

Consolidates migrations 001–018 into a single initial migration that
reflects the current ORM (app/infrastructure/db/models.py) exactly.
Old migration files are archived in alembic/versions/_archive/.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON, UUID as PGUUID

revision: str = "001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # plans
    # ------------------------------------------------------------------
    op.create_table(
        "plans",
        sa.Column("id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("min_value_cents", sa.BigInteger(), nullable=False),
        sa.Column("max_value_cents", sa.BigInteger(), nullable=True),
        sa.Column("min_duration_months", sa.Integer(), nullable=False),
        sa.Column("max_duration_months", sa.Integer(), nullable=True),
        sa.Column("admin_tax_value_cents", sa.BigInteger(), nullable=False),
        sa.Column("insurance_percent", sa.Numeric(5, 2), nullable=False),
        sa.Column("guarantee_fund_percent_1", sa.Numeric(5, 2), nullable=False),
        sa.Column("guarantee_fund_percent_2", sa.Numeric(5, 2), nullable=False),
        sa.Column("guarantee_fund_threshold_cents", sa.BigInteger(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_plans_title", "plans", ["title"])
    op.create_index("ix_plans_deleted_at", "plans", ["deleted_at"])

    # ------------------------------------------------------------------
    # users
    # ------------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("cpf", sa.String(11), nullable=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("role", sa.String(20), nullable=False, server_default="user"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("nickname", sa.String(100), nullable=True),
        sa.Column(
            "plan_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("plans.id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    # Partial unique index: CPF unique only when non-NULL (invited users have no CPF yet)
    op.execute("CREATE UNIQUE INDEX ix_users_cpf ON users (cpf) WHERE cpf IS NOT NULL")
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_plan_id", "users", ["plan_id"])

    # ------------------------------------------------------------------
    # contracts
    # ------------------------------------------------------------------
    op.create_table(
        "contracts",
        sa.Column("id", PGUUID(as_uuid=True), nullable=False),
        sa.Column(
            "user_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "plan_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("plans.id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("pdf_storage_path", sa.String(500), nullable=True),
        sa.Column("accepted_at", sa.DateTime(), nullable=True),
        sa.Column("start_date", sa.DateTime(), nullable=True),
        sa.Column("end_date", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_contracts_user_id", "contracts", ["user_id"])
    op.create_index("ix_contracts_plan_id", "contracts", ["plan_id"])

    # ------------------------------------------------------------------
    # wallets
    # ------------------------------------------------------------------
    op.create_table(
        "wallets",
        sa.Column("id", PGUUID(as_uuid=True), nullable=False),
        sa.Column(
            "user_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("balance_cents", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "total_invested_cents", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "total_yield_cents", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "fundo_garantidor_cents", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # ------------------------------------------------------------------
    # user_plan_subscriptions
    # ------------------------------------------------------------------
    op.create_table(
        "user_plan_subscriptions",
        sa.Column("id", PGUUID(as_uuid=True), nullable=False),
        sa.Column(
            "user_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "plan_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("plans.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(120), nullable=False, server_default=""),
        sa.Column("target_amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("deposit_count", sa.Integer(), nullable=False),
        sa.Column("monthly_amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("admin_tax_value_cents", sa.BigInteger(), nullable=False),
        sa.Column("insurance_percent", sa.Numeric(5, 2), nullable=False),
        sa.Column("guarantee_fund_percent", sa.Numeric(5, 2), nullable=False),
        sa.Column("total_cost_cents", sa.BigInteger(), nullable=False),
        sa.Column("deposits_paid", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "deposit_day_of_month", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column("next_due_date", sa.Date(), nullable=True),
        sa.Column(
            "has_overdue_deposit",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column("overdue_marked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "covers_activation_fees",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "deposit_day_of_month IN (1, 5, 10, 15, 20, 25)",
            name="ck_subscriptions_deposit_day",
        ),
    )
    op.create_index(
        "ix_user_plan_subscriptions_user_id", "user_plan_subscriptions", ["user_id"]
    )
    op.create_index(
        "ix_user_plan_subscriptions_plan_id", "user_plan_subscriptions", ["plan_id"]
    )
    op.create_index(
        "ix_user_plan_subscriptions_user_status",
        "user_plan_subscriptions",
        ["user_id", "status"],
    )
    op.create_index(
        "ix_user_plan_subscriptions_user_due",
        "user_plan_subscriptions",
        ["user_id", "next_due_date"],
    )
    op.create_index(
        "ix_user_plan_subscriptions_user_overdue_due",
        "user_plan_subscriptions",
        ["user_id", "has_overdue_deposit", "next_due_date"],
    )

    # ------------------------------------------------------------------
    # transactions
    # ------------------------------------------------------------------
    op.create_table(
        "transactions",
        sa.Column("id", PGUUID(as_uuid=True), nullable=False),
        sa.Column(
            "user_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "contract_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("contracts.id"),
            nullable=True,
        ),
        sa.Column(
            "subscription_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("user_plan_subscriptions.id"),
            nullable=True,
        ),
        sa.Column("transaction_type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("installment_number", sa.Integer(), nullable=True),
        sa.Column("installment_type", sa.String(20), nullable=True),
        sa.Column("pix_key", sa.String(100), nullable=True),
        sa.Column("pix_key_type", sa.String(20), nullable=True),
        sa.Column("pix_transaction_id", sa.String(100), nullable=True),
        sa.Column("bank_account", sa.String(200), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("pix_qr_code_data", sa.Text(), nullable=True),
        sa.Column("pix_qr_code_base64", sa.Text(), nullable=True),
        sa.Column("expiration_minutes", sa.Integer(), nullable=True),
        sa.Column(
            "pix_transaction_fee_cents",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("admin_tax_cents", sa.BigInteger(), nullable=True),
        sa.Column("insurance_cents", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_transactions_user_id", "transactions", ["user_id"])
    op.create_index("ix_transactions_contract_id", "transactions", ["contract_id"])
    op.create_index(
        "ix_transactions_transaction_type", "transactions", ["transaction_type"]
    )
    op.create_index("ix_transactions_status", "transactions", ["status"])
    op.create_index(
        "ix_transactions_user_type_status",
        "transactions",
        ["user_id", "transaction_type", "status"],
    )
    op.create_index(
        "ix_transactions_subscription_id", "transactions", ["subscription_id"]
    )
    op.create_index(
        "ix_transactions_pix_transaction_id", "transactions", ["pix_transaction_id"]
    )

    # ------------------------------------------------------------------
    # transaction_items
    # ------------------------------------------------------------------
    op.create_table(
        "transaction_items",
        sa.Column("id", PGUUID(as_uuid=True), nullable=False),
        sa.Column(
            "transaction_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("transactions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "subscription_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("user_plan_subscriptions.id"),
            nullable=False,
        ),
        sa.Column("subscription_name", sa.String(120), nullable=False, server_default=""),
        sa.Column("plan_title", sa.String(100), nullable=False, server_default=""),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("installment_number", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_transaction_items_transaction_id", "transaction_items", ["transaction_id"]
    )
    op.create_index(
        "ix_transaction_items_subscription_id", "transaction_items", ["subscription_id"]
    )
    op.create_index(
        "ix_transaction_items_sub_transaction",
        "transaction_items",
        ["subscription_id", "transaction_id"],
    )

    # ------------------------------------------------------------------
    # principal_deposits
    # ------------------------------------------------------------------
    op.create_table(
        "principal_deposits",
        sa.Column("id", PGUUID(as_uuid=True), nullable=False),
        sa.Column(
            "user_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "subscription_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("user_plan_subscriptions.id"),
            nullable=False,
        ),
        sa.Column(
            "transaction_item_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("transaction_items.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("installment_number", sa.Integer(), nullable=False),
        sa.Column("principal_cents", sa.BigInteger(), nullable=False),
        sa.Column("deposited_at", sa.Date(), nullable=False),
        sa.Column("last_yield_run_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "transaction_item_id", name="uq_principal_deposits_transaction_item_id"
        ),
    )
    op.create_index(
        "ix_principal_deposits_user_id", "principal_deposits", ["user_id"]
    )
    op.create_index(
        "ix_principal_deposits_subscription_id",
        "principal_deposits",
        ["subscription_id"],
    )
    op.create_index(
        "ix_principal_deposits_deposited_at", "principal_deposits", ["deposited_at"]
    )
    op.create_index(
        "ix_principal_deposits_last_yield_run",
        "principal_deposits",
        ["last_yield_run_date"],
    )
    # ------------------------------------------------------------------
    # audit_logs
    # ------------------------------------------------------------------
    op.create_table(
        "audit_logs",
        sa.Column("id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("actor_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("target_id", PGUUID(as_uuid=True), nullable=True),
        sa.Column("target_type", sa.String(50), nullable=True),
        sa.Column("details", JSON(), nullable=False, server_default="{}"),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_actor_id", "audit_logs", ["actor_id"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])

    # ------------------------------------------------------------------
    # yield_data
    # ------------------------------------------------------------------
    op.create_table(
        "yield_data",
        sa.Column("id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("series_id", sa.Integer(), nullable=False),
        sa.Column("reference_date", sa.DateTime(), nullable=False),
        sa.Column("rate", sa.Numeric(12, 8), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "series_id", "reference_date", name="uq_yield_data_series_date"
        ),
    )
    op.create_index(
        "ix_yield_data_series_date", "yield_data", ["series_id", "reference_date"]
    )

    # ------------------------------------------------------------------
    # user_tokens
    # ------------------------------------------------------------------
    op.create_table(
        "user_tokens",
        sa.Column("id", PGUUID(as_uuid=True), nullable=False),
        sa.Column(
            "user_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(255), nullable=False),
        sa.Column("token_type", sa.String(20), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_tokens_user_id", "user_tokens", ["user_id"])
    op.create_index("ix_user_tokens_token_hash", "user_tokens", ["token_hash"])
    op.create_index(
        "ix_user_tokens_user_type", "user_tokens", ["user_id", "token_type"]
    )

    # ------------------------------------------------------------------
    # notifications
    # ------------------------------------------------------------------
    op.create_table(
        "notifications",
        sa.Column("id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("notification_type", sa.String(50), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("target_id", PGUUID(as_uuid=True), nullable=True),
        sa.Column("target_type", sa.String(50), nullable=True),
        sa.Column("data", JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_notifications_notification_type", "notifications", ["notification_type"]
    )
    op.create_index("ix_notifications_is_read", "notifications", ["is_read"])
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"])


def downgrade() -> None:
    op.drop_table("notifications")
    op.drop_table("user_tokens")
    op.drop_table("yield_data")
    op.drop_table("audit_logs")
    op.drop_table("principal_deposits")
    op.drop_table("transaction_items")
    op.drop_table("transactions")
    op.drop_table("user_plan_subscriptions")
    op.drop_table("wallets")
    op.drop_table("contracts")
    op.drop_table("users")
    op.drop_table("plans")
