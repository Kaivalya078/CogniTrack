"""Match a name from a sheet or a statement to an NSE instrument.

Order: a confirmed alias, then an exact symbol, then an exact company name, then a fuzzy ranking.
Only the first three resolve a name on their own; fuzzy candidates need my confirmation, which is
saved as an alias so the name resolves exactly from then on.
"""

import re
from dataclasses import dataclass
from typing import Literal

from rapidfuzz import fuzz, process
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.instruments import Instrument, InstrumentAlias

Method = Literal["alias", "symbol", "name", "fuzzy"]
EXACT_METHODS: frozenset[Method] = frozenset({"alias", "symbol", "name"})


@dataclass(frozen=True)
class Candidate:
    instrument: Instrument
    score: float  # 0-100
    method: Method


def normalise(name: str) -> str:
    """'Sky Gold & Diamonds Ltd.' -> 'sky gold and diamonds'."""
    name = name.casefold().replace("&", " and ")
    name = re.sub(r"[^a-z0-9 ]", " ", name)
    name = re.sub(r"\b(limited|ltd)\b", " ", name)
    return " ".join(name.split())


def match(
    query: str,
    instruments: list[Instrument],
    aliases: dict[str, Instrument],
    limit: int = 5,
) -> list[Candidate]:
    """Rank instruments for `query`. Pure: no I/O. `aliases` maps alias_norm -> instrument."""
    q = normalise(query)
    if not q:
        return []
    if q in aliases:
        return [Candidate(aliases[q], 100.0, "alias")]
    symbol = query.strip().upper()
    for inst in instruments:
        if inst.symbol == symbol:
            return [Candidate(inst, 100.0, "symbol")]
    same_name = [i for i in instruments if normalise(i.name) == q]
    if len(same_name) == 1:
        return [Candidate(same_name[0], 100.0, "name")]

    # Score each instrument by its better match: company name (token_set_ratio copes with
    # abbreviations like "ICICI Prud.Asset Man") or symbol (brand names like "PolicyBazaar").
    names = {n: normalise(i.name) for n, i in enumerate(instruments)}
    symbols = {n: i.symbol.casefold() for n, i in enumerate(instruments)}
    scores: dict[int, float] = {}
    for choices, scorer, text in (
        (names, fuzz.token_set_ratio, q),
        (symbols, fuzz.ratio, q.replace(" ", "")),
    ):
        for _, score, n in process.extract(text, choices, scorer=scorer, limit=limit):
            scores[n] = max(scores.get(n, 0.0), score)
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], instruments[kv[0]].symbol))
    return [Candidate(instruments[n], round(s, 1), "fuzzy") for n, s in ranked[:limit]]


def load_choices(session: Session, user_id: int) -> tuple[list[Instrument], dict[str, Instrument]]:
    """Active instruments and this user's confirmed aliases, ready for match()."""
    instruments = list(session.scalars(select(Instrument).where(Instrument.active)))
    rows = session.execute(
        select(InstrumentAlias.alias_norm, Instrument)
        .join(Instrument, InstrumentAlias.instrument_id == Instrument.id)
        .where(InstrumentAlias.user_id == user_id)
    )
    return instruments, {alias_norm: inst for alias_norm, inst in rows}


def confirm_alias(session: Session, user_id: int, alias: str, instrument_id: int) -> None:
    """Remember that `alias` means this instrument. Re-confirming replaces the old answer."""
    stmt = insert(InstrumentAlias).values(
        user_id=user_id, instrument_id=instrument_id, alias=alias, alias_norm=normalise(alias)
    )
    session.execute(
        stmt.on_conflict_do_update(
            constraint="uq_instrument_aliases_user_id",
            set_={"instrument_id": stmt.excluded.instrument_id, "alias": stmt.excluded.alias},
        )
    )
