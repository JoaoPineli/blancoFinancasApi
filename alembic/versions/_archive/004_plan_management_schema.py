"""Redesign plans table for admin plan management

Revision ID: 004_plan_management_schema
Revises: 003_user_invitation_system
Create Date: 2026-01-28

This migration updates the plans table to support the new admin plan management feature.
The schema changes include:
- Renaming 'name' to 'title'
- Adding value range constraints (min_value_cents, max_value_cents)
- Adding duration range constraints (min_duration_months, max_duration_months)
- Adding first installment parameters (admin_tax, insurance, guarantee fund tiers)
- Removing deprecated columns (plan_type, monthly_installment_cents, fundo_garantidor_percentage)

IMPORTANT: This migration is destructive for existing data. In production,
a data migration step would be required to preserve existing plan data.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "004_plan_management_schema"
down_revision: Union[str, None] = "003_user_invitation_system"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rename 'name' column to 'title'
    op.alter_column("plans", "name", new_column_name="title")

    # Remove deprecated columns
    op.drop_column("plans", "plan_type")
    op.drop_column("plans", "monthly_installment_cents")

    # Rename existing fundo_garantidor_percentage to duration_months temporarily
    # and add new columns
    op.drop_column("plans", "fundo_garantidor_percentage")
    op.drop_column("plans", "duration_months")

    # Add new constraint columns
    op.add_column(
        "plans",
        sa.Column("min_value_cents", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "plans",
        sa.Column("max_value_cents", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "plans",
        sa.Column("min_duration_months", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "plans",
        sa.Column("max_duration_months", sa.Integer(), nullable=False, server_default="12"),
    )

    # Add first installment parameter columns
    op.add_column(
        "plans",
        sa.Column("admin_tax_value_cents", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "plans",
        sa.Column("insurance_percent", sa.Numeric(5, 2), nullable=False, server_default="0"),
    )
    op.add_column(
        "plans",
        sa.Column("guarantee_fund_percent_1", sa.Numeric(5, 2), nullable=False, server_default="0"),
    )
    op.add_column(
        "plans",
        sa.Column("guarantee_fund_percent_2", sa.Numeric(5, 2), nullable=False, server_default="0"),
    )
    op.add_column(
        "plans",
        sa.Column("guarantee_fund_threshold_cents", sa.BigInteger(), nullable=False, server_default="0"),
    )

    # Remove server defaults after column creation (they were only for migration)
    op.alter_column("plans", "min_value_cents", server_default=None)
    op.alter_column("plans", "max_value_cents", server_default=None)
    op.alter_column("plans", "min_duration_months", server_default=None)
    op.alter_column("plans", "max_duration_months", server_default=None)
    op.alter_column("plans", "admin_tax_value_cents", server_default=None)
    op.alter_column("plans", "insurance_percent", server_default=None)
    op.alter_column("plans", "guarantee_fund_percent_1", server_default=None)
    op.alter_column("plans", "guarantee_fund_percent_2", server_default=None)
    op.alter_column("plans", "guarantee_fund_threshold_cents", server_default=None)

    # Add index for title search
    op.create_index("ix_plans_title", "plans", ["title"])


def downgrade() -> None:
    # Remove new index
    op.drop_index("ix_plans_title")

    # Remove new columns
    op.drop_column("plans", "guarantee_fund_threshold_cents")
    op.drop_column("plans", "guarantee_fund_percent_2")
    op.drop_column("plans", "guarantee_fund_percent_1")
    op.drop_column("plans", "insurance_percent")
    op.drop_column("plans", "admin_tax_value_cents")
    op.drop_column("plans", "max_duration_months")
    op.drop_column("plans", "min_duration_months")
    op.drop_column("plans", "max_value_cents")
    op.drop_column("plans", "min_value_cents")

    # Restore original columns
    op.add_column(
        "plans",
        sa.Column("duration_months", sa.Integer(), nullable=False, server_default="12"),
    )
    op.add_column(
        "plans",
        sa.Column(
            "fundo_garantidor_percentage",
            sa.Numeric(5, 2),
            nullable=False,
            server_default="1.0",
        ),
    )
    op.add_column(
        "plans",
        sa.Column(
            "monthly_installment_cents",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "plans",
        sa.Column("plan_type", sa.String(30), nullable=False, server_default="geral"),
    )

    # Rename 'title' back to 'name'
    op.alter_column("plans", "title", new_column_name="name")
