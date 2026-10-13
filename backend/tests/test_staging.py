"""Upload -> stage -> edit -> commit, through the API, on synthetic files."""

import re
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.api.deps import OWNER_USER_ID
from app.ledger.pnl import realised
from app.ledger.queries import lot_histories
from app.models.instruments import Instrument
from app.models.ledger import CashBalance, Lot, SellAllocation, Transaction
from tests.sample_files import (
    CLOSED,
    OPEN,
    ORDERS,
    UNDATED,
    ZZLONG_ISIN,
    groww_orders,
    momentum_row,
    momentum_sheet,
)

MOMENTUM = momentum_sheet(CLOSED, OPEN, UNDATED)


@pytest.fixture(autouse=True)
def instruments(session):
    for symbol, isin in [
        ("ZZMOMO", "INE0ZZ000002"),
        ("ZZOPEN", "INE0ZZ000003"),
        ("ZZNODATE", "INE0ZZ000004"),
        ("ZZLONG", ZZLONG_ISIN),
    ]:
        session.add(Instrument(symbol=symbol, isin=isin, name=f"{symbol} Ltd", series="EQ"))
    session.flush()


def upload(client, data, filename="momentum portfolio.xlsx"):
    response = client.post(f"/api/staging/batches?filename={filename}", content=data)
    assert response.status_code == 200, response.text
    return response.json()


def by_symbol(batch):
    return {i["payload"].get("symbol", "cash"): i for i in batch["items"]}


def patch(client, item, **changes):
    response = client.patch(f"/api/staging/items/{item['id']}", json=changes)
    assert response.status_code == 200, response.text
    return response.json()


def own_histories(session, strategy):
    """This test's lots only: the database may also hold my real ledger."""
    ours = select(Lot.id).join(Instrument).where(Instrument.symbol.like("ZZ%"))
    histories = lot_histories(session, OWNER_USER_ID, strategy)
    return [histories[i] for i in session.scalars(ours) if i in histories]


def count(session, model):
    return session.scalar(select(func.count()).select_from(model))


def fill_in(client, batch):
    """What I would type on the staging page."""
    items = by_symbol(batch)
    patch(client, items["ZZOPEN"], stop="45")
    patch(client, items["ZZNODATE"], opened_on="2026-04-01", stop="180",
          targets=[{"label": "T1", "price": "230"}])  # fmt: skip


def test_staging_flags_what_needs_input_and_commit_refuses_until_filled(client, session):
    batch = upload(client, MOMENTUM)
    items = by_symbol(batch)
    assert batch["importer"] == "momentum_sheet"
    # Needs input first; closed trades need no stop.
    assert [i["payload"].get("symbol") for i in batch["items"][:2]] == ["ZZOPEN", "ZZNODATE"]
    assert items["ZZMOMO"]["needs_input"] == []
    assert items["ZZMOMO"]["realised"] == "31.00"
    assert items["ZZMOMO"]["outcomes"] == ["target", "target", "target"]
    assert items["ZZOPEN"]["needs_input"] == ["stop"]
    assert items["ZZNODATE"]["needs_input"] == ["opened_on", "T1", "stop"]
    assert "Total Amount is 401.00" in items["ZZNODATE"]["warnings"][0]

    lots_before = count(session, Lot)
    response = client.post(f"/api/staging/batches/{batch['id']}/commit")
    assert response.status_code == 409
    assert any("ZZOPEN" in p and "stop" in p for p in response.json()["detail"])
    assert count(session, Lot) == lots_before  # all or nothing

    fill_in(client, batch)
    response = client.post(f"/api/staging/batches/{batch['id']}/commit")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "committed"
    assert by_symbol(response.json())["cash"]["status"] == "skipped"  # left empty

    histories = own_histories(session, "momentum")
    assert sorted(realised(h).gross for h in histories) == [0, 0, 31]
    nodate = session.scalar(select(Lot).join(Instrument).where(Instrument.symbol == "ZZNODATE"))
    assert nodate.opened_on == date(2026, 4, 1)
    assert (nodate.stop_price, nodate.targets) == (D("180"), [{"label": "T1", "price": "230"}])
    buy = session.scalar(select(Transaction).where(Transaction.lot_id == nodate.id))
    assert (buy.trade_date, buy.price, buy.charges_estimated) == (
        date(2026, 4, 1),
        D("200.5"),
        True,
    )
    closed = session.scalar(select(Lot).join(Instrument).where(Instrument.symbol == "ZZMOMO"))
    assert (closed.status, closed.qty_open, closed.remarks) == ("closed", 0, "rode it")


