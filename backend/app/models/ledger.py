"""The ledger: strategies, lots, transactions and which lot each sale came from.

Only the staging commit (M3) writes these tables. The P&L math lives in app.ledger.pnl.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Identity, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

STRATEGY_STATUSES = ("active", "superseded")
DATE_CONFIDENCE = ("exact", "approximate", "unknown")
LOT_STATUSES = ("open", "closed")
TXN_KINDS = ("buy", "sell", "dividend", "bonus", "split", "charge")
SOURCES = ("contract_note", "broker_report", "sheet", "screenshot", "chat", "opening_balance")


class Strategy(Base):
    """A versioned description of how I trade. Changing it adds a version, never edits one."""

    __tablename__ = "strategies"
    __table_args__ = (
        UniqueConstraint("user_id", "name", "version"),
        CheckConstraint(f"status IN {STRATEGY_STATUSES}", name="status"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String)
    version: Mapped[int]
    config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String)
    supersedes_id: Mapped[int | None] = mapped_column(ForeignKey("strategies.id"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Lot(Base):
    """One purchase under one strategy. Lots of the same stock are never merged."""

    __tablename__ = "lots"
    __table_args__ = (
        CheckConstraint(f"date_confidence IN {DATE_CONFIDENCE}", name="date_confidence"),
        CheckConstraint(f"status IN {LOT_STATUSES}", name="status"),
        CheckConstraint("qty_initial > 0", name="qty_initial"),
        CheckConstraint("qty_open BETWEEN 0 AND qty_initial", name="qty_open"),
        CheckConstraint("(status = 'closed') = (qty_open = 0)", name="closed_means_empty"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    strategy_id: Mapped[int] = mapped_column(ForeignKey("strategies.id"))
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    # Opening balances use the snapshot date here, with date_confidence = 'unknown'.
    opened_on: Mapped[date]
    date_confidence: Mapped[str] = mapped_column(String)
    qty_initial: Mapped[int]
    qty_open: Mapped[int]
    avg_cost: Mapped[Decimal]
    stop_price: Mapped[Decimal | None]
    # The plan, e.g. [{"label": "T1", "price": "810", "qty": 6}]; prices as strings to stay
    # exact. What actually happened is in the sell transactions.
    targets: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default=text("'[]'"))
    thesis: Mapped[str | None]
    review_trigger: Mapped[str | None]
    remarks: Mapped[str | None]  # free text from the sheet, e.g. "SL Hit"
    status: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint(f"kind IN {TXN_KINDS}", name="kind"),
        CheckConstraint(f"source IN {SOURCES}", name="source"),
        # A sale can draw on several lots, so it names none; sell_allocations does.
        CheckConstraint("(kind = 'sell') = (lot_id IS NULL) OR kind = 'charge'", name="lot"),
        # COALESCE: a NULL would make the check NULL, and Postgres lets NULL checks pass.
        CheckConstraint(
            "kind NOT IN ('buy', 'sell') OR (COALESCE(qty, 0) > 0 AND COALESCE(price, -1) >= 0)",
            name="fill",
        ),
        CheckConstraint("charges >= 0", name="charges"),
        # One row per origin: re-importing a file can never duplicate a buy or a sale.
        UniqueConstraint("user_id", "source", "source_ref"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))
    lot_id: Mapped[int | None] = mapped_column(ForeignKey("lots.id"), index=True)
    kind: Mapped[str] = mapped_column(String)
    trade_date: Mapped[date]
    qty: Mapped[int | None]
    price: Mapped[Decimal | None]
    charges: Mapped[Decimal] = mapped_column(server_default=text("0"))
    charges_estimated: Mapped[bool]
    source: Mapped[str] = mapped_column(String)
    # Where exactly it came from, e.g. "momentum portfolio.xlsx:Sheet1!A3" or a contract note no.
    source_ref: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class SellAllocation(Base):
    """Which lot a sale came from: strategy P&L follows this, not FIFO."""

    __tablename__ = "sell_allocations"
    __table_args__ = (
        UniqueConstraint("sell_txn_id", "lot_id"),
        CheckConstraint("qty > 0", name="qty"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    sell_txn_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"))
    lot_id: Mapped[int] = mapped_column(ForeignKey("lots.id"), index=True)
    qty: Mapped[int]


class CashBalance(Base):
    """Uninvested cash in an account on a date, as I reported it (e.g. Groww's unutilised funds)."""

    __tablename__ = "cash_balances"
    __table_args__ = (UniqueConstraint("account_id", "as_of"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    as_of: Mapped[date]
    amount: Mapped[Decimal]
    source: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
