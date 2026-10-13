from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Identity, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

BROKERS = ("zerodha", "groww", "other", "none")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Account(Base):
    """Where a lot sits. Strategy lives on the lot, not here."""

    __tablename__ = "accounts"
    __table_args__ = (
        # A CHECK instead of a Postgres ENUM: adding a broker later is one constraint swap.
        CheckConstraint(f"broker IN {BROKERS}", name="broker"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    broker: Mapped[str] = mapped_column(String)
    label: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