def test_reimport_is_unchanged_then_picks_up_new_exits_and_flags_edits(client, session):
    fill_in(client, batch := upload(client, MOMENTUM))
    client.post(f"/api/staging/batches/{batch['id']}/commit")
    txns = count(session, Transaction)

    again = by_symbol(upload(client, MOMENTUM))
    assert {i["match_status"] for s, i in again.items() if s != "cash"} == {"unchanged"}
    assert again["ZZNODATE"]["needs_input"] == []  # its date and stop are in the ledger now

    # ZZOPEN hits T1; ZZMOMO's T1 price was edited in the sheet.
    hit = momentum_row("ZZOPEN", 50, 10, 500, OPEN["Date Purchased"],
                       exits=[(60, date(2026, 4, 10), 5)])  # fmt: skip
    edited = CLOSED | {"Target 1": 109}
    batch = upload(client, momentum_sheet(edited, hit, UNDATED))
    items = by_symbol(batch)
    assert items["ZZOPEN"]["match_status"] == "changed"
    assert items["ZZOPEN"]["diff"] == ["new exit: T1 5 @ 60.00 on 2026-04-10"]
    assert items["ZZMOMO"]["match_status"] == "conflict"
    assert "109.00" in items["ZZMOMO"]["diff"][0]

    assert client.post(f"/api/staging/batches/{batch['id']}/commit").status_code == 409
    patch(client, items["ZZMOMO"], status="skipped")
    assert client.post(f"/api/staging/batches/{batch['id']}/commit").status_code == 200
    assert count(session, Transaction) == txns + 1
    lot = session.scalar(select(Lot).join(Instrument).where(Instrument.symbol == "ZZOPEN"))
    assert (lot.qty_open, lot.stop_price) == (5, D("45"))  # the stop I entered is kept


def test_groww_orders_commit_one_sale_split_across_two_lots(client, session):
    batch = upload(client, groww_orders(*ORDERS), "Stocks_Order_History.xlsx")
    assert batch["importer"] == "groww_order_history"
    items = by_symbol(batch)
    assert all(not i["needs_input"] for i in batch["items"])  # no stop or thesis needed
    patch(client, items["cash"], amount="547", as_of="2030-01-01")
    assert client.post(f"/api/staging/batches/{batch['id']}/commit").status_code == 200

    sale = session.scalar(select(Transaction).where(Transaction.source_ref == "1000000000000004"))
    assert (sale.qty, sale.price, sale.lot_id) == (5, D("120"), None)
    allocations = session.scalars(
        select(SellAllocation.qty).where(SellAllocation.sell_txn_id == sale.id)
    ).all()
    assert sorted(allocations) == [1, 4]
    histories = own_histories(session, "long_term")
    assert sorted(realised(h).gross for h in histories) == [10, 80]
    cash = session.scalar(select(CashBalance).where(CashBalance.as_of == date(2030, 1, 1)))
    assert (cash.amount, cash.source) == (D("547"), "manual")

    again = upload(client, groww_orders(*ORDERS), "Stocks_Order_History.xlsx")
    assert {i["match_status"] for i in again["items"] if i["kind"] == "lot"} == {"unchanged"}


def test_unknown_file_and_wrong_fields(client):
    response = client.post("/api/staging/batches?filename=notes.xlsx", content=b"hello")
    assert response.status_code == 400
    batch = upload(client, MOMENTUM)
    item = by_symbol(batch)["ZZOPEN"]
    response = client.patch(f"/api/staging/items/{item['id']}", json={"amount": "5"})
    assert response.status_code == 422
    response = client.patch(f"/api/staging/items/{item['id']}", json={"stop": "-1"})
    assert response.status_code == 422
    assert client.post(f"/api/staging/batches/{batch['id']}/discard").status_code == 200
    assert client.patch(f"/api/staging/items/{item['id']}", json={"stop": "1"}).status_code == 409


# Constructing or inserting a ledger row (class definitions excluded).
LEDGER_MODELS = re.compile(
    r"(?<!class )\b(Lot|Transaction|SellAllocation|CashBalance)\(|insert\(CashBalance"
)


def test_only_the_commit_writes_the_ledger():
    """Rule 2: the ledger is written in exactly one place."""
    app_dir = Path(__file__).resolve().parents[1] / "app"
    writers = {
        path.relative_to(app_dir).as_posix()
        for path in app_dir.rglob("*.py")
        if LEDGER_MODELS.search(path.read_text(encoding="utf-8"))
    }
    assert writers == {"ingest/commit.py"}


@pytest.mark.parametrize(
    ("headers", "status"),
    [
        ({"Sec-Fetch-Site": "cross-site"}, 403),
        ({"Sec-Fetch-Site": "same-site"}, 403),
        ({"Origin": "https://evil.example"}, 403),  # an older browser: no Sec-Fetch-Site
        ({"Sec-Fetch-Site": "same-origin"}, 404),  # allowed through; there is no batch 0
        ({"Origin": "http://localhost"}, 404),
        ({}, 404),  # curl or a script
    ],
)
def test_cross_site_writes_are_refused(client, headers, status):
    response = client.post("/api/staging/batches/0/commit", headers=headers)
    assert response.status_code == status


def test_unknown_host_is_refused(client):
    """DNS rebinding: a page on evil.example whose name now points at this machine."""
    response = client.get("/api/staging/batches", headers={"Host": "evil.example"})
    assert response.status_code == 400
