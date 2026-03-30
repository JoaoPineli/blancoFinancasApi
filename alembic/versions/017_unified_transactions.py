"""Unify payments into transactions + transaction_items.

Revision ID: 017
Revises: 016_activation_payments
Create Date: 2026-03-29

Changes
-------
1. Add payment-flow columns to `transactions`
   (pix_qr_code_data, expiration_minutes, pix_transaction_fee_cents,
    admin_tax_cents, insurance_cents, transaction_type widened to 50 chars)
2. Create `transaction_items` table
3. Backfill: installment_payments → transactions (type=subscription_installment_payment)
             installment_payment_items → transaction_items
             subscription_activation_payments → transactions (type=subscription_activation_payment) + transaction_items
4. Add `transaction_item_id` FK to `principal_deposits`; backfill from installment_payment_item_id
5. Drop old tables (installment_payments, installment_payment_items,
                    subscription_activation_payments)
6. Remove legacy `installment_payment_item_id` column from principal_deposits

Downgrade restores the old schema from the data that was preserved in transactions.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "017_unified_transactions"
down_revision = "016_activation_payments"
branch_labels = None
depends_on = None

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

INSTALLMENT_TYPE = "subscription_installment_payment"
ACTIVATION_TYPE = "subscription_activation_payment"


def _conn():
    return op.get_bind()


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    conn = _conn()

    # -----------------------------------------------------------------------
    # 1. Widen transaction_type column and add new payment-flow columns
    # -----------------------------------------------------------------------
    op.alter_column(
        "transactions",
        "transaction_type",
        type_=sa.String(50),
        existing_type=sa.String(30),
        existing_nullable=False,
    )
    op.add_column(
        "transactions",
        sa.Column("pix_qr_code_data", sa.Text(), nullable=True),
    )
    op.add_column(
        "transactions",
        sa.Column("expiration_minutes", sa.Integer(), nullable=True),
    )
    op.add_column(
        "transactions",
        sa.Column(
            "pix_transaction_fee_cents",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "transactions",
        sa.Column("admin_tax_cents", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "transactions",
        sa.Column("insurance_cents", sa.BigInteger(), nullable=True),
    )

    # -----------------------------------------------------------------------
    # 2. Create transaction_items
    # -----------------------------------------------------------------------
    op.create_table(
        "transaction_items",
        sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
        sa.Column(
            "transaction_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("transactions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "subscription_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("user_plan_subscriptions.id"),
            nullable=False,
        ),
        sa.Column("subscription_name", sa.String(120), nullable=False, server_default=""),
        sa.Column("plan_title", sa.String(100), nullable=False, server_default=""),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("installment_number", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_transaction_items_transaction_id",
        "transaction_items",
        ["transaction_id"],
    )
    op.create_index(
        "ix_transaction_items_subscription_id",
        "transaction_items",
        ["subscription_id"],
    )
    op.create_index(
        "ix_transaction_items_sub_transaction",
        "transaction_items",
        ["subscription_id", "transaction_id"],
    )

    # -----------------------------------------------------------------------
    # 3a. Backfill: installment_payments → transactions
    # -----------------------------------------------------------------------
    conn.execute(sa.text("""
        INSERT INTO transactions (
            id, user_id, contract_id, subscription_id,
            transaction_type, status, amount_cents,
            installment_number, installment_type,
            pix_key, pix_key_type, pix_transaction_id,
            bank_account, description, rejection_reason,
            created_at, updated_at, confirmed_at,
            pix_qr_code_data, expiration_minutes,
            pix_transaction_fee_cents,
            admin_tax_cents, insurance_cents
        )
        SELECT
            ip.id,
            ip.user_id,
            NULL,              -- contract_id
            NULL,              -- subscription_id (group payment, no single sub)
            :type_installment,
            ip.status,
            ip.total_amount_cents,
            NULL,              -- installment_number (at tx level)
            NULL,              -- installment_type
            NULL,              -- pix_key
            NULL,              -- pix_key_type
            ip.pix_transaction_id,
            NULL,              -- bank_account
            NULL,              -- description
            NULL,              -- rejection_reason
            ip.created_at,
            ip.updated_at,
            ip.confirmed_at,
            ip.pix_qr_code_data,
            ip.expiration_minutes,
            ip.pix_transaction_fee_cents,
            NULL,              -- admin_tax_cents
            NULL               -- insurance_cents
        FROM installment_payments ip
        ON CONFLICT (id) DO NOTHING
    """), {"type_installment": INSTALLMENT_TYPE})

    # -----------------------------------------------------------------------
    # 3b. Backfill: installment_payment_items → transaction_items
    # -----------------------------------------------------------------------
    conn.execute(sa.text("""
        INSERT INTO transaction_items (
            id, transaction_id, subscription_id,
            subscription_name, plan_title,
            amount_cents, installment_number
        )
        SELECT
            ipi.id,
            ipi.payment_id,        -- maps to transactions.id (backfilled above)
            ipi.subscription_id,
            COALESCE(ipi.subscription_name, ''),
            COALESCE(ipi.plan_title, ''),
            ipi.amount_cents,
            ipi.installment_number
        FROM installment_payment_items ipi
        ON CONFLICT (id) DO NOTHING
    """))

    # -----------------------------------------------------------------------
    # 3c. Backfill: subscription_activation_payments → transactions
    # -----------------------------------------------------------------------
    conn.execute(sa.text("""
        INSERT INTO transactions (
            id, user_id, contract_id, subscription_id,
            transaction_type, status, amount_cents,
            installment_number, installment_type,
            pix_key, pix_key_type, pix_transaction_id,
            bank_account, description, rejection_reason,
            created_at, updated_at, confirmed_at,
            pix_qr_code_data, expiration_minutes,
            pix_transaction_fee_cents,
            admin_tax_cents, insurance_cents
        )
        SELECT
            ap.id,
            ap.user_id,
            NULL,              -- contract_id
            ap.subscription_id,
            :type_activation,
            ap.status,
            ap.total_amount_cents,
            NULL,              -- installment_number
            NULL,              -- installment_type
            NULL,              -- pix_key
            NULL,              -- pix_key_type
            ap.pix_transaction_id,
            NULL,              -- bank_account
            NULL,              -- description
            NULL,              -- rejection_reason
            ap.created_at,
            ap.updated_at,
            ap.confirmed_at,
            ap.pix_qr_code_data,
            ap.expiration_minutes,
            ap.pix_transaction_fee_cents,
            ap.admin_tax_cents,
            ap.insurance_cents
        FROM subscription_activation_payments ap
        ON CONFLICT (id) DO NOTHING
    """), {"type_activation": ACTIVATION_TYPE})

    # -----------------------------------------------------------------------
    # 3d. Create one transaction_item per activation payment
    #     (links the transaction to its subscription with the full amount)
    # -----------------------------------------------------------------------
    conn.execute(sa.text("""
        INSERT INTO transaction_items (
            id, transaction_id, subscription_id,
            subscription_name, plan_title,
            amount_cents, installment_number
        )
        SELECT
            gen_random_uuid(),
            ap.id,             -- transaction_id = activation payment id
            ap.subscription_id,
            COALESCE(ups.name, p.title, ''),
            COALESCE(p.title, ''),
            ap.total_amount_cents,
            NULL               -- activation has no installment number
        FROM subscription_activation_payments ap
        LEFT JOIN user_plan_subscriptions ups ON ups.id = ap.subscription_id
        LEFT JOIN plans p ON p.id = ups.plan_id
    """))

    # -----------------------------------------------------------------------
    # 4. Add transaction_item_id column to principal_deposits
    # -----------------------------------------------------------------------
    op.add_column(
        "principal_deposits",
        sa.Column(
            "transaction_item_id",
            PGUUID(as_uuid=True),
            nullable=True,  # nullable temporarily during backfill
        ),
    )
    op.create_index(
        "ix_principal_deposits_transaction_item_id",
        "principal_deposits",
        ["transaction_item_id"],
    )

    # Backfill: installment_payment_item_id is the same UUID as transaction_item.id
    conn.execute(sa.text("""
        UPDATE principal_deposits pd
        SET transaction_item_id = pd.installment_payment_item_id
        WHERE pd.installment_payment_item_id IS NOT NULL
    """))

    # Make non-nullable now that backfill is done
    op.alter_column(
        "principal_deposits",
        "transaction_item_id",
        nullable=False,
        existing_type=PGUUID(as_uuid=True),
    )

    # Add UNIQUE constraint
    op.create_unique_constraint(
        "uq_principal_deposits_transaction_item_id",
        "principal_deposits",
        ["transaction_item_id"],
    )

    # Add FK (after the unique constraint)
    op.create_foreign_key(
        "fk_principal_deposits_transaction_item_id",
        "principal_deposits",
        "transaction_items",
        ["transaction_item_id"],
        ["id"],
    )

    # -----------------------------------------------------------------------
    # 5. Drop old tables
    # -----------------------------------------------------------------------
    # Drop FK from principal_deposits to installment_payment_items first
    op.drop_constraint(
        "principal_deposits_installment_payment_item_id_fkey",
        "principal_deposits",
        type_="foreignkey",
    )
    op.drop_column("principal_deposits", "installment_payment_item_id")

    # Drop installment_payment_items (FK to installment_payments; cascade)
    op.drop_index(
        "ix_installment_payment_items_subscription_id",
        table_name="installment_payment_items",
    )
    op.drop_index(
        "ix_installment_payment_items_payment_id",
        table_name="installment_payment_items",
    )
    op.drop_table("installment_payment_items")

    # Drop installment_payments
    op.drop_index("ix_installment_payments_user_status", table_name="installment_payments")
    op.drop_index("ix_installment_payments_user_id", table_name="installment_payments")
    op.drop_index("ix_installment_payments_status", table_name="installment_payments")
    op.drop_index(
        "ix_installment_payments_pix_transaction_id", table_name="installment_payments"
    )
    op.drop_table("installment_payments")

    # Drop subscription_activation_payments
    op.drop_index(
        "ix_subscription_activation_payments_user_id",
        table_name="subscription_activation_payments",
    )
    op.drop_index(
        "ix_subscription_activation_payments_subscription_id",
        table_name="subscription_activation_payments",
    )
    op.drop_index(
        "ix_subscription_activation_payments_status",
        table_name="subscription_activation_payments",
    )
    op.drop_index(
        "ix_subscription_activation_payments_pix_transaction_id",
        table_name="subscription_activation_payments",
    )
    op.drop_index(
        "ix_subscription_activation_payments_user_status",
        table_name="subscription_activation_payments",
    )
    op.drop_index(
        "ix_subscription_activation_payments_sub_id",
        table_name="subscription_activation_payments",
    )
    op.drop_table("subscription_activation_payments")

    # Add indexes on transactions for the new types
    op.create_index(
        "ix_transactions_user_type_status",
        "transactions",
        ["user_id", "transaction_type", "status"],
    )


# ---------------------------------------------------------------------------
# Downgrade — restores old tables from unified transactions data
# ---------------------------------------------------------------------------


def downgrade() -> None:
    conn = _conn()

    # Remove the new transaction_type index
    op.drop_index("ix_transactions_user_type_status", table_name="transactions")

    # -----------------------------------------------------------------------
    # Restore installment_payments
    # -----------------------------------------------------------------------
    op.create_table(
        "installment_payments",
        sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", PGUUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("total_amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("pix_qr_code_data", sa.Text(), nullable=True),
        sa.Column("pix_transaction_id", sa.String(100), nullable=True),
        sa.Column("expiration_minutes", sa.Integer(), nullable=False, server_default="30"),
        sa.Column(
            "pix_transaction_fee_cents",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_installment_payments_user_status", "installment_payments", ["user_id", "status"])
    op.create_index("ix_installment_payments_user_id", "installment_payments", ["user_id"])
    op.create_index("ix_installment_payments_status", "installment_payments", ["status"])
    op.create_index("ix_installment_payments_pix_transaction_id", "installment_payments", ["pix_transaction_id"])

    conn.execute(sa.text("""
        INSERT INTO installment_payments (
            id, user_id, status, total_amount_cents,
            pix_qr_code_data, pix_transaction_id, expiration_minutes,
            pix_transaction_fee_cents, created_at, updated_at, confirmed_at
        )
        SELECT
            t.id, t.user_id, t.status, t.amount_cents,
            t.pix_qr_code_data, t.pix_transaction_id,
            COALESCE(t.expiration_minutes, 30),
            t.pix_transaction_fee_cents,
            t.created_at, t.updated_at, t.confirmed_at
        FROM transactions t
        WHERE t.transaction_type = :type_installment
    """), {"type_installment": INSTALLMENT_TYPE})

    # -----------------------------------------------------------------------
    # Restore installment_payment_items
    # -----------------------------------------------------------------------
    op.create_table(
        "installment_payment_items",
        sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
        sa.Column(
            "payment_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("installment_payments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "subscription_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("user_plan_subscriptions.id"),
            nullable=False,
        ),
        sa.Column("subscription_name", sa.String(120), nullable=False, server_default=""),
        sa.Column("plan_title", sa.String(100), nullable=False, server_default=""),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("installment_number", sa.Integer(), nullable=True),
    )
    op.create_index("ix_installment_payment_items_payment_id", "installment_payment_items", ["payment_id"])
    op.create_index("ix_installment_payment_items_subscription_id", "installment_payment_items", ["subscription_id"])

    conn.execute(sa.text("""
        INSERT INTO installment_payment_items (
            id, payment_id, subscription_id, subscription_name,
            plan_title, amount_cents, installment_number
        )
        SELECT
            ti.id, ti.transaction_id, ti.subscription_id,
            ti.subscription_name, ti.plan_title,
            ti.amount_cents, ti.installment_number
        FROM transaction_items ti
        JOIN transactions t ON t.id = ti.transaction_id
        WHERE t.transaction_type = :type_installment
    """), {"type_installment": INSTALLMENT_TYPE})

    # -----------------------------------------------------------------------
    # Restore subscription_activation_payments
    # -----------------------------------------------------------------------
    op.create_table(
        "subscription_activation_payments",
        sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", PGUUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "subscription_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("user_plan_subscriptions.id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("admin_tax_cents", sa.BigInteger(), nullable=False),
        sa.Column("insurance_cents", sa.BigInteger(), nullable=False),
        sa.Column("pix_transaction_fee_cents", sa.BigInteger(), nullable=False),
        sa.Column("total_amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("pix_qr_code_data", sa.Text(), nullable=True),
        sa.Column("pix_transaction_id", sa.String(100), nullable=True, unique=True),
        sa.Column("expiration_minutes", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_subscription_activation_payments_user_id", "subscription_activation_payments", ["user_id"])
    op.create_index("ix_subscription_activation_payments_subscription_id", "subscription_activation_payments", ["subscription_id"])
    op.create_index("ix_subscription_activation_payments_status", "subscription_activation_payments", ["status"])
    op.create_index("ix_subscription_activation_payments_pix_transaction_id", "subscription_activation_payments", ["pix_transaction_id"])
    op.create_index("ix_subscription_activation_payments_user_status", "subscription_activation_payments", ["user_id", "status"])
    op.create_index("ix_subscription_activation_payments_sub_id", "subscription_activation_payments", ["subscription_id"])

    conn.execute(sa.text("""
        INSERT INTO subscription_activation_payments (
            id, user_id, subscription_id, status,
            admin_tax_cents, insurance_cents, pix_transaction_fee_cents,
            total_amount_cents, pix_qr_code_data, pix_transaction_id,
            expiration_minutes, created_at, updated_at, confirmed_at
        )
        SELECT
            t.id, t.user_id, t.subscription_id, t.status,
            COALESCE(t.admin_tax_cents, 0),
            COALESCE(t.insurance_cents, 0),
            t.pix_transaction_fee_cents,
            t.amount_cents,
            t.pix_qr_code_data, t.pix_transaction_id,
            COALESCE(t.expiration_minutes, 30),
            t.created_at, t.updated_at, t.confirmed_at
        FROM transactions t
        WHERE t.transaction_type = :type_activation
    """), {"type_activation": ACTIVATION_TYPE})

    # -----------------------------------------------------------------------
    # Restore principal_deposits.installment_payment_item_id
    # -----------------------------------------------------------------------
    op.add_column(
        "principal_deposits",
        sa.Column(
            "installment_payment_item_id",
            PGUUID(as_uuid=True),
            nullable=True,
        ),
    )
    conn.execute(sa.text("""
        UPDATE principal_deposits pd
        SET installment_payment_item_id = pd.transaction_item_id
    """))
    op.alter_column(
        "principal_deposits",
        "installment_payment_item_id",
        nullable=False,
        existing_type=PGUUID(as_uuid=True),
    )
    op.create_unique_constraint(
        "uq_principal_deposits_installment_payment_item_id",
        "principal_deposits",
        ["installment_payment_item_id"],
    )
    op.create_foreign_key(
        "principal_deposits_installment_payment_item_id_fkey",
        "principal_deposits",
        "installment_payment_items",
        ["installment_payment_item_id"],
        ["id"],
    )

    # Drop new FK/column on principal_deposits
    op.drop_constraint(
        "fk_principal_deposits_transaction_item_id",
        "principal_deposits",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_principal_deposits_transaction_item_id",
        "principal_deposits",
        type_="unique",
    )
    op.drop_index("ix_principal_deposits_transaction_item_id", table_name="principal_deposits")
    op.drop_column("principal_deposits", "transaction_item_id")

    # Drop transaction_items
    op.drop_index("ix_transaction_items_sub_transaction", table_name="transaction_items")
    op.drop_index("ix_transaction_items_subscription_id", table_name="transaction_items")
    op.drop_index("ix_transaction_items_transaction_id", table_name="transaction_items")
    op.drop_table("transaction_items")

    # Remove new columns from transactions
    op.drop_column("transactions", "insurance_cents")
    op.drop_column("transactions", "admin_tax_cents")
    op.drop_column("transactions", "pix_transaction_fee_cents")
    op.drop_column("transactions", "expiration_minutes")
    op.drop_column("transactions", "pix_qr_code_data")

    # Narrow back transaction_type
    # Remove unified rows from transactions
    conn.execute(sa.text("""
        DELETE FROM transactions
        WHERE transaction_type IN (:type_installment, :type_activation)
    """), {"type_installment": INSTALLMENT_TYPE, "type_activation": ACTIVATION_TYPE})

    op.alter_column(
        "transactions",
        "transaction_type",
        type_=sa.String(30),
        existing_type=sa.String(50),
        existing_nullable=False,
    )
