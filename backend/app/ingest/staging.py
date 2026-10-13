"""Turn an uploaded file into a staging batch, and keep each item's checks current.

Every item is checked against the ledger:
    match_status  new | unchanged | changed (adds exits or plans) | conflict (never applied)
    needs_input   what I must fill in before the batch can be committed
    diff          what committing would change, or what conflicts
    warnings      worth a look, but not blocking
This module only reads the ledger. app.ingest.commit is the one place that writes it.
"""

import hashlib
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingest.importers import Importer
from app.ingest.importers.groww_order_history import GrowwOrderHistory
from app.ingest.importers.momentum_sheet import MomentumSheet
from app.ingest.matching import EXACT_METHODS, load_choices, match
from app.ledger.pnl import Fill, LotHistory, realised
from app.models.ledger import CashBalance, Lot, SellAllocation, Strategy, Transaction
from app.models.staging import StagingBatch, StagingItem
from app.models.users import Account

IMPORTERS: list[Importer] = [MomentumSheet(), GrowwOrderHistory()]


def stage(session: Session, user_id: int, data: bytes, filename: str) -> StagingBatch:
    """Parse a file into a pending batch. Raises ValueError if no importer knows the file."""
    importer = next((i for i in IMPORTERS if i.detect(data, filename)), None)
    if importer is None:
        raise ValueError(f"{filename}: not a file I know how to import")
    proposed = importer.parse(data, filename)

    batch = StagingBatch(
        user_id=user_id,
        importer=importer.source,
        filename=filename,
        sha256=hashlib.sha256(data).hexdigest(),
        status="pending",
    )
    session.add(batch)
    session.flush()
    instruments, aliases = load_choices(session, user_id)
    by_isin = {i.isin: i for i in instruments}
    for p in proposed:
        item = StagingItem(
            user_id=user_id,
            batch_id=batch.id,
            row_ref=p.row_ref,
            kind=p.kind,
            payload=p.payload,
            match_status="new",
            status="pending",
        )
        if p.kind == "lot":
            item.instrument_id = resolve(p.payload, instruments, aliases, by_isin)
        session.add(item)
        check(session, item)
    session.flush()
    return batch


def resolve(payload, instruments, aliases, by_isin) -> int | None:
    """ISIN first (broker exports), then symbol, alias or exact name. Fuzzy matches don't count:
    confirm those first (python -m app.ingest.resolve_names --confirm), then re-upload."""
    if payload.get("isin") in by_isin:
        return by_isin[payload["isin"]].id
    candidates = match(payload["symbol"], instruments, aliases)
    if candidates and candidates[0].method in EXACT_METHODS:
        return candidates[0].instrument.id
    return None


def history(payload: dict[str, Any], stop: Decimal | None = None) -> LotHistory:
    """The proposed lot as M2's LotHistory, to compute P&L and outcomes before it is committed."""

    def fill(f):
        day = f["date"] or payload["opened_on"]
        return Fill(
            day and date.fromisoformat(day), f["qty"], Decimal(f["price"]), Decimal(f["charges"])
        )

    return LotHistory(
        buys=tuple(fill(b) for b in payload["buys"]),
        exits=tuple(fill(e) for e in payload["exits"]),
        stop=stop,
    )


def check(session: Session, item: StagingItem) -> None:
    """Recompute match_status, lot_id, diff, needs_input and warnings from the payload."""
    item.lot_id, item.diff, item.needs_input = None, [], []
    item.match_status = "new"
    if item.kind == "cash":
        check_cash(session, item)
    else:
        check_lot(session, item)


def check_cash(session: Session, item: StagingItem) -> None:
    p = item.payload
    item.warnings = []
    if p["amount"] is None:
        return  # optional: an empty cash item is skipped on commit
    if p["as_of"] is None:
        item.needs_input = ["as_of"]
        return
    existing = session.scalar(
        select(CashBalance.amount)
        .join(Account, CashBalance.account_id == Account.id)
        .where(
            CashBalance.user_id == item.user_id,
            Account.broker == p["account"],
            CashBalance.as_of == date.fromisoformat(p["as_of"]),
        )
    )
    if existing is not None:
        same = existing == Decimal(p["amount"])
        item.match_status = "unchanged" if same else "changed"
        if not same:
            item.diff = [f"cash on {p['as_of']}: {existing:.2f} -> {p['amount']}"]


