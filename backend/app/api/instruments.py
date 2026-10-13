from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import current_user_id
from app.core.db import get_session
from app.ingest.matching import Method, confirm_alias, load_choices, match
from app.models.instruments import Instrument

router = APIRouter(prefix="/instruments")

SessionDep = Annotated[Session, Depends(get_session)]
UserDep = Annotated[int, Depends(current_user_id)]


class CandidateOut(BaseModel):
    instrument_id: int
    symbol: str
    name: str
    score: float
    method: Method


class AliasIn(BaseModel):
    alias: str = Field(min_length=1)
    instrument_id: int


class AliasOut(BaseModel):
    alias: str
    instrument_id: int
    symbol: str


@router.get("/match")
def match_name(name: str, session: SessionDep, user_id: UserDep) -> list[CandidateOut]:
    """Ranked candidates for a name. method 'fuzzy' means it needs confirming."""
    return [
        CandidateOut(
            instrument_id=c.instrument.id,
            symbol=c.instrument.symbol,
            name=c.instrument.name,
            score=c.score,
            method=c.method,
        )
        for c in match(name, *load_choices(session, user_id))
    ]


@router.post("/aliases")
def confirm(body: AliasIn, session: SessionDep, user_id: UserDep) -> AliasOut:
    """Confirm that a name means this instrument. Idempotent; re-confirming replaces it."""
    instrument = session.get(Instrument, body.instrument_id)
    if instrument is None:
        raise HTTPException(404, f"No instrument with id {body.instrument_id}")
    confirm_alias(session, user_id, body.alias, instrument.id)
    session.commit()
    return AliasOut(alias=body.alias, instrument_id=instrument.id, symbol=instrument.symbol)
