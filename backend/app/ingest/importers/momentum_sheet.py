"""My momentum trade log: one row per trade, up to four exits, in the Zerodha account.

A "Target N" cell with a sell date is an actual exit; without one it is a planned target.
The sheet's P&L is gross. Averaged entries (AGI, RATNAVEER) stay one buy until M7 splits them.
"""

from typing import Any

from app.ingest.importers import ProposedItem, cash_item, excel_date, find_table, rows, rupees
from app.ledger.charges import estimate

SOURCE = "momentum_sheet"
BROKER = "zerodha"
REQUIRED = {"Stock", "Enter Price", "Qty Purchased", "Total Amount", "Date Purchased"}
TARGETS = range(1, 5)


class MomentumSheet:
    source = SOURCE

    def detect(self, data: bytes, filename: str) -> bool:
        return filename.lower().endswith(".xlsx") and find_table(data, REQUIRED) is not None

    def parse(self, data: bytes, filename: str) -> list[ProposedItem]:
        items = []
        for ref, row in rows(data, REQUIRED):
            symbol = str(row["Stock"] or "").strip()
            if not symbol or symbol.upper() == "TOTAL":
                break
            items.append(parse_row(ref, symbol, row))
        return [*items, cash_item(BROKER)]


def parse_row(ref: str, symbol: str, row: dict[str, Any]) -> ProposedItem:
    warnings = []
    qty = int(row["Qty Purchased"])
    # Cost from the total, price = cost / qty: averaged entries (1,084.84 / 6) stay exact.
    total = rupees(row["Total Amount"] if row["Total Amount"] is not None else 0)
    entered = rupees(row["Enter Price"]) * qty
    if not total:
        total = entered
    elif abs(rupees(row["Enter Price"]) - total / qty) >= 0.01:
        warnings.append(f"Enter Price x qty is {entered}, but Total Amount is {total}")
    opened = excel_date(row["Date Purchased"])
    key = f"{SOURCE}:{symbol}:{opened or 'undated'}"

    exits, targets = [], []
    for n in TARGETS:
        price, day, sold = (
            row.get(f"Target {n}"),
            row.get(f"Target {n} Sell Date"),
            row.get(f"Qty Sold {n}"),
        )
        day = excel_date(day)
        if day is not None:
            if price is None or not sold:
                warnings.append(f"T{n} has a sell date but no price or quantity: ignored")
                continue
            value = rupees(price) * int(sold)
            exits.append(
                {
                    "label": f"T{n}",
                    "date": day.isoformat(),
                    "qty": int(sold),
                    "price": str(rupees(price)),
                    "charges": str(estimate(BROKER, "sell", value)),
                    "charges_estimated": True,
                    "source": "sheet",
                    "source_ref": f"{key}:T{n}",
                }
            )
        elif price is not None:
            targets.append({"label": f"T{n}", "price": str(rupees(price))})
            if sold:
                warnings.append(f"T{n} has a quantity sold but no sell date: kept as a plan")

    payload = {
        "strategy": "momentum",
        "account": BROKER,
        "symbol": symbol,
        "isin": None,
        "name": None,
        "opened_on": opened and opened.isoformat(),
        "date_confidence": "exact",
        "buys": [
            {
                "date": opened and opened.isoformat(),
                "qty": qty,
                "price": str(total / qty),
                "charges": str(estimate(BROKER, "buy", total)),
                "charges_estimated": True,
                "source": "sheet",
                "source_ref": key,
            }
        ],
        "exits": exits,
        "targets": targets,
        "stop": None,
        "thesis": None,
        "review_trigger": None,
        "remarks": (str(row.get("remarks") or "").strip() or None),
        "sheet": {
            "pnl": row.get("P&L") and str(rupees(row["P&L"])),
            "days": row.get("Duration"),
        },
    }
    return ProposedItem(ref, "lot", payload | {"file_warnings": warnings})
