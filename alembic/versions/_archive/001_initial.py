"""Initial migration - Create all tables

Revision ID: 001_initial
Revises: 
Create Date: 2026-01-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create clients table
    op.create_table(
        'clients',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('cpf', sa.String(11), nullable=False),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('role', sa.String(20), nullable=False, server_default='client'),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.Column('phone', sa.String(20), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_clients_cpf', 'clients', ['cpf'], unique=True)
    op.create_index('ix_clients_email', 'clients', ['email'], unique=True)

    # Create plans table
    op.create_table(
        'plans',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('plan_type', sa.String(30), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('monthly_installment_cents', sa.BigInteger(), nullable=False),
        sa.Column('duration_months', sa.Integer(), nullable=False),
        sa.Column('fundo_garantidor_percentage', sa.Numeric(5, 2), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    # Create contracts table
    op.create_table(
        'contracts',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('plan_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('pdf_storage_path', sa.String(500), nullable=True),
        sa.Column('accepted_at', sa.DateTime(), nullable=True),
        sa.Column('start_date', sa.DateTime(), nullable=True),
        sa.Column('end_date', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['clients.id']),
        sa.ForeignKeyConstraint(['plan_id'], ['plans.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_contracts_user_id', 'contracts', ['id'])
    op.create_index('ix_contracts_plan_id', 'contracts', ['plan_id'])

    # Create wallets table
    op.create_table(
        'wallets',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('balance_cents', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('total_invested_cents', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('total_yield_cents', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('fundo_garantidor_cents', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['clients.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id')
    )

    # Create transactions table
    op.create_table(
        'transactions',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('contract_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('transaction_type', sa.String(30), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('amount_cents', sa.BigInteger(), nullable=False),
        sa.Column('installment_number', sa.Integer(), nullable=True),
        sa.Column('installment_type', sa.String(20), nullable=True),
        sa.Column('pix_key', sa.String(100), nullable=True),
        sa.Column('pix_transaction_id', sa.String(100), nullable=True),
        sa.Column('bank_account', sa.String(100), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('confirmed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['clients.id']),
        sa.ForeignKeyConstraint(['contract_id'], ['contracts.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_transactions_user_id', 'transactions', ['user_id'])
    op.create_index('ix_transactions_contract_id', 'transactions', ['contract_id'])
    op.create_index('ix_transactions_transaction_type', 'transactions', ['transaction_type'])
    op.create_index('ix_transactions_status', 'transactions', ['status'])
    op.create_index(
        'ix_transactions_client_type_status',
        'transactions',
        ['user_id', 'transaction_type', 'status']
    )

    # Create audit_logs table
    op.create_table(
        'audit_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('action', sa.String(50), nullable=False),
        sa.Column('actor_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('target_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('target_type', sa.String(50), nullable=True),
        sa.Column('details', postgresql.JSON(), nullable=False, server_default='{}'),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_audit_logs_action', 'audit_logs', ['action'])
    op.create_index('ix_audit_logs_actor_id', 'audit_logs', ['actor_id'])
    op.create_index('ix_audit_logs_created_at', 'audit_logs', ['created_at'])

    # Create yield_data table
    op.create_table(
        'yield_data',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('series_id', sa.Integer(), nullable=False),
        sa.Column('reference_date', sa.DateTime(), nullable=False),
        sa.Column('rate', sa.Numeric(12, 8), nullable=False),
        sa.Column('fetched_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('series_id', 'reference_date', name='uq_yield_data_series_date')
    )
    op.create_index('ix_yield_data_series_date', 'yield_data', ['series_id', 'reference_date'])


def downgrade() -> None:
    op.drop_table('yield_data')
    op.drop_table('audit_logs')
    op.drop_table('transactions')
    op.drop_table('wallets')
    op.drop_table('contracts')
    op.drop_table('plans')
    op.drop_table('clients')
