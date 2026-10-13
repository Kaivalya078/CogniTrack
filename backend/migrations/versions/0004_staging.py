"""staging_batches, staging_items, cash_balances; lots.remarks; one transaction per origin

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "staging_batches",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("importer", sa.String(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("sha256", sa.String(), nullable=False),
        sa.Column("status", sa.String(), server_default="pending", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'committed', 'discarded')",
            name=op.f("ck_staging_batches_status"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_staging_batches_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_staging_batches")),
    )
    op.create_index(op.f("ix_staging_batches_user_id"), "staging_batches", ["user_id"])
    op.create_table(
        "cash_balances",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"], name=op.f("fk_cash_balances_account_id_accounts")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_cash_balances_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cash_balances")),
        sa.UniqueConstraint("account_id", "as_of", name=op.f("uq_cash_balances_account_id")),
    )
    op.create_index(op.f("ix_cash_balances_user_id"), "cash_balances", ["user_id"])
    op.create_table(
        "staging_items",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("batch_id", sa.BigInteger(), nullable=False),
        sa.Column("row_ref", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("instrument_id", sa.BigInteger(), nullable=True),
        sa.Column("lot_id", sa.BigInteger(), nullable=True),
        sa.Column("match_status", sa.String(), nullable=False),
        sa.Column(
            "diff",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column(
            "needs_input",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column(
            "warnings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column("status", sa.String(), server_default="pending", nullable=False),
        sa.CheckConstraint("kind IN ('lot', 'cash')", name=op.f("ck_staging_items_kind")),
        sa.CheckConstraint(
            "match_status IN ('new', 'unchanged', 'changed', 'conflict')",
            name=op.f("ck_staging_items_match_status"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'skipped', 'committed')", name=op.f("ck_staging_items_status")
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["staging_batches.id"],
            name=op.f("fk_staging_items_batch_id_staging_batches"),
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name=op.f("fk_staging_items_instrument_id_instruments"),
        ),
        sa.ForeignKeyConstraint(["lot_id"], ["lots.id"], name=op.f("fk_staging_items_lot_id_lots")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_staging_items_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_staging_items")),
    )
    op.create_index(op.f("ix_staging_items_batch_id"), "staging_items", ["batch_id"])
    op.create_index(op.f("ix_staging_items_user_id"), "staging_items", ["user_id"])
    op.add_column("lots", sa.Column("remarks", sa.String(), nullable=True))
    op.create_unique_constraint(
        op.f("uq_transactions_user_id"), "transactions", ["user_id", "source", "source_ref"]
    )


def downgrade() -> None:
    op.drop_constraint(op.f("uq_transactions_user_id"), "transactions", type_="unique")
    op.drop_column("lots", "remarks")
    op.drop_index(op.f("ix_staging_items_user_id"), table_name="staging_items")
    op.drop_index(op.f("ix_staging_items_batch_id"), table_name="staging_items")
    op.drop_table("staging_items")
    op.drop_index(op.f("ix_cash_balances_user_id"), table_name="cash_balances")
    op.drop_table("cash_balances")
    op.drop_index(op.f("ix_staging_batches_user_id"), table_name="staging_batches")
    op.drop_table("staging_batches")
