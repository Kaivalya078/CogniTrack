"""Groww's order history export (Stocks > Orders > Download), my long-term account.

Each executed buy becomes its own lot; each sale is matched to those lots oldest first (FIFO),
since the export does not say which purchase I meant to sell. source_ref is the exchange order
id, so a newer export of an overlapping period only adds orders the ledger does not have yet.
The export has no charges: they are estimated.
"""

from collections import defaultdict, deque
from datetime import datetime
from decimal import Decimal

from app.ingest.importers import ProposedItem, cash_item, find_table, rows, rupees
from app.ledger.charges import estimate

SOURCE = "groww_order_history"
BROKER = "groww"
REQUIRED = {
    "Symbol",
    "ISIN",
    "Type",
    "Quantity",
    "Value",
    "Exchange Order Id",
    "Execution date and time",
    "Order status",
}


class GrowwOrderHistory:
    source = SOURCE

    def detect(self, data: bytes, filename: str) -> bool:
        return filename.lower().endswith(".xlsx") and find_table(data, REQUIRED) is not None

    def parse(self, data: bytes, filename: str) -> list[ProposedItem]:
        orders = []
        for ref, row in rows(data, REQUIRED):
            if not row["Symbol"]:
                break
            if str(row["Order status"]).strip() != "Executed":
                continue
            when = datetime.strptime(str(row["Execution date and time"]), "%d-%m-%Y %I:%M %p")
            orders.append((when, ref, row))
        orders.sort(key=lambda o: o[0])  # stable: same-minute orders keep the file's order

        lots: dict[str, deque[ProposedItem]] = defaultdict(deque)  # ISIN -> lots with shares left
        items = []
        for when, ref, row in orders:
            qty, value = int(row["Quantity"]), rupees(row["Value"])
            exchange = str(row["Exchange"] or "NSE").strip()
            fill = {
                "date": when.date().isoformat(),
                "qty": qty,
                "price": str(value / qty),
                "charges_estimated": True,
                "source": "broker_report",
                "source_ref": str(row["Exchange Order Id"]).strip(),
            }
            side = str(row["Type"]).strip().lower()
            if side == "buy":
                item = ProposedItem(
                    ref,
                    "lot",
                    {
                        "strategy": "long_term",
                        "account": BROKER,
                        "symbol": str(row["Symbol"]).strip(),
                        "isin": str(row["ISIN"]).strip(),
                        "name": str(row.get("Stock name") or "").strip() or None,
                        "opened_on": fill["date"],
                        "date_confidence": "exact",
                        "buys": [fill | {"charges": str(estimate(BROKER, "buy", value, exchange))}],
                        "exits": [],
                        "targets": [],
                        "stop": None,
                        "thesis": None,
                        "review_trigger": None,
                        "remarks": None,
                    },
                )
                items.append(item)
                lots[item.payload["isin"]].append(item)
            elif side == "sell":
                allocate(
                    lots[str(row["ISIN"]).strip()],
                    fill,
                    row["Symbol"],
                    estimate(BROKER, "sell", value, exchange),
                )
            else:
                raise ValueError(f"{ref}: unknown order type {row['Type']!r}")
        return [*items, cash_item(BROKER)]


def allocate(open_lots: deque[ProposedItem], sale: dict, symbol: str, charges: Decimal) -> None:
    """Add a sale to the oldest lots that still hold shares, splitting its charges by quantity."""
    left = sale["qty"]
    charged = Decimal(0)
    while left:
        if not open_lots:
            # ponytail: FIFO only sees this file. A sale of shares bought before the export's
            # start needs an export that reaches back to that purchase.
            raise ValueError(
                f"{symbol}: sold {left} more than this export bought; use an export that starts "
                "before those shares were bought"
            )
        lot = open_lots[0].payload
        held = lot["buys"][0]["qty"] - sum(e["qty"] for e in lot["exits"])
        part = min(held, left)
        left -= part
        share = (
            charges - charged
            if not left
            else (charges * part / sale["qty"]).quantize(Decimal("0.01"))
        )
        charged += share
        lot["exits"].append(sale | {"label": None, "qty": part, "charges": str(share)})
        if part == held:
            open_lots.popleft()
