"""Rename clients table to users

Revision ID: 002_rename_clients_to_users
Revises: 001_initial
Create Date: 2026-01-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "002_rename_clients_to_users"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.rename_table("clients", "users")
    # Alembic version in use does not expose rename_index helper; use SQL instead.
    op.execute("ALTER INDEX IF EXISTS ix_clients_cpf RENAME TO ix_users_cpf")
    op.execute("ALTER INDEX IF EXISTS ix_clients_email RENAME TO ix_users_email")


def downgrade() -> None:
    op.execute("ALTER INDEX IF EXISTS ix_users_cpf RENAME TO ix_clients_cpf")
    op.execute("ALTER INDEX IF EXISTS ix_users_email RENAME TO ix_clients_email")
    op.rename_table("users", "clients")
