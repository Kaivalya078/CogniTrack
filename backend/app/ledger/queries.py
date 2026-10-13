"""Read lots back from the ledger as M2's LotHistory, for the P&L functions."""

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ledger.pnl import Fill, LotHistory
from app.models.ledger import Lot, SellAllocation, Strategy, Transaction


def lot_histories(session: Session, user_id: int, strategy: str) -> dict[int, LotHistory]:
    """Lot id -> history for every lot under `strategy`. Exits follow sell_allocations, and a
    sale split across lots charges each lot its share by quantity."""
    lots = session.scalars(
        select(Lot)
        .join(Strategy, Lot.strategy_id == Strategy.id)
        .where(Lot.user_id == user_id, Strategy.name == strategy)
    ).all()
    ids = [lot.id for lot in lots]
    buys, exits = defaultdict(list), defaultdict(list)
    for t in session.scalars(
        select(Transaction).where(Transaction.lot_id.in_(ids), Transaction.kind == "buy")
    ):
        buys[t.lot_id].append(Fill(t.trade_date, t.qty, t.price, t.charges))
    for t, a in session.execute(
        select(Transaction, SellAllocation)
        .join(SellAllocation, SellAllocation.sell_txn_id == Transaction.id)
        .where(SellAllocation.lot_id.in_(ids))
    ):
        exits[a.lot_id].append(Fill(t.trade_date, a.qty, t.price, t.charges * a.qty / t.qty))
    return {
        lot.id: LotHistory(
            buys=tuple(buys[lot.id]),
            exits=tuple(sorted(exits[lot.id], key=lambda f: f.day)),
            stop=lot.stop_price,
            date_confidence=lot.date_confidence,
        )
        for lot in lots
    }
