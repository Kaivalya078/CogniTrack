from datetime import datetime

from sqlalchemy import ForeignKey, Identity, String, UniqueConstraint, func, true
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Instrument(Base):
    """An NSE-listed equity. Shared market reference data, so no user_id (like prices_daily)."""

    __tablename__ = "instruments"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    symbol: Mapped[str] = mapped_column(String, unique=True)
    isin: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    series: Mapped[str] = mapped_column(String)
    sector: Mapped[str | None] = mapped_column(String)
    # False once a symbol drops off NSE's list. Never deleted: lots may still point here.
    active: Mapped[bool] = mapped_column(server_default=true())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())


class InstrumentAlias(Base):
    """A name I confirmed as meaning this instrument (e.g. "Restau. Brands Asia" -> RBA)."""

    __tablename__ = "instrument_aliases"
    __table_args__ = (UniqueConstraint("user_id", "alias_norm"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))
    alias: Mapped[str] = mapped_column(String)
    # Lookup key: the alias after matching.normalise(), so "Paytm" and "PAYTM." are one alias.
    alias_norm: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
