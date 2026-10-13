"""Estimated charges on an equity delivery trade, from each broker's published rates.

Used only when real charges are unknown; such transactions get charges_estimated = true, and
contract notes replace them later (M7). Brokers change these rates: checked against
zerodha.com/charges and groww.in/pricing on 13 Oct 2026.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

Side = Literal["buy", "sell"]
PCT = Decimal("0.01")
STT = Decimal("0.1") * PCT  # both sides
STAMP = Decimal("0.015") * PCT  # buy side only
SEBI = Decimal("0.0001") * PCT  # ₹10 per crore
GST = Decimal("0.18")  # on brokerage, exchange and SEBI charges and the DP charge


@dataclass(frozen=True)
class Rates:
    brokerage_pct: Decimal  # of the order value, within [min, max] per order
    brokerage_min: Decimal
    brokerage_max: Decimal
    exchange_pct: dict[str, Decimal]
    dp_per_sell: Decimal  # per scrip per day of selling, before GST


RATES = {
    "zerodha": Rates(
        brokerage_pct=Decimal(0),
        brokerage_min=Decimal(0),
        brokerage_max=Decimal(0),
        exchange_pct={"NSE": Decimal("0.00307") * PCT, "BSE": Decimal("0.00375") * PCT},
        dp_per_sell=Decimal("13"),
    ),
    "groww": Rates(
        brokerage_pct=Decimal("0.1") * PCT,
        brokerage_min=Decimal("5"),
        brokerage_max=Decimal("20"),
        exchange_pct={"NSE": Decimal("0.00297") * PCT, "BSE": Decimal("0.00375") * PCT},
        # ₹3.50 CDSL + ₹16.50 Groww. CDSL charges women ₹3.25; the 25 paise is ignored.
        dp_per_sell=Decimal("20"),
    ),
}


def estimate(broker: str, side: Side, value: Decimal, exchange: str = "NSE") -> Decimal:
    """Total charges on one order of `value` rupees, rounded to paise.

    ponytail: one order is treated as one DP charge on a sale; two sales of the same stock on
    the same day really share one. Exchanges also round STT to the rupee. Both are within a few
    rupees, and real charges replace estimates in M7.
    """
    rates = RATES[broker]
    brokerage = min(max(value * rates.brokerage_pct, rates.brokerage_min), rates.brokerage_max)
    dp = rates.dp_per_sell if side == "sell" else Decimal(0)
    taxable = brokerage + value * rates.exchange_pct[exchange] + value * SEBI + dp
    total = taxable * (1 + GST) + value * STT + (value * STAMP if side == "buy" else 0)
    return total.quantize(Decimal("0.01"), ROUND_HALF_UP)
