"""Add pix_qr_code_base64 column to transactions.

Revision ID: 018
Revises: 017_unified_transactions
Create Date: 2026-04-05

Changes
-------
Add optional pix_qr_code_base64 (Text, nullable) to `transactions`.
Populated at payment-creation time from the Mercado Pago gateway response
and surfaced to the frontend for rendering the QR code image.
"""

from alembic import op
import sqlalchemy as sa

revision = "018_pix_qr_code_base64"
down_revision = "017_unified_transactions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column("pix_qr_code_base64", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("transactions", "pix_qr_code_base64")
