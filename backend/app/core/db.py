from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, MetaData, Numeric, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.settings import settings

# Predictable constraint names, so later migrations can drop or alter them by name.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    # Timestamps are always UTC timestamptz; ids are bigint; money is NUMERIC, never float.
    # Six decimals hold averaged entry prices (1,084.84 / 6 = 180.806667) to under ₹0.0001.
    type_annotation_map = {
        datetime: DateTime(timezone=True),
        int: BigInteger,
        Decimal: Numeric(20, 6),
    }


engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(engine)


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
