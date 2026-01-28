"""Add user_tokens table and update users table

Revision ID: 003_user_invitation_system
Revises: 002_rename_clients_to_users
Create Date: 2026-01-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "003_user_invitation_system"
down_revision: Union[str, None] = "002_rename_clients_to_users"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add nullable columns to users table for invitation system
    # nickname - optional display name
    op.add_column(
        "users",
        sa.Column("nickname", sa.String(100), nullable=True),
    )

    # plan_id - optional foreign key to plans table for pre-assigned plan
    op.add_column(
        "users",
        sa.Column(
            "plan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("plans.id"),
            nullable=True,
        ),
    )
    op.create_index("ix_users_plan_id", "users", ["plan_id"])

    # Make cpf nullable (invited users don't have CPF yet)
    op.alter_column("users", "cpf", nullable=True)

    # Make password_hash nullable (invited users don't have password yet)
    op.alter_column("users", "password_hash", nullable=True)

    # Drop the unique constraint on cpf and recreate it as a partial unique index
    # This allows NULL values while still enforcing uniqueness for non-NULL values
    op.drop_index("ix_users_cpf")
    op.execute(
        "CREATE UNIQUE INDEX ix_users_cpf ON users (cpf) WHERE cpf IS NOT NULL"
    )

    # Create user_tokens table for activation and password reset tokens
    op.create_table(
        "user_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(255), nullable=False),
        sa.Column("token_type", sa.String(20), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_tokens_user_id", "user_tokens", ["user_id"])
    op.create_index("ix_user_tokens_token_hash", "user_tokens", ["token_hash"])
    op.create_index(
        "ix_user_tokens_user_type", "user_tokens", ["user_id", "token_type"]
    )


def downgrade() -> None:
    # Drop user_tokens table
    op.drop_index("ix_user_tokens_user_type")
    op.drop_index("ix_user_tokens_token_hash")
    op.drop_index("ix_user_tokens_user_id")
    op.drop_table("user_tokens")

    # Restore cpf unique index (will fail if NULL values exist)
    op.drop_index("ix_users_cpf")
    op.create_index("ix_users_cpf", "users", ["cpf"], unique=True)

    # Make password_hash non-nullable (will fail if NULL values exist)
    op.alter_column("users", "password_hash", nullable=False)

    # Make cpf non-nullable (will fail if NULL values exist)
    op.alter_column("users", "cpf", nullable=False)

    # Drop plan_id column
    op.drop_index("ix_users_plan_id")
    op.drop_column("users", "plan_id")

    # Drop nickname column
    op.drop_column("users", "nickname")
