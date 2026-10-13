"""Ledger tables: seed data and the rules Postgres enforces."""

from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import OWNER_USER_ID
from app.models.instruments import Instrument
from app.models.ledger import Lot, SellAllocation, Strategy, Transaction
from app.models.users import Account


@pytest.fixture
def ids(session):
    """A test instrument plus the seeded strategies and accounts, by name."""
    instrument = Instrument(symbol="ZZLEDGER", isin="INE000000001", name="Zz Ledger", series="EQ")
    session.add(instrument)
    session.flush()
    strategies = {s.name: s.id for s in session.scalars(select(Strategy))}
    accounts = {a.broker: a.id for a in session.scalars(select(Account))}
    return {"instrument": instrument.id, **strategies, **accounts}


def lot(ids, strategy="momentum", broker="zerodha", **overrides) -> Lot:
    fields = dict(
        user_id=OWNER_USER_ID,
        instrument_id=ids["instrument"],
        strategy_id=ids[strategy],
        account_id=ids[broker],
        opened_on=date(2026, 8, 5),
        date_confidence="exact",
        qty_initial=3,
        qty_open=3,
        avg_cost=D("1444.6"),
        status="open",
    )
    return Lot(**fields | overrides)


def txn(ids, **overrides) -> Transaction:
    fields = dict(
        user_id=OWNER_USER_ID,
        instrument_id=ids["instrument"],
        kind="buy",
        trade_date=date(2026, 8, 5),
        qty=3,
        price=D("1444.6"),
        charges_estimated=True,
        source="sheet",
        source_ref="test",
    )
    return Transaction(**fields | overrides)


def test_seeded_strategies_and_accounts(session):
    strategies = {s.name: s for s in session.scalars(select(Strategy))}
    assert strategies["momentum"].config["required_at_entry"] == ["T1", "stop"]
    assert strategies["long_term"].config["stop"] is None
    assert {s.version for s in strategies.values()} == {1}
    assert {a.broker for a in session.scalars(select(Account))} >= {"zerodha", "groww"}


def test_same_stock_under_two_strategies_stays_two_lots(session, ids):
    # Syrma: 3 momentum on Zerodha, 7 long-term on Groww.
    session.add_all([lot(ids), lot(ids, "long_term", "groww", qty_initial=7, qty_open=7)])
    session.flush()
    lots = session.scalars(select(Lot).where(Lot.instrument_id == ids["instrument"])).all()
    assert sorted(lot.qty_open for lot in lots) == [3, 7]


def test_sale_allocated_to_a_lot(session, ids):
    momentum = lot(ids)
    session.add(momentum)
    session.flush()
    sale = txn(ids, kind="sell", qty=1, price=D("1780"))
    session.add(sale)
    session.flush()
    session.add(
        SellAllocation(user_id=OWNER_USER_ID, sell_txn_id=sale.id, lot_id=momentum.id, qty=1)
    )
    session.flush()


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"qty_open": 4}, "ck_lots_qty_open"),  # more open than bought
        ({"status": "closed"}, "ck_lots_closed_means_empty"),  # closed with shares still open
        ({"date_confidence": "guess"}, "ck_lots_date_confidence"),
    ],
)
def test_lot_rules(session, ids, overrides, constraint):
    session.add(lot(ids, **overrides))
    with pytest.raises(IntegrityError, match=constraint):
        session.flush()


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"price": None}, "ck_transactions_fill"),  # a buy needs a price
        ({"qty": 0}, "ck_transactions_fill"),
        ({"source": "rumour"}, "ck_transactions_source"),
        ({"kind": "sell"}, "ck_transactions_lot"),  # a sale names its lots via sell_allocations
        ({"lot_id": None}, "ck_transactions_lot"),  # a buy belongs to a lot
    ],
)
def test_transaction_rules(session, ids, overrides, constraint):
    owner = lot(ids)
    session.add(owner)
    session.flush()
    session.add(txn(ids, **{"lot_id": owner.id} | overrides))
    with pytest.raises(IntegrityError, match=constraint):
        session.flush()
