"""Golden numbers: my real files through upload -> staging -> commit -> ledger (rolled back).

Needs the private files and the real NSE list in the local database
(python -m app.market.instruments). Expected values are in CLAUDE.md.
"""

from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest
from sqlalchemy import select

from app.api.deps import OWNER_USER_ID
from app.ledger.pnl import LotHistory, realised, trade_stats
from app.ledger.queries import lot_histories
from app.models.instruments import Instrument
from app.models.ledger import Lot

PRIVATE = Path(__file__).parent / "fixtures" / "private"
MOMENTUM = PRIVATE / "momentum portfolio.xlsx"
ORDERS = sorted(PRIVATE.glob("Stocks_Order_History_*.xlsx"))

pytestmark = [
    pytest.mark.private,
    pytest.mark.skipif(not (MOMENTUM.exists() and ORDERS), reason="private files not present"),
]
PAISE = D("0.01")


@pytest.fixture
def ledger(client, session):
    for path in (MOMENTUM, ORDERS[-1]):
        response = client.post(
            f"/api/staging/batches?filename={path.name}", content=path.read_bytes()
        )
        assert response.status_code == 200, response.text
        batch = response.json()
        for item in batch["items"]:
            # Placeholders for what I type on the staging page; they don't affect these numbers.
            fill = {"stop": "1"} if "stop" in item["needs_input"] else {}
            if "T1" in item["needs_input"]:
                fill["targets"] = [{"label": "T1", "price": "99999"}]
            if "opened_on" in item["needs_input"]:
                fill["opened_on"] = "2026-10-08"  # RRKABEL
            if fill:
                client.patch(f"/api/staging/items/{item['id']}", json=fill)
        response = client.post(f"/api/staging/batches/{batch['id']}/commit")
        assert response.status_code == 200, response.text
    return session


def test_momentum(ledger):
    lots = lot_histories(ledger, OWNER_USER_ID, "momentum")
    agi = ledger.scalar(select(Lot.id).join(Instrument).where(Instrument.symbol == "AGI"))
    assert realised(lots[agi]).gross == D("934.50")

    s = trade_stats(lots.values(), date(2026, 9, 24))
    assert (s.trades, s.realised, s.wins) == (13, D("4025.09"), 8)
    assert (s.avg_win.quantize(PAISE), s.avg_loss.quantize(PAISE)) == (D("794.89"), D("466.81"))
    assert s.median_days == 26

    s = trade_stats(lots.values(), date(2026, 10, 12))
    assert (s.trades, s.realised, s.wins) == (15, D("2875.69"), 8)
    assert (s.avg_win.quantize(PAISE), s.avg_loss.quantize(PAISE)) == (D("794.89"), D("497.64"))
    assert s.median_days == 26


def held_on(lot: LotHistory, day: date) -> tuple[int, D]:
    """(shares held, their cost) at the end of `day`."""
    if min(b.day for b in lot.buys) > day:
        return 0, D(0)
    qty = lot.bought_qty - sum(e.qty for e in lot.exits if e.day <= day)
    return qty, lot.cost_of(qty)[0]


def long_term_on(session, day):
    lots = lot_histories(session, OWNER_USER_ID, "long_term")
    instrument = dict(
        session.execute(select(Lot.id, Lot.instrument_id).where(Lot.id.in_(lots))).all()
    )
    held = {i: held_on(h, day) for i, h in lots.items()}
    open_ids = [i for i, (qty, _) in held.items() if qty]
    return (
        len(open_ids),
        len({instrument[i] for i in open_ids}),
        sum(cost for _, cost in held.values()),
        sum(realised(h, as_of=day).gross for h in lots.values()),
    )


def test_long_term(ledger):
    # The long-term sheet's snapshot (18 Sep): 22 stocks, ₹1,31,052.40 there because the sheet
    # rounds Lenskart and Sakar by a few paise.
    _, stocks, invested, _ = long_term_on(ledger, date(2026, 9, 18))
    assert (stocks, invested) == (22, D("131052.45"))
    assert long_term_on(ledger, date(2026, 10, 12)) == (31, 23, D("133381.63"), D("-1940.45"))


def test_syrma_is_two_lots(ledger):
    lots = ledger.execute(
        select(Lot.qty_initial, Lot.qty_open)
        .join(Instrument)
        .where(Instrument.symbol == "SYRMA")
        .order_by(Lot.qty_initial)
    ).all()
    assert [tuple(r) for r in lots] == [(3, 2), (7, 7)]  # momentum, long-term
