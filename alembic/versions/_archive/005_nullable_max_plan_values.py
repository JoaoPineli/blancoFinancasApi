"""Make max_value_cents and max_duration_months nullable for indefinite plans.

Revision ID: 005_nullable_max_plan_values
Revises: 004_plan_management_schema
Create Date: 2026-01-28

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "005_nullable_max_plan_values"
down_revision: Union[str, None] = "004_plan_management_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Make max_value_cents and max_duration_months nullable.
    
    This allows plans to have indefinite maximum values (null = no limit).
    """
    # Make max_value_cents nullable
    op.alter_column(
        "plans",
        "max_value_cents",
        existing_type=sa.BigInteger(),
        nullable=True,
    )
    
    # Make max_duration_months nullable
    op.alter_column(
        "plans",
        "max_duration_months",
        existing_type=sa.Integer(),
        nullable=True,
    )


def downgrade() -> None:
    """Revert max_value_cents and max_duration_months to non-nullable.
    
    WARNING: This will fail if any existing plans have null values.
    Consider updating null values to a default before downgrading.
    """
    # Make max_value_cents non-nullable
    op.alter_column(
        "plans",
        "max_value_cents",
        existing_type=sa.BigInteger(),
        nullable=False,
    )
    
    # Make max_duration_months non-nullable
    op.alter_column(
        "plans",
        "max_duration_months",
        existing_type=sa.Integer(),
        nullable=False,
    )
