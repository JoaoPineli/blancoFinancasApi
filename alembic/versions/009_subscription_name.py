"""Add name column to user_plan_subscriptions

Revision ID: 009_subscription_name
Revises: 008_sub_deposit_due_dates
Create Date: 2026-02-27

Adds a required user-given name for subscriptions.
Existing rows default to 'Plano Poupança'.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "009_subscription_name"
down_revision: Union[str, None] = "008_sub_deposit_due_dates"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_plan_subscriptions",
        sa.Column(
            "name",
            sa.String(120),
            nullable=False,
            server_default="Plano Poupança",
        ),
    )
    # Drop server default; app always provides the value
    op.alter_column(
        "user_plan_subscriptions",
        "name",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_column("user_plan_subscriptions", "name")
