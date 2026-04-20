"""Create subscription_activation_payments table.

Revision ID: 016
Revises: 015
Create Date: 2026-03-28
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PGUUID

# revision identifiers, used by Alembic.
revision = "016_activation_payments"
down_revision = "015_sub_inactive"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "subscription_activation_payments",
        sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
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
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("admin_tax_cents", sa.BigInteger(), nullable=False),
        sa.Column("insurance_cents", sa.BigInteger(), nullable=False),
        sa.Column("pix_transaction_fee_cents", sa.BigInteger(), nullable=False),
        sa.Column("total_amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("pix_qr_code_data", sa.Text(), nullable=True),
        sa.Column("pix_transaction_id", sa.String(100), nullable=True, unique=True),
        sa.Column("expiration_minutes", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_subscription_activation_payments_user_id",
        "subscription_activation_payments",
        ["user_id"],
    )
    op.create_index(
        "ix_subscription_activation_payments_subscription_id",
        "subscription_activation_payments",
        ["subscription_id"],
    )
    op.create_index(
        "ix_subscription_activation_payments_status",
        "subscription_activation_payments",
        ["status"],
    )
    op.create_index(
        "ix_subscription_activation_payments_pix_transaction_id",
        "subscription_activation_payments",
        ["pix_transaction_id"],
    )
    op.create_index(
        "ix_subscription_activation_payments_user_status",
        "subscription_activation_payments",
        ["user_id", "status"],
    )
    op.create_index(
        "ix_subscription_activation_payments_sub_id",
        "subscription_activation_payments",
        ["subscription_id"],
    )
    # Also add pix_transaction_fee_cents to installment_payments
    op.add_column(
        "installment_payments",
        sa.Column(
            "pix_transaction_fee_cents",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("installment_payments", "pix_transaction_fee_cents")
    op.drop_index(
        "ix_subscription_activation_payments_sub_id",
        table_name="subscription_activation_payments",
    )
    op.drop_index(
        "ix_subscription_activation_payments_user_status",
        table_name="subscription_activation_payments",
    )
    op.drop_index(
        "ix_subscription_activation_payments_pix_transaction_id",
        table_name="subscription_activation_payments",
    )
    op.drop_index(
        "ix_subscription_activation_payments_status",
        table_name="subscription_activation_payments",
    )
    op.drop_index(
        "ix_subscription_activation_payments_subscription_id",
        table_name="subscription_activation_payments",
    )
    op.drop_index(
        "ix_subscription_activation_payments_user_id",
        table_name="subscription_activation_payments",
    )
    op.drop_table("subscription_activation_payments")
