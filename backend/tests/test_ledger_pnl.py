"""P&L logic on synthetic trades shaped like my real ones (numbers invented, worked by hand)."""

from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from app.ledger.pnl import (
    Fill,
    LotHistory,
    day_pnl,
    exit_outcome,
    realised,
    trade_stats,
    unrealised,
)

START = date(2026, 1, 5)


def day(n: int) -> date:
    return START + timedelta(days=n)


def fill(n: int, qty: int, price: str, charges: str = "0") -> Fill:
    return Fill(day(n), qty, D(price), D(charges))


# Averaged entry, three partial exits (shaped like AGI). Cost 4x100 + 8x103 = 1,224.
# Exits 6x110 + 3x115 + 3x111 = 1,338. Realised 114. Days 0 -> 25.
AVERAGED = LotHistory(
    buys=(fill(0, 4, "100"), fill(2, 8, "103")),
    exits=(fill(20, 6, "110"), fill(22, 3, "115"), fill(25, 3, "111")),
)
# Stop-loss exit. 10 x (184 - 200) = -160. Net: buy charges 2, sell charges 3 -> -165. 10 days.
STOPPED = LotHistory(
    buys=(fill(0, 10, "200", "2"),), exits=(fill(10, 10, "184", "3"),), stop=D("185")
)
# Second exit at breakeven (shaped like SIKA). 3x330 + 2x300.5 - 5x300 = 91. 1 day.
BREAKEVEN_LEG = LotHistory(
    buys=(fill(0, 5, "300"),), exits=(fill(1, 3, "330"), fill(1, 2, "300.5"))
)
# Sold before the stop was hit (shaped like PINELABS). 20 x (47 - 50) = -60. 30 days.
EARLY = LotHistory(buys=(fill(0, 20, "50"),), exits=(fill(30, 20, "47"),), stop=D("44"))
# Average that never terminates: cost 100 + 2x101 = 302, avg 100.666...
# Exits 110 + 111 + 112 = 333. Realised exactly 31. Days 0 -> 40.
REPEATING = LotHistory(
    buys=(fill(0, 1, "100"), fill(0, 2, "101")),
    exits=(fill(30, 1, "110"), fill(35, 1, "111"), fill(40, 1, "112")),
)
# Still open after a partial exit (shaped like SOMANYCERA): realised, but not a closed trade.
PARTIAL = LotHistory(buys=(fill(0, 15, "80", "1.5"),), exits=(fill(5, 8, "90", "0.5"),))
# Closed after the as_of date used below. 2 x (1,100 - 1,000) = 200. 5 days.
LATER = LotHistory(buys=(fill(50, 2, "1000"),), exits=(fill(55, 2, "1100"),))

ALL = [AVERAGED, STOPPED, BREAKEVEN_LEG, EARLY, REPEATING, PARTIAL, LATER]


def test_realised_gross_across_partial_exits():
    assert realised(AVERAGED).gross == D("114")


def test_realised_net_subtracts_buy_and_sell_charges():
    assert realised(STOPPED) == (D("-160"), D("-165"))


def test_full_close_is_exact_even_when_the_average_repeats():
    assert realised(REPEATING).gross == D("31")
    # After the first exit only: 110 - 302/3.
    assert realised(REPEATING, as_of=day(30)).gross == D("110") - D("302") / 3


def test_partial_exit_realises_pro_rata_cost():
    # 8 of 15 sold: 720 - 1,200 x 8/15 = 80. Net: 8/15 of 1.5 buy charges and 0.5 sell charges.
    assert realised(PARTIAL) == (D("80"), D("80") - D("0.8") - D("0.5"))


def test_unrealised_on_the_open_shares():
    # 7 open at 85: 595 - 1,200 x 7/15 = 35. Net: their 7/15 share of 1.5 buy charges.
    assert unrealised(PARTIAL, D("85")) == (D("35"), D("35") - D("0.7"))


def test_cannot_sell_more_than_the_lot_holds():
    with pytest.raises(ValueError, match="Sold 6 from a lot of 5"):
        LotHistory(buys=(fill(0, 5, "100"),), exits=(fill(1, 6, "110"),))


def test_trade_stats_pinned_to_as_of():
    stats = trade_stats(ALL, as_of=day(45))
    # Closed by day 45: AVERAGED 114, STOPPED -160, BREAKEVEN_LEG 91, EARLY -60, REPEATING 31.
    assert (stats.trades, stats.wins, stats.losses) == (5, 3, 2)
    assert stats.realised == D("16")
    assert stats.avg_win == D("236") / 3  # (114 + 91 + 31) / 3
    assert stats.avg_loss == D("110")  # (160 + 60) / 2
    assert stats.median_days == 25  # of 1, 10, 25, 30, 40


def test_trade_stats_later_includes_newer_trades():
    stats = trade_stats(ALL, as_of=day(60))
    assert (stats.trades, stats.wins, stats.realised) == (6, 4, D("216"))
    assert stats.median_days == 17.5  # of 1, 5, 10, 25, 30, 40


def test_net_stats_use_charges():
    assert trade_stats([STOPPED], as_of=day(45), basis="net").realised == D("-165")


def test_unknown_dates_count_as_trades_but_not_durations():
    opening = LotHistory(
        buys=(fill(0, 1, "10"),), exits=(fill(3, 1, "12"),), date_confidence="unknown"
    )
    stats = trade_stats([opening, STOPPED], as_of=day(45))
    assert (stats.trades, stats.median_days) == (2, 10)


@pytest.mark.parametrize(
    ("exit_price", "stop", "outcome"),
    [
        ("230", "185", "target"),
        ("200.9", "185", "breakeven"),  # within 0.5% (1.00) of 200
        ("184", "185", "stop"),
        ("185.8", "185", "stop"),  # GTT filled just above its trigger
        ("190", "185", "early_exit"),  # sold before the stop was hit
        ("190", None, "loss"),  # older trades: no stop recorded
    ],
)
def test_exit_outcome(exit_price, stop, outcome):
    assert exit_outcome(D("200"), D(exit_price), stop and D(stop)) == outcome


def test_day_pnl_bought_today_earns_only_from_the_buy_price():
    # 10 bought at 100, closes at 105: 50, not the whole day's move.
    assert day_pnl(0, D("98"), 10, D("105"), buys=[fill(0, 10, "100")]).gross == D("50")


def test_day_pnl_with_a_sale_and_a_dividend():
    # 10 held at 100; 4 sold at 104; close 103; dividend 15.
    # 6x103 - 10x100 + 4x104 + 15 = 49 (4 sold gained 4 each, 6 held gained 3 each, + 15).
    pnl = day_pnl(10, D("100"), 6, D("103"), sells=[fill(0, 4, "104", "2")], dividends=D("15"))
    assert pnl == (D("49"), D("47"))
