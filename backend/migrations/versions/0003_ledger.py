"""ledger: strategies, lots, transactions, sell_allocations; seed accounts and strategies

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OWNER = 1  # seeded by 0002

# From CLAUDE.md "My strategies". Momentum lots must have T1 and a stop at entry: both GTTs are
# placed as soon as the buy completes. Descriptive keys are guidance and are not enforced.
MOMENTUM = {
    "account": "zerodha",
    "idea_source": "advisor picks (supertrend + volume)",
    "horizon_months": {"min": 4, "max": 8},
    "review_at_months": 8,
    "required_at_entry": ["T1", "stop"],
    "targets": "T1 and T2; T2 is the full expected move, T1 part of the way",
    "sizing": "about 50% sold at T1, the rest at T2",
    "stop": "GTT trigger set at entry; may exit earlier when the setup weakens",
    "runner": {"status": "unconfirmed", "note": "sometimes ride part after T2 with a GTT band"},
}
LONG_TERM = {
    "account": "groww",
    "stop": None,
    "required_at_entry": ["thesis", "review_trigger"],
}


def upgrade() -> None:
    op.create_table(
        "strategies",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("supersedes_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("status IN ('active', 'superseded')", name=op.f("ck_strategies_status")),
        sa.ForeignKeyConstraint(
            ["supersedes_id"],
            ["strategies.id"],
            name=op.f("fk_strategies_supersedes_id_strategies"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_strategies_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_strategies")),
        sa.UniqueConstraint("user_id", "name", "version", name=op.f("uq_strategies_user_id")),
    )
    op.create_index(op.f("ix_strategies_user_id"), "strategies", ["user_id"])
    op.create_table(
        "lots",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("instrument_id", sa.BigInteger(), nullable=False),
        sa.Column("strategy_id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("opened_on", sa.Date(), nullable=False),
        sa.Column("date_confidence", sa.String(), nullable=False),
        sa.Column("qty_initial", sa.BigInteger(), nullable=False),
        sa.Column("qty_open", sa.BigInteger(), nullable=False),
        sa.Column("avg_cost", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("stop_price", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column(
            "targets",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column("thesis", sa.String(), nullable=True),
        sa.Column("review_trigger", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status = 'closed') = (qty_open = 0)", name=op.f("ck_lots_closed_means_empty")
        ),
        sa.CheckConstraint(
            "date_confidence IN ('exact', 'approximate', 'unknown')",
            name=op.f("ck_lots_date_confidence"),
        ),
        sa.CheckConstraint("status IN ('open', 'closed')", name=op.f("ck_lots_status")),
        sa.CheckConstraint("qty_initial > 0", name=op.f("ck_lots_qty_initial")),
        sa.CheckConstraint("qty_open BETWEEN 0 AND qty_initial", name=op.f("ck_lots_qty_open")),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"], name=op.f("fk_lots_account_id_accounts")
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"], ["instruments.id"], name=op.f("fk_lots_instrument_id_instruments")
        ),
        sa.ForeignKeyConstraint(
            ["strategy_id"], ["strategies.id"], name=op.f("fk_lots_strategy_id_strategies")
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_lots_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lots")),
    )
    op.create_index(op.f("ix_lots_instrument_id"), "lots", ["instrument_id"])
    op.create_index(op.f("ix_lots_user_id"), "lots", ["user_id"])
    op.create_table(
        "transactions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("instrument_id", sa.BigInteger(), nullable=False),
        sa.Column("lot_id", sa.BigInteger(), nullable=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("qty", sa.BigInteger(), nullable=True),
        sa.Column("price", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column(
            "charges",
            sa.Numeric(precision=20, scale=6),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("charges_estimated", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("source_ref", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(kind = 'sell') = (lot_id IS NULL) OR kind = 'charge'",
            name=op.f("ck_transactions_lot"),
        ),
        sa.CheckConstraint(
            "kind IN ('buy', 'sell', 'dividend', 'bonus', 'split', 'charge')",
            name=op.f("ck_transactions_kind"),
        ),
        sa.CheckConstraint(
            "kind NOT IN ('buy', 'sell') OR (COALESCE(qty, 0) > 0 AND COALESCE(price, -1) >= 0)",
            name=op.f("ck_transactions_fill"),
        ),
        sa.CheckConstraint(
            "source IN ('contract_note', 'broker_report', 'sheet', 'screenshot', 'chat', "
            "'opening_balance')",
            name=op.f("ck_transactions_source"),
        ),
        sa.CheckConstraint("charges >= 0", name=op.f("ck_transactions_charges")),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name=op.f("fk_transactions_instrument_id_instruments"),
        ),
        sa.ForeignKeyConstraint(["lot_id"], ["lots.id"], name=op.f("fk_transactions_lot_id_lots")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_transactions_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transactions")),
    )
    op.create_index(op.f("ix_transactions_lot_id"), "transactions", ["lot_id"])
    op.create_index(op.f("ix_transactions_user_id"), "transactions", ["user_id"])
    op.create_table(
        "sell_allocations",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("sell_txn_id", sa.BigInteger(), nullable=False),
        sa.Column("lot_id", sa.BigInteger(), nullable=False),
        sa.Column("qty", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("qty > 0", name=op.f("ck_sell_allocations_qty")),
        sa.ForeignKeyConstraint(
            ["lot_id"], ["lots.id"], name=op.f("fk_sell_allocations_lot_id_lots")
        ),
        sa.ForeignKeyConstraint(
            ["sell_txn_id"],
            ["transactions.id"],
            name=op.f("fk_sell_allocations_sell_txn_id_transactions"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_sell_allocations_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sell_allocations")),
        sa.UniqueConstraint("sell_txn_id", "lot_id", name=op.f("uq_sell_allocations_sell_txn_id")),
    )
    op.create_index(op.f("ix_sell_allocations_lot_id"), "sell_allocations", ["lot_id"])
    op.create_index(op.f("ix_sell_allocations_user_id"), "sell_allocations", ["user_id"])

    accounts = sa.table("accounts", sa.column("user_id"), sa.column("broker"), sa.column("label"))
    op.bulk_insert(
        accounts,
        [
            {"user_id": OWNER, "broker": "zerodha", "label": "Zerodha (momentum)"},
            {"user_id": OWNER, "broker": "groww", "label": "Groww (long-term)"},
        ],
    )
    strategies = sa.table(
        "strategies",
        sa.column("user_id"),
        sa.column("name"),
        sa.column("version"),
        sa.column("config", postgresql.JSONB),
        sa.column("status"),
    )
    op.bulk_insert(
        strategies,
        [
            {
                "user_id": OWNER,
                "name": "momentum",
                "version": 1,
                "config": MOMENTUM,
                "status": "active",
            },
            {
                "user_id": OWNER,
                "name": "long_term",
                "version": 1,
                "config": LONG_TERM,
                "status": "active",
            },
        ],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_sell_allocations_user_id"), table_name="sell_allocations")
    op.drop_index(op.f("ix_sell_allocations_lot_id"), table_name="sell_allocations")
    op.drop_table("sell_allocations")
    op.drop_index(op.f("ix_transactions_user_id"), table_name="transactions")
    op.drop_index(op.f("ix_transactions_lot_id"), table_name="transactions")
    op.drop_table("transactions")
    op.drop_index(op.f("ix_lots_user_id"), table_name="lots")
    op.drop_index(op.f("ix_lots_instrument_id"), table_name="lots")
    op.drop_table("lots")
    op.drop_index(op.f("ix_strategies_user_id"), table_name="strategies")
    op.drop_table("strategies")
    # After lots are gone, since they reference these accounts.
    op.execute(f"DELETE FROM accounts WHERE user_id = {OWNER} AND broker IN ('zerodha', 'groww')")
