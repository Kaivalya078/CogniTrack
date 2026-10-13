"""Synthetic files in my real files' layouts (same headers, invented rows), built at test time."""

import io
from datetime import date, datetime

import openpyxl

MOMENTUM_HEADERS = [
    "Stock", "Enter Price", "Qty Purchased", "Total Amount", "Date Purchased",
    "Target 1", "Target 1 Sell Date", "Qty Sold 1", "Target 2", "Target 2 Sell Date",
    "Qty Sold 2", "Target 3", "Target 3 Sell Date", "Qty Sold 3", "Target 4",
    "Target 4 Sell Date", "Qty Sold 4", "P&L", "P&L %", "Duration", "remarks", "Net Profit",
]  # fmt: skip


def excel_serial(day: date) -> int:
    return (day - date(1899, 12, 30)).days


def momentum_row(
    stock, price, qty, total, bought, exits=(), plans=(), pnl=None, days=None, remarks=None
) -> dict:
    """exits: (price, sell date, qty) per target; plans: planned target prices after them."""
    row = {
        "Stock": stock,
        "Enter Price": price,
        "Qty Purchased": qty,
        "Total Amount": total,
        "Date Purchased": bought,
        "P&L": pnl,
        "Duration": days,
        "remarks": remarks,
    }
    for n, (p, d, q) in enumerate(exits, 1):
        row |= {f"Target {n}": p, f"Target {n} Sell Date": d, f"Qty Sold {n}": q}
    for n, p in enumerate(plans, len(exits) + 1):
        row[f"Target {n}"] = p
    return row


# An averaged entry that never terminates (302 / 3), closed in three exits: realised exactly 31.
# Total Amount carries Excel's float noise.
CLOSED = momentum_row(
    "ZZMOMO", 100.66666666666667, 3, 302.00000000000006, datetime(2026, 1, 5),
    exits=[(110, datetime(2026, 2, 4), 1), (111, datetime(2026, 2, 9), 1),
           (112, datetime(2026, 2, 14), 1)],
    pnl=31.000000000000004, days=40, remarks="rode it",
)  # fmt: skip
# Open, T1 planned, date as an Excel serial number.
OPEN = momentum_row("ZZOPEN", 50, 10, 500, excel_serial(date(2026, 3, 2)), plans=[60])
# No date, and Enter Price x qty (400) disagrees with Total Amount (401).
UNDATED = momentum_row("ZZNODATE", 200, 2, 401, None)


def momentum_sheet(*rows: dict) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(MOMENTUM_HEADERS)
    for row in rows:
        ws.append([row.get(h) for h in MOMENTUM_HEADERS])
    return save(wb)


GROWW_HEADERS = [
    "Stock name", "Symbol", "ISIN", "Type", "Quantity", "Value", "Exchange", "Exchange Order Id",
    "Execution date and time", "Order status",
]  # fmt: skip
ZZLONG_ISIN = "INE0ZZ000001"


def order(side, qty, value, order_id, when, status="Executed", exchange="NSE") -> list:
    return ["ZZ LONG LTD", "ZZLONG", ZZLONG_ISIN, side, float(qty), value, exchange, order_id,
            when, status]  # fmt: skip


# Two buys, then a sale of 5 that FIFO splits 4 (closing the first lot) + 1. A cancelled order.
ORDERS = [
    order("BUY", 4, 400.0, "1000000000000001", "05-01-2026 09:30 AM"),
    order("BUY", 6, 660.0, "1000000000000002", "06-01-2026 10:00 AM"),
    order("BUY", 1, 120.0, "1000000000000003", "07-01-2026 11:00 AM", status="Cancelled"),
    order("SELL", 5, 600.0, "1000000000000004", "10-01-2026 02:00 PM"),
]


def groww_orders(*orders: list) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Name", "A. Person"])  # the real export starts with account details
    ws.append(["Unique Client Code", "0000000000"])
    ws.append([])
    ws.append(["Order History from 01-01-2026 to 31-01-2026"])
    ws.append([])
    ws.append(GROWW_HEADERS)
    for row in orders:
        ws.append(row)
    return save(wb)


def save(wb) -> bytes:
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
