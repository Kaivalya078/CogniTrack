"""P&L math. Pure functions over plain values: no database, no files.

Amounts are exact Decimals. The only rounding is each fill settling in paise; round results
only for display. Gross ignores charges, net subtracts them.
"""

import statistics
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal, NamedTuple

ZERO = Decimal(0)
PAISE = Decimal("0.01")
# An exit this close to the entry price counts as breakeven (SIKA: 1,197 against 1,196.80).
BREAKEVEN_PCT = Decimal("0.5")

Outcome = Literal["target", "breakeven", "stop", "early_exit", "loss"]


@dataclass(frozen=True)
class Fill:
    day: date
    qty: int
    price: Decimal
    charges: Decimal = ZERO

    @property
    def value(self) -> Decimal:
        """What the fill settled for, in paise. The ledger keeps prices to 6 places, so an
        averaged entry (1,084.84 / 6 = 180.806667) gets back its exact total this way."""
        return (self.qty * self.price).quantize(PAISE, ROUND_HALF_UP)


class PnL(NamedTuple):
    gross: Decimal
    net: Decimal


@dataclass(frozen=True)
class LotHistory:
    """One lot's buys and its share of each sale (from sell_allocations).

    A sale split across lots is split before it gets here: each exit carries this lot's qty and
    this lot's share of the sale's charges.
    """

    buys: tuple[Fill, ...]
    exits: tuple[Fill, ...] = ()
    stop: Decimal | None = None
    date_confidence: str = "exact"

    def __post_init__(self) -> None:
        if not self.buys:
            raise ValueError("A lot needs at least one buy")
        if self.sold_qty > self.bought_qty:
            raise ValueError(f"Sold {self.sold_qty} from a lot of {self.bought_qty}")

    @property
    def bought_qty(self) -> int:
        return sum(b.qty for b in self.buys)

    @property
    def sold_qty(self) -> int:
        return sum(e.qty for e in self.exits)

    @property
    def open_qty(self) -> int:
        return self.bought_qty - self.sold_qty

    @property
    def cost(self) -> Decimal:
        return sum((b.value for b in self.buys), ZERO)

    @property
    def avg_cost(self) -> Decimal:
        return self.cost / self.bought_qty

    @property
    def closed(self) -> bool:
        return self.open_qty == 0

    def cost_of(self, qty: int) -> tuple[Decimal, Decimal]:
        """(cost, buy charges) attributable to `qty` shares of this lot, pro rata.

        Pro rata rather than qty * avg_cost so a fully sold lot comes out exact even when the
        average price repeats forever (1,084.84 / 6).
        """
        buy_charges = sum((b.charges for b in self.buys), ZERO)
        return (
            self.cost * qty / self.bought_qty,
            buy_charges * qty / self.bought_qty,
        )


def realised(lot: LotHistory, as_of: date | None = None) -> PnL:
    """P&L on the shares this lot has sold (by `as_of`, if given)."""
    exits = [e for e in lot.exits if as_of is None or e.day <= as_of]
    sold = sum(e.qty for e in exits)
    cost, buy_charges = lot.cost_of(sold)
    gross = sum((e.value for e in exits), ZERO) - cost
    return PnL(gross, gross - buy_charges - sum((e.charges for e in exits), ZERO))


def unrealised(lot: LotHistory, close: Decimal) -> PnL:
    """P&L on the shares still held, at `close`. Net subtracts their buy charges only."""
    cost, buy_charges = lot.cost_of(lot.open_qty)
    gross = lot.open_qty * close - cost
    return PnL(gross, gross - buy_charges)


def day_pnl(
    qty_before: int,
    close_before: Decimal,
    qty_after: int,
    close: Decimal,
    buys: Iterable[Fill] = (),
    sells: Iterable[Fill] = (),
    dividends: Decimal = ZERO,
) -> PnL:
    """One day for one position: MV today - MV yesterday + sale proceeds - buy cost + dividends.

    A lot bought today therefore earns (close - buy price) x qty, not the whole day's move.
    """
    buys, sells = list(buys), list(sells)
    gross = (
        qty_after * close
        - qty_before * close_before
        + sum((s.value for s in sells), ZERO)
        - sum((b.value for b in buys), ZERO)
        + dividends
    )
    return PnL(gross, gross - sum((f.charges for f in buys + sells), ZERO))


def exit_outcome(entry: Decimal, exit_price: Decimal, stop: Decimal | None) -> Outcome:
    """Label an exit from its price, never from remarks.

    `stop` counts a fill near the stop as a stop: a GTT can fill a little above its trigger.
    """
    tolerance = entry * BREAKEVEN_PCT / 100
    if abs(exit_price - entry) <= tolerance:
        return "breakeven"
    if exit_price > entry:
        return "target"
    if stop is None:
        return "loss"
    if exit_price <= stop + tolerance:
        return "stop"
    return "early_exit"


@dataclass(frozen=True)
class TradeStats:
    trades: int
    wins: int
    losses: int
    realised: Decimal
    avg_win: Decimal | None
    avg_loss: Decimal | None  # as a positive amount
    median_days: float | None  # first buy to last exit; lots with unknown dates left out


def trade_stats(
    lots: Iterable[LotHistory], as_of: date, basis: Literal["gross", "net"] = "gross"
) -> TradeStats:
    """Stats over trades fully closed on or before `as_of`. A zero-P&L trade is neither a win
    nor a loss. Pinning `as_of` keeps a result stable while new trades are added."""
    closed = [lot for lot in lots if lot.closed and max(e.day for e in lot.exits) <= as_of]
    results = [getattr(realised(lot), basis) for lot in closed]
    wins = [r for r in results if r > 0]
    losses = [-r for r in results if r < 0]
    days = [
        (max(e.day for e in lot.exits) - min(b.day for b in lot.buys)).days
        for lot in closed
        if lot.date_confidence != "unknown"
    ]
    return TradeStats(
        trades=len(closed),
        wins=len(wins),
        losses=len(losses),
        realised=sum(results, ZERO),
        avg_win=sum(wins, ZERO) / len(wins) if wins else None,
        avg_loss=sum(losses, ZERO) / len(losses) if losses else None,
        median_days=statistics.median(days) if days else None,
    )
