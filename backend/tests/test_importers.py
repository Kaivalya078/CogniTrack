"""Importers on synthetic files: pure parsing, no database."""

from decimal import Decimal as D

import pytest

from app.ingest.importers.groww_order_history import GrowwOrderHistory
from app.ingest.importers.momentum_sheet import MomentumSheet
from app.ledger.charges import estimate
from tests.sample_files import CLOSED, OPEN, ORDERS, UNDATED, groww_orders, momentum_sheet, order

MOMENTUM = momentum_sheet(CLOSED, OPEN, UNDATED, {"Stock": "TOTAL"})
GROWW = groww_orders(*ORDERS)


def test_each_importer_recognises_only_its_own_file():
    assert MomentumSheet().detect(MOMENTUM, "momentum portfolio.xlsx")
    assert not MomentumSheet().detect(GROWW, "orders.xlsx")
    assert GrowwOrderHistory().detect(GROWW, "orders.xlsx")
    assert not GrowwOrderHistory().detect(MOMENTUM, "momentum portfolio.xlsx")
    assert not MomentumSheet().detect(b"not a workbook", "notes.xlsx")


def test_momentum_sheet():
    closed, open_, undated, cash = MomentumSheet().parse(MOMENTUM, "m.xlsx")

    p = closed.payload
    assert closed.row_ref == "Sheet1!A2"
    # Cost from Total Amount (float noise removed), price = cost / qty (the ledger keeps 6 places).
    assert D(p["buys"][0]["price"]).quantize(D("0.000001")) == D("100.666667")
    assert p["opened_on"] == "2026-01-05"
    assert [(e["label"], e["qty"], e["price"], e["date"]) for e in p["exits"]] == [
        ("T1", 1, "110.00", "2026-02-04"),
        ("T2", 1, "111.00", "2026-02-09"),
        ("T3", 1, "112.00", "2026-02-14"),
    ]
    assert p["targets"] == []
    assert p["remarks"] == "rode it"
    assert p["sheet"] == {"pnl": "31.00", "days": 40}
    assert p["buys"][0]["source"] == "sheet"
    assert p["buys"][0]["charges_estimated"]
    assert D(p["exits"][0]["charges"]) == estimate("zerodha", "sell", D("110"))

    # A target without a sell date is a plan, not an exit. Serial dates are read.
    assert open_.payload["exits"] == []
    assert open_.payload["targets"] == [{"label": "T1", "price": "60.00"}]
    assert open_.payload["opened_on"] == "2026-03-02"

    assert undated.payload["opened_on"] is None
    assert undated.payload["buys"][0]["price"] == "200.50"
    assert undated.payload["file_warnings"] == [
        "Enter Price x qty is 400.00, but Total Amount is 401.00"
    ]
    assert (cash.kind, cash.payload["account"]) == ("cash", "zerodha")


def test_groww_orders_one_lot_per_buy_and_fifo_sales():
    first, second, cash = GrowwOrderHistory().parse(GROWW, "orders.xlsx")  # cancelled: dropped

    assert first.payload["isin"] == "INE0ZZ000001"
    assert first.payload["strategy"] == "long_term"
    assert first.payload["buys"][0]["source"] == "broker_report"
    assert first.payload["buys"][0]["source_ref"] == "1000000000000001"
    # The sale of 5 closes the first lot (4) and takes 1 from the second.
    (a,) = first.payload["exits"]
    (b,) = second.payload["exits"]
    assert (a["qty"], b["qty"], a["price"], a["source_ref"]) == (4, 1, "120.00", "1000000000000004")
    assert a["source_ref"] == b["source_ref"]
    # The sale's charges are split by quantity and add up to the whole.
    assert D(a["charges"]) + D(b["charges"]) == estimate("groww", "sell", D("600"))
    assert (cash.kind, cash.payload["account"]) == ("cash", "groww")


def test_groww_sale_before_the_export_starts_is_refused():
    data = groww_orders(order("SELL", 1, 100.0, "1", "05-01-2026 09:30 AM"))
    with pytest.raises(ValueError, match="sold 1 more than this export bought"):
        GrowwOrderHistory().parse(data, "orders.xlsx")
