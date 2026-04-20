"""Add installment payments and deposits_paid tracking.

Revision ID: 010
Revises: 009
Create Date: 2026-03-09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PGUUID

# revision identifiers, used by Alembic.
revision = "010_installment_payments"
down_revision = "009_subscription_name"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Add deposits_paid to subscriptions ---
    op.add_column(
        "user_plan_subscriptions",
        sa.Column("deposits_paid", sa.Integer(), nullable=False, server_default="0"),
    )

    # --- Create installment_payments table ---
    op.create_table(
        "installment_payments",
        sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("total_amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("pix_qr_code_data", sa.Text(), nullable=True),
        sa.Column("pix_transaction_id", sa.String(100), nullable=True, unique=True),
        sa.Column("expiration_minutes", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_installment_payments_user_id",
        "installment_payments",
        ["user_id"],
    )
    op.create_index(
        "ix_installment_payments_status",
        "installment_payments",
        ["status"],
    )
    op.create_index(
        "ix_installment_payments_user_status",
        "installment_payments",
        ["user_id", "status"],
    )
    op.create_index(
        "ix_installment_payments_pix_transaction_id",
        "installment_payments",
        ["pix_transaction_id"],
    )

    # --- Create installment_payment_items table ---
    op.create_table(
        "installment_payment_items",
        sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
        sa.Column(
            "payment_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("installment_payments.id", ondelete="CASCADE"),
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
        sa.Column("installment_number", sa.Integer(), nullable=False),
    )
    op.create_index(
        "ix_installment_payment_items_payment_id",
        "installment_payment_items",
        ["payment_id"],
    )
    op.create_index(
        "ix_installment_payment_items_subscription_id",
        "installment_payment_items",
        ["subscription_id"],
    )
    op.create_index(
        "ix_installment_payment_items_sub_payment",
        "installment_payment_items",
        ["subscription_id", "payment_id"],
    )


def downgrade() -> None:
    op.drop_table("installment_payment_items")
    op.drop_table("installment_payments")
    op.drop_column("user_plan_subscriptions", "deposits_paid")
