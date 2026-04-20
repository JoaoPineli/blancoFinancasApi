"""Add deleted_at column to plans table for soft delete

Revision ID: 006_plan_soft_delete
Revises: 005_nullable_max_plan_values
Create Date: 2026-01-29

This migration adds a deleted_at column to the plans table to support soft delete.
When a plan is deleted, instead of removing the row, the deleted_at timestamp is populated.
Plans with a non-null deleted_at are excluded from listing endpoints.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "006_plan_soft_delete"
down_revision: Union[str, None] = "005_nullable_max_plan_values"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add deleted_at column for soft delete
    op.add_column(
        "plans",
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )

    # Add index for filtering non-deleted plans
    op.create_index("ix_plans_deleted_at", "plans", ["deleted_at"])


def downgrade() -> None:
    # Remove index
    op.drop_index("ix_plans_deleted_at", table_name="plans")

    # Remove deleted_at column
    op.drop_column("plans", "deleted_at")
