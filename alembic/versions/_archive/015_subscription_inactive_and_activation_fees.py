"""Add inactive subscription support and activation fees flag.

Revision ID: 015
Revises: 014
Create Date: 2026-03-28
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "015_sub_inactive"
down_revision = "014_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("user_plan_subscriptions", "next_due_date", nullable=True)
    op.add_column(
        "user_plan_subscriptions",
        sa.Column(
            "covers_activation_fees",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    op.drop_column("user_plan_subscriptions", "covers_activation_fees")
    op.alter_column("user_plan_subscriptions", "next_due_date", nullable=False)
