"""The only code that writes the ledger: committing a staging batch I confirmed.

All or nothing: every item is re-checked first (another batch may have been committed since this
one was staged), and if any pending item still needs input or conflicts, nothing is written.
The caller commits the session.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.ingest.staging import check
from app.models.ledger import CashBalance, Lot, SellAllocation, Strategy, Transaction
from app.models.staging import StagingBatch, StagingItem
from app.models.users import Account


class CommitRefused(Exception):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


def commit_batch(session: Session, batch: StagingBatch) -> None:
    if batch.status != "pending":
        raise CommitRefused([f"batch {batch.id} is already {batch.status}"])
    items = session.scalars(
        select(StagingItem)
        .where(StagingItem.batch_id == batch.id, StagingItem.status == "pending")
        .order_by(StagingItem.id)
    ).all()
    for item in items:
        check(session, item)
    problems = [
        f"{label(item)}: {'conflict' if item.match_status == 'conflict' else 'needs'} "
        + ", ".join(item.diff if item.match_status == "conflict" else item.needs_input)
        for item in items
        if item.match_status == "conflict" or item.needs_input
    ]
    if problems:
        raise CommitRefused(problems)

    user_id = batch.user_id
    accounts = {
        a.broker: a.id for a in session.scalars(select(Account).where(Account.user_id == user_id))
    }
    strategies = {
        s.name: s.id
        for s in session.scalars(
            select(Strategy).where(Strategy.user_id == user_id, Strategy.status == "active")
        )
    }
    sales: dict[str, Transaction] = {}  # source_ref -> sale created in this commit
    for item in items:
        item.status = "committed"
        if item.kind == "cash":
            write_cash(session, user_id, accounts, item)  # an empty one becomes "skipped"
        elif item.match_status != "unchanged":
            write_lot(session, user_id, accounts, strategies, sales, item)
    batch.status = "committed"
    batch.committed_at = datetime.now(UTC)
    session.flush()


def label(item: StagingItem) -> str:
    return f"{item.payload.get('symbol', 'cash')} ({item.row_ref})"


def write_cash(session, user_id, accounts, item) -> None:
    p = item.payload
    if p["amount"] is None:
        item.status = "skipped"
        return
    stmt = insert(CashBalance).values(
        user_id=user_id,
        account_id=accounts[p["account"]],
        as_of=date.fromisoformat(p["as_of"]),
        amount=Decimal(p["amount"]),
        source="manual",
    )
    session.execute(
        stmt.on_conflict_do_update(
            constraint="uq_cash_balances_account_id", set_={"amount": stmt.excluded.amount}
        )
    )


def write_lot(session, user_id, accounts, strategies, sales, item) -> None:
    p = item.payload
    if item.lot_id is None:
        qty = sum(b["qty"] for b in p["buys"])
        cost = sum(b["qty"] * Decimal(b["price"]) for b in p["buys"])
        lot = Lot(
            user_id=user_id,
            instrument_id=item.instrument_id,
            strategy_id=strategies[p["strategy"]],
            account_id=accounts[p["account"]],
            opened_on=date.fromisoformat(p["opened_on"]),
            date_confidence=p["date_confidence"],
            qty_initial=qty,
            qty_open=qty,
            avg_cost=cost / qty,
            stop_price=p["stop"] and Decimal(p["stop"]),
            targets=p["targets"],
            thesis=p["thesis"],
            review_trigger=p["review_trigger"],
            remarks=p["remarks"],
            status="open",
        )
        session.add(lot)
        session.flush()
        item.lot_id = lot.id
        for b in p["buys"]:
            session.add(
                txn(user_id, item, b, "buy", lot_id=lot.id, day=b["date"] or p["opened_on"])
            )
        recorded: set[str] = set()
    else:
        lot = session.get(Lot, item.lot_id)
        planned = {t["label"]: t for t in lot.targets} | {t["label"]: t for t in p["targets"]}
        lot.targets = sorted(planned.values(), key=lambda t: t["label"])
        for field in ("thesis", "review_trigger", "remarks"):
            if p[field] is not None:
                setattr(lot, field, p[field])
        if p["stop"] is not None:
            lot.stop_price = Decimal(p["stop"])
        recorded = set(
            session.scalars(
                select(Transaction.source_ref)
                .join(SellAllocation, SellAllocation.sell_txn_id == Transaction.id)
                .where(SellAllocation.lot_id == lot.id)
            )
        )

    for e in p["exits"]:
        if e["source_ref"] in recorded:
            continue
        # A sale split across lots (FIFO) arrives as one exit per lot: one transaction in total.
        sale = sales.get(e["source_ref"])
        if sale is None:
            sale = sales[e["source_ref"]] = txn(user_id, item, e, "sell")
            sale.qty, sale.charges = 0, Decimal(0)
            session.add(sale)
        sale.qty += e["qty"]
        sale.charges += Decimal(e["charges"])
        session.flush()
        session.add(
            SellAllocation(user_id=user_id, sell_txn_id=sale.id, lot_id=lot.id, qty=e["qty"])
        )
        lot.qty_open -= e["qty"]
        lot.status = "closed" if lot.qty_open == 0 else "open"
    session.flush()


def txn(user_id, item, fill, kind, lot_id=None, day=None) -> Transaction:
    return Transaction(
        user_id=user_id,
        instrument_id=item.instrument_id,
        lot_id=lot_id,
        kind=kind,
        trade_date=date.fromisoformat(day or fill["date"]),
        qty=fill["qty"],
        price=Decimal(fill["price"]),
        charges=Decimal(fill["charges"]),
        charges_estimated=fill["charges_estimated"],
        source=fill["source"],
        source_ref=fill["source_ref"],
    )
