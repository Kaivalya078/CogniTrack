from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user_id
from app.core.db import get_session
from app.ingest.commit import CommitRefused, commit_batch
from app.ingest.staging import check, history, stage
from app.ledger.pnl import exit_outcome, realised
from app.models.instruments import Instrument
from app.models.staging import StagingBatch, StagingItem

router = APIRouter(prefix="/staging")

SessionDep = Annotated[Session, Depends(get_session)]
UserDep = Annotated[int, Depends(current_user_id)]
MAX_UPLOAD = 5 * 1024 * 1024  # my files are ~10 KB
STATUS_ORDER = {"conflict": 1, "changed": 2, "new": 3, "unchanged": 4}


class ItemOut(BaseModel):
    id: int
    row_ref: str
    kind: str
    symbol: str | None  # the matched NSE symbol
    payload: dict[str, Any]  # money as strings
    match_status: str
    diff: list[str]
    needs_input: list[str]
    warnings: list[str]
    status: str
    open_qty: int | None
    realised: str | None  # gross, on this item's exits
    outcomes: list[str]  # per exit, labelled from prices (exit_outcome)


class BatchOut(BaseModel):
    id: int
    importer: str
    filename: str
    status: str
    created_at: datetime
    items: list[ItemOut]


class BatchSummary(BaseModel):
    id: int
    importer: str
    filename: str
    status: str
    created_at: datetime


class Target(BaseModel):
    label: str = Field(pattern=r"^T[1-9]$")
    price: Decimal = Field(gt=0)


class ItemPatch(BaseModel):
    """Only the fields sent are changed; null clears one."""

    opened_on: date | None = None
    stop: Decimal | None = Field(default=None, gt=0)
    targets: list[Target] | None = None
    thesis: str | None = None
    review_trigger: str | None = None
    amount: Decimal | None = Field(default=None, ge=0)  # cash items
    as_of: date | None = None  # cash items
    status: Literal["pending", "skipped"] | None = None


def item_out(item: StagingItem, symbol: str | None) -> ItemOut:
    p = item.payload
    open_qty = realised_ = None
    outcomes = []
    if item.kind == "lot":
        try:
            h = history(p)
            open_qty, realised_ = h.open_qty, f"{realised(h).gross:.2f}"
            stop = p["stop"] and Decimal(p["stop"])
            outcomes = [exit_outcome(h.avg_cost, e.price, stop) for e in h.exits]
        except ValueError:
            pass  # sold more than bought: already a conflict on the item
    return ItemOut(
        id=item.id,
        row_ref=item.row_ref,
        kind=item.kind,
        symbol=symbol,
        payload=p,
        match_status=item.match_status,
        diff=item.diff,
        needs_input=item.needs_input,
        warnings=item.warnings,
        status=item.status,
        open_qty=open_qty,
        realised=realised_,
        outcomes=outcomes,
    )


def get_batch(session: Session, user_id: int, batch_id: int) -> StagingBatch:
    batch = session.get(StagingBatch, batch_id)
    if batch is None or batch.user_id != user_id:
        raise HTTPException(404, f"No staging batch {batch_id}")
    return batch


def batch_out(session: Session, batch: StagingBatch) -> BatchOut:
    rows = session.execute(
        select(StagingItem, Instrument.symbol)
        .outerjoin(Instrument, StagingItem.instrument_id == Instrument.id)
        .where(StagingItem.batch_id == batch.id)
    ).all()
    # Needs input first, then conflicts, changes, new, and unchanged last.
    rows.sort(key=lambda r: (not r[0].needs_input, STATUS_ORDER[r[0].match_status], r[0].id))
    return BatchOut(
        id=batch.id,
        importer=batch.importer,
        filename=batch.filename,
        status=batch.status,
        created_at=batch.created_at,
        items=[item_out(item, symbol) for item, symbol in rows],
    )


@router.post("/batches")
def upload(
    filename: str,
    data: Annotated[bytes, Body(media_type="application/octet-stream")],
    session: SessionDep,
    user_id: UserDep,
) -> BatchOut:
    """Upload a file as the raw request body (no multipart): ?filename=momentum.xlsx"""
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "File too large")
    try:
        batch = stage(session, user_id, data, filename)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    session.commit()
    return batch_out(session, batch)


@router.get("/batches")
def list_batches(session: SessionDep, user_id: UserDep) -> list[BatchSummary]:
    batches = session.scalars(
        select(StagingBatch)
        .where(StagingBatch.user_id == user_id)
        .order_by(StagingBatch.id.desc())
        .limit(20)
    )
    return [BatchSummary.model_validate(b, from_attributes=True) for b in batches]


@router.get("/batches/{batch_id}")
def read_batch(batch_id: int, session: SessionDep, user_id: UserDep) -> BatchOut:
    return batch_out(session, get_batch(session, user_id, batch_id))


@router.patch("/items/{item_id}")
def edit_item(item_id: int, body: ItemPatch, session: SessionDep, user_id: UserDep) -> ItemOut:
    item = session.get(StagingItem, item_id)
    if item is None or item.user_id != user_id:
        raise HTTPException(404, f"No staging item {item_id}")
    if get_batch(session, user_id, item.batch_id).status != "pending":
        raise HTTPException(409, "This batch is no longer pending")
    changes = body.model_dump(exclude_unset=True, mode="json")  # dates and money as strings
    if status := changes.pop("status", None):
        item.status = status
    allowed = (
        {"amount", "as_of"}
        if item.kind == "cash"
        else set(ItemPatch.model_fields)
        - {
            "amount",
            "as_of",
        }
    )
    if unknown := set(changes) - allowed:
        raise HTTPException(422, f"Not editable on a {item.kind} item: {sorted(unknown)}")
    payload = dict(item.payload) | changes
    if "opened_on" in changes:  # the sheet's undated buy happened on that day
        payload["buys"] = [b | {"date": b["date"] or changes["opened_on"]} for b in payload["buys"]]
    item.payload = payload
    check(session, item)
    session.commit()
    symbol = item.instrument_id and session.get(Instrument, item.instrument_id).symbol
    return item_out(item, symbol)


@router.post("/batches/{batch_id}/commit")
def commit(batch_id: int, session: SessionDep, user_id: UserDep) -> BatchOut:
    """Write the batch into the ledger, all or nothing. 409 lists what still blocks it."""
    batch = get_batch(session, user_id, batch_id)
    try:
        commit_batch(session, batch)
    except CommitRefused as e:
        session.rollback()
        raise HTTPException(409, e.problems) from e
    session.commit()
    return batch_out(session, batch)


@router.post("/batches/{batch_id}/discard")
def discard(batch_id: int, session: SessionDep, user_id: UserDep) -> BatchSummary:
    batch = get_batch(session, user_id, batch_id)
    if batch.status != "pending":
        raise HTTPException(409, f"Batch {batch_id} is already {batch.status}")
    batch.status = "discarded"
    session.commit()
    return BatchSummary.model_validate(batch, from_attributes=True)
