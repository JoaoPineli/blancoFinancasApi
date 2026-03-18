"""Add principal_deposits table for per-installment poupança yield tracking.

Each confirmed InstallmentPaymentItem produces one PrincipalDeposit record.
deposited_at is the poupança anniversary anchor date.
last_yield_run_date enables idempotent yield crediting.

Revision ID: 011
Revises: 010
Create Date: 2026-03-18
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PGUUID

# revision identifiers, used by Alembic.
revision = "011_principal_deposits"
down_revision = "010_installment_payments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "principal_deposits",
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
        sa.Column(
            "installment_payment_item_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("installment_payment_items.id"),
            nullable=False,
            unique=True,  # one deposit per payment item
        ),
        sa.Column("installment_number", sa.Integer(), nullable=False),
        sa.Column("principal_cents", sa.BigInteger(), nullable=False),
        sa.Column("deposited_at", sa.Date(), nullable=False),
        sa.Column("last_yield_run_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_index(
        "ix_principal_deposits_user_id",
        "principal_deposits",
        ["user_id"],
    )
    op.create_index(
        "ix_principal_deposits_subscription_id",
        "principal_deposits",
        ["subscription_id"],
    )
    op.create_index(
        "ix_principal_deposits_deposited_at",
        "principal_deposits",
        ["deposited_at"],
    )
    # Compound index for the yield processing query
    # (last_yield_run_date IS NULL OR last_yield_run_date < X)
    op.create_index(
        "ix_principal_deposits_last_yield_run",
        "principal_deposits",
        ["last_yield_run_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_principal_deposits_last_yield_run", "principal_deposits")
    op.drop_index("ix_principal_deposits_deposited_at", "principal_deposits")
    op.drop_index("ix_principal_deposits_subscription_id", "principal_deposits")
    op.drop_index("ix_principal_deposits_user_id", "principal_deposits")
    op.drop_table("principal_deposits")
