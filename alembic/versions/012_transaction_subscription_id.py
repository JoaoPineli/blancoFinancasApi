"""Add subscription_id to transactions for yield traceability.
Revision ID: 012_transaction_subscription_id
Revises: 011_principal_deposits
Create Date: 2026-03-18
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "012_transaction_subscription_id"
down_revision = "011_principal_deposits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column(
            "subscription_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_plan_subscriptions.id"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_transactions_subscription_id",
        "transactions",
        ["subscription_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_transactions_subscription_id", table_name="transactions")
    op.drop_column("transactions", "subscription_id")
