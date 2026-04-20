"""Add deposit due-date fields to user_plan_subscriptions

Revision ID: 008_subscription_deposit_due_dates
Revises: 007_user_plan_subscriptions
Create Date: 2026-02-26

Adds fields for monthly deposit due-date selection and lazy overdue flagging:
- deposit_day_of_month: fixed day-of-month for deposits (1,5,10,15,20,25)
- next_due_date: computed next deposit due date
- has_overdue_deposit: lazy-updated flag when a deposit is overdue
- overdue_marked_at: timestamp of when overdue was first detected
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "008_sub_deposit_due_dates"
down_revision: Union[str, None] = "007_user_plan_subscriptions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add deposit_day_of_month with default 1 for existing rows
    op.add_column(
        "user_plan_subscriptions",
        sa.Column(
            "deposit_day_of_month",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.create_check_constraint(
        "ck_subscriptions_deposit_day",
        "user_plan_subscriptions",
        "deposit_day_of_month IN (1, 5, 10, 15, 20, 25)",
    )

    # Add next_due_date with a temporary default for existing rows
    op.add_column(
        "user_plan_subscriptions",
        sa.Column(
            "next_due_date",
            sa.Date(),
            nullable=False,
            server_default="2026-03-01",
        ),
    )
    # Remove server default after migration (existing rows get 2026-03-01 = day 1)
    op.alter_column(
        "user_plan_subscriptions",
        "next_due_date",
        server_default=None,
    )
    # Remove server default for deposit_day_of_month (app always provides it)
    op.alter_column(
        "user_plan_subscriptions",
        "deposit_day_of_month",
        server_default=None,
    )

    # Add has_overdue_deposit boolean
    op.add_column(
        "user_plan_subscriptions",
        sa.Column(
            "has_overdue_deposit",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )

    # Add overdue_marked_at timestamp
    op.add_column(
        "user_plan_subscriptions",
        sa.Column(
            "overdue_marked_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # Indexes for dashboard query performance
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


def downgrade() -> None:
    op.drop_index(
        "ix_user_plan_subscriptions_user_overdue_due",
        table_name="user_plan_subscriptions",
    )
    op.drop_index(
        "ix_user_plan_subscriptions_user_due",
        table_name="user_plan_subscriptions",
    )
    op.drop_column("user_plan_subscriptions", "overdue_marked_at")
    op.drop_column("user_plan_subscriptions", "has_overdue_deposit")
    op.drop_column("user_plan_subscriptions", "next_due_date")
    op.drop_constraint(
        "ck_subscriptions_deposit_day",
        "user_plan_subscriptions",
        type_="check",
    )
    op.drop_column("user_plan_subscriptions", "deposit_day_of_month")
