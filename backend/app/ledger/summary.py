"""Print the headline numbers straight from the ledger, to check them against my sheets.

uv run python -m app.ledger.summary                      # trade stats as of today
uv run python -m app.ledger.summary --as-of 2026-09-24   # pinned, like the golden tests
"""

import argparse
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.api.deps import OWNER_USER_ID
from app.core.db import SessionLocal
from app.ledger.pnl import realised, trade_stats
from app.ledger.queries import lot_histories
from app.models.instruments import Instrument
from app.models.ledger import CashBalance, Lot
from app.models.users import Account


def inr(amount: Decimal | None) -> str:
    """₹1,33,381.63: Indian digit grouping (lakhs and crores)."""
    if amount is None:
        return "-"
    sign = "-" if amount < 0 else ""
    whole, paise = f"{abs(amount):.2f}".split(".")
    head, tail = whole[:-3], whole[-3:]
    while len(head) > 2:
        head, tail = head[:-2], f"{head[-2:]},{tail}"
    return f"{sign}₹{head + ',' if head else ''}{tail}.{paise}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    args = parser.parse_args()

    with SessionLocal() as session:
        momentum = lot_histories(session, OWNER_USER_ID, "momentum")
        s = trade_stats(momentum.values(), args.as_of)
        net = trade_stats(momentum.values(), args.as_of, basis="net").realised
        print(f"Momentum, trades closed by {args.as_of}: {s.trades}")
        print(f"  realised {inr(s.realised)} gross, {inr(net)} net of estimated charges")
        print(
            f"  wins {s.wins} of {s.trades}, average win {inr(s.avg_win)}, "
            f"average loss {inr(s.avg_loss)}, median {s.median_days} days"
        )

        long_term = lot_histories(session, OWNER_USER_ID, "long_term")
        open_lots = {i: h for i, h in long_term.items() if not h.closed}
        stocks = session.scalars(
            select(Lot.instrument_id).where(Lot.id.in_(open_lots)).distinct()
        ).all()
        invested = sum((h.cost_of(h.open_qty)[0] for h in open_lots.values()), Decimal(0))
        gross = sum((realised(h).gross for h in long_term.values()), Decimal(0))
        print(f"Long-term: {len(open_lots)} open lots in {len(stocks)} stocks")
        print(f"  invested {inr(invested)}, realised {inr(gross)} gross")

        print("Open momentum lots:")
        rows = session.execute(
            select(Lot, Instrument.symbol)
            .join(Instrument, Lot.instrument_id == Instrument.id)
            .where(Lot.id.in_([i for i, h in momentum.items() if not h.closed]))
            .order_by(Lot.opened_on)
        )
        for lot, symbol in rows:
            t1 = next((t["price"] for t in lot.targets if t["label"] == "T1"), "-")
            stop = "-" if lot.stop_price is None else f"{lot.stop_price:.2f}"
            print(
                f"  {symbol:12} {lot.qty_open:>3} @ {lot.avg_cost:.2f}  opened {lot.opened_on}"
                f"  T1 {t1}  stop {stop}"
            )

        for broker, as_of, amount in session.execute(
            select(Account.broker, CashBalance.as_of, CashBalance.amount)
            .join(Account, CashBalance.account_id == Account.id)
            .order_by(CashBalance.as_of)
        ):
            print(f"Cash: {broker} {inr(amount)} on {as_of}")


if __name__ == "__main__":
    main()
