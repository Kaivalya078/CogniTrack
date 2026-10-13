"""Staging: what an import proposes, before I confirm it. Nothing here is the record.

An item's payload is the proposed lot (its buys, exits and planned targets) or a cash balance.
Edits on the staging page change the payload; app.ingest.staging re-checks it after every edit.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Identity, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

BATCH_STATUSES = ("pending", "committed", "discarded")
ITEM_KINDS = ("lot", "cash")
MATCH_STATUSES = ("new", "unchanged", "changed", "conflict")
ITEM_STATUSES = ("pending", "skipped", "committed")


class StagingBatch(Base):
    __tablename__ = "staging_batches"
    __table_args__ = (CheckConstraint(f"status IN {BATCH_STATUSES}", name="status"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    importer: Mapped[str] = mapped_column(String)
    filename: Mapped[str] = mapped_column(String)
    sha256: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, server_default="pending")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    committed_at: Mapped[datetime | None]


class StagingItem(Base):
    __tablename__ = "staging_items"
    __table_args__ = (
        CheckConstraint(f"kind IN {ITEM_KINDS}", name="kind"),
        CheckConstraint(f"match_status IN {MATCH_STATUSES}", name="match_status"),
        CheckConstraint(f"status IN {ITEM_STATUSES}", name="status"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("staging_batches.id"), index=True)
    row_ref: Mapped[str] = mapped_column(String)  # where in the file, e.g. "Sheet1!A3"
    kind: Mapped[str] = mapped_column(String)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instruments.id"))
    lot_id: Mapped[int | None] = mapped_column(ForeignKey("lots.id"))  # the lot it matched
    match_status: Mapped[str] = mapped_column(String)
    # Lists of short human-readable strings, shown as they are on the staging page.
    diff: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'"))
    needs_input: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'"))
    warnings: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'"))
    status: Mapped[str] = mapped_column(String, server_default="pending")
