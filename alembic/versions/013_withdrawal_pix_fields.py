"""Add pix_key_type and rejection_reason to transactions.

Revision ID: 013
Revises: 012
Create Date: 2026-03-28
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "013_withdrawal_pix_fields"
down_revision = "012_transaction_subscription_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column("pix_key_type", sa.String(20), nullable=True),
    )
    op.add_column(
        "transactions",
        sa.Column("rejection_reason", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("transactions", "rejection_reason")
    op.drop_column("transactions", "pix_key_type")