def check_lot(session: Session, item: StagingItem) -> None:
    p = item.payload
    warnings = list(p.get("file_warnings", []))
    needs = []
    if item.instrument_id is None:
        needs.append("instrument")
        warnings.append(
            f"No NSE instrument matches {p['symbol']!r}. Reload the NSE list or confirm the name "
            "(python -m app.ingest.resolve_names --confirm), then upload again."
        )
    try:
        lot_history = history(p)
    except ValueError as e:  # sold more than bought: the file is wrong, not just incomplete
        item.match_status, item.diff, item.needs_input, item.warnings = (
            "conflict",
            [str(e)],
            needs,
            warnings,
        )
        return

    lot = find_lot(session, item) if item.instrument_id is not None else None
    if lot is not None:
        item.lot_id = lot.id
        compare(session, item, lot)
    elif from_sheet(p) and item.instrument_id is not None:
        other = session.scalar(open_lots(item).where(Lot.qty_open > 0))
        if other is not None:
            warnings.append(
                f"Another open {p['strategy']} lot of {p['symbol']} exists "
                f"(opened {other.opened_on}): is this a duplicate?"
            )

    # What the lot will look like: the ledger's values, overridden by this item.
    if not p["opened_on"] and lot is None:
        needs.append("opened_on")
    stop = p["stop"] if p["stop"] is not None else lot and lot.stop_price
    targets = {t["label"] for t in (lot.targets if lot else [])} | {
        t["label"] for t in p["targets"]
    }
    if p["strategy"] == "momentum" and not lot_history.closed:
        # Both GTTs go in as soon as the buy completes. A first exit means T1 was there.
        if "T1" not in targets and not p["exits"]:
            needs.append("T1")
        if stop is None:
            needs.append("stop")

    sheet = p.get("sheet") or {}
    gross = realised(lot_history).gross.quantize(Decimal("0.01"))
    if sheet.get("pnl") is not None and Decimal(sheet["pnl"]) != gross:
        warnings.append(f"Sheet P&L is {sheet['pnl']}, computed {gross}")
    if sheet.get("days") is not None and p["opened_on"] and p["exits"]:
        last = max(e["date"] for e in p["exits"])
        days = (date.fromisoformat(last) - date.fromisoformat(p["opened_on"])).days
        if days != sheet["days"]:
            warnings.append(f"Sheet duration is {sheet['days']} days, computed {days}")
    item.needs_input, item.warnings = needs, warnings


def from_sheet(payload: dict[str, Any]) -> bool:
    return all(b["source"] == "sheet" for b in payload["buys"])


def open_lots(item: StagingItem):
    """Lots of this item's stock under its strategy."""
    return (
        select(Lot)
        .join(Strategy, Lot.strategy_id == Strategy.id)
        .where(
            Lot.user_id == item.user_id,
            Lot.instrument_id == item.instrument_id,
            Strategy.name == item.payload["strategy"],
        )
        .order_by(Lot.id)
    )


def find_lot(session: Session, item: StagingItem) -> Lot | None:
    """The ledger lot this item describes: by its buys' origin, else (sheet rows only, whose
    origin changes when I add a missing date) by stock, strategy and purchase date."""
    p = item.payload
    lot_id = session.scalar(
        select(Transaction.lot_id).where(
            Transaction.user_id == item.user_id,
            Transaction.kind == "buy",
            Transaction.source == p["buys"][0]["source"],
            Transaction.source_ref.in_([b["source_ref"] for b in p["buys"]]),
        )
    )
    if lot_id is not None:
        return session.get(Lot, lot_id)
    if from_sheet(p) and p["opened_on"]:
        return session.scalar(
            open_lots(item).where(Lot.opened_on == date.fromisoformat(p["opened_on"]))
        )
    return None


def fmt(f: dict[str, Any]) -> str:
    return f"{f.get('label') or 'sale'} {f['qty']} @ {Decimal(f['price']):.2f} on {f['date']}"


def compare(session: Session, item: StagingItem, lot: Lot) -> None:
    """Set match_status and diff for an item that matched an existing lot."""
    p = item.payload
    conflicts, changes = [], []

    ledger_buys = session.scalars(
        select(Transaction).where(Transaction.lot_id == lot.id, Transaction.kind == "buy")
    ).all()
    as_file = sorted(
        (b["qty"], Decimal(b["price"]).quantize(Decimal("0.000001"))) for b in p["buys"]
    )
    as_ledger = sorted((t.qty, t.price) for t in ledger_buys)
    if as_file != as_ledger:
        conflicts.append(f"buys: file {as_file}, ledger {as_ledger}")

    ledger_exits = {
        t.source_ref: (t, a.qty)
        for t, a in session.execute(
            select(Transaction, SellAllocation)
            .join(SellAllocation, SellAllocation.sell_txn_id == Transaction.id)
            .where(SellAllocation.lot_id == lot.id)
        )
    }
    for e in p["exits"]:
        found = ledger_exits.pop(e["source_ref"], None)
        if found is None:
            elsewhere = session.scalar(
                select(Transaction.id).where(
                    Transaction.user_id == item.user_id,
                    Transaction.source == e["source"],
                    Transaction.source_ref == e["source_ref"],
                )
            )
            if elsewhere is not None:
                conflicts.append(f"{fmt(e)} is already recorded against another lot")
            else:
                changes.append(f"new exit: {fmt(e)}")
            continue
        txn, qty = found
        if (txn.trade_date.isoformat(), qty, txn.price) != (
            e["date"],
            e["qty"],
            Decimal(e["price"]).quantize(Decimal("0.000001")),
        ):
            conflicts.append(
                f"{fmt(e)} in the file, but the ledger has {qty} @ {txn.price:.2f} "
                f"on {txn.trade_date}"
            )
    for txn, qty in ledger_exits.values():
        conflicts.append(
            f"the ledger has a sale of {qty} @ {txn.price:.2f} on {txn.trade_date} "
            "that the file does not"
        )

    planned = {t["label"]: t["price"] for t in lot.targets}
    for t in p["targets"]:
        if planned.get(t["label"]) is None or Decimal(planned[t["label"]]) != Decimal(t["price"]):
            changes.append(f"{t['label']} planned: {planned.get(t['label'])} -> {t['price']}")
    for field in ("stop", "thesis", "review_trigger", "remarks"):
        new, old = p.get(field), getattr(lot, "stop_price" if field == "stop" else field)
        if new is not None and (Decimal(new) != old if field == "stop" else new != old):
            changes.append(f"{field}: {old} -> {new}")

    item.match_status = "conflict" if conflicts else "changed" if changes else "unchanged"
    item.diff = conflicts or changes
