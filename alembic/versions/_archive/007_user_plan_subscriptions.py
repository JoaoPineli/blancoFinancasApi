"""Add user_plan_subscriptions table

Revision ID: 007_user_plan_subscriptions
Revises: 006_plan_soft_delete
Create Date: 2026-02-25

This migration creates the user_plan_subscriptions table.
A user can have zero, one, or many subscriptions, including
multiple subscriptions to the same plan. Each subscription stores
a snapshot of the chosen parameters and applicable fees at creation time.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PGUUID

# revision identifiers, used by Alembic.
revision: str = "007_user_plan_subscriptions"
down_revision: Union[str, None] = "006_plan_soft_delete"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_plan_subscriptions",
        sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
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
        # User-chosen parameters
        sa.Column("target_amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("deposit_count", sa.Integer(), nullable=False),
        sa.Column("monthly_amount_cents", sa.BigInteger(), nullable=False),
        # Snapshot of plan fees at creation time
        sa.Column("admin_tax_value_cents", sa.BigInteger(), nullable=False),
        sa.Column("insurance_percent", sa.Numeric(5, 2), nullable=False),
        sa.Column("guarantee_fund_percent", sa.Numeric(5, 2), nullable=False),
        # Pre-calculated total cost
        sa.Column("total_cost_cents", sa.BigInteger(), nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="active",
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    # Indexes
    op.create_index(
        "ix_user_plan_subscriptions_user_id",
        "user_plan_subscriptions",
        ["user_id"],
    )
    op.create_index(
        "ix_user_plan_subscriptions_plan_id",
        "user_plan_subscriptions",
        ["plan_id"],
    )
    op.create_index(
        "ix_user_plan_subscriptions_user_status",
        "user_plan_subscriptions",
        ["user_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_plan_subscriptions_user_status",
        table_name="user_plan_subscriptions",
    )
    op.drop_index(
        "ix_user_plan_subscriptions_plan_id",
        table_name="user_plan_subscriptions",
    )
    op.drop_index(
        "ix_user_plan_subscriptions_user_id",
        table_name="user_plan_subscriptions",
    )
    op.drop_table("user_plan_subscriptions")
