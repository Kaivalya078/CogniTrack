from pathlib import Path

import pytest
from sqlalchemy import select

from app.ingest.matching import match, normalise
from app.market.instruments import ListedEquity, parse_equity_list, upsert_instruments
from app.models.instruments import Instrument

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = parse_equity_list((FIXTURES / "nse_equity_list_sample.csv").read_bytes())
PRIVATE_SHEETS = sorted((FIXTURES / "private").glob("*.xlsx"))


def sample_instruments() -> list[Instrument]:
    return [Instrument(id=n, symbol=e.symbol, name=e.name) for n, e in enumerate(SAMPLE)]


def test_parse_strips_header_spaces():
    # The real header is "SYMBOL,NAME OF COMPANY, SERIES, ..., ISIN NUMBER, ...".
    rba = next(e for e in SAMPLE if e.symbol == "RBA")
    assert rba == ListedEquity("RBA", "INE07T201019", "Restaurant Brands Asia Limited", "EQ")


def test_parse_rejects_a_changed_format():
    with pytest.raises(ValueError, match="missing columns"):
        parse_equity_list(b"Symbol,Company\nRBA,Restaurant Brands Asia\n")


def test_normalise():
    assert normalise("Sky Gold & Diamonds Ltd.") == "sky gold and diamonds"


@pytest.mark.parametrize(
    ("name", "symbol", "method"),
    [
        ("SYRMA", "SYRMA", "symbol"),
        ("Paytm", "PAYTM", "symbol"),
        ("Syrma SGS Technology", "SYRMA", "name"),
        ("Restau. Brands Asia", "RBA", "fuzzy"),
        ("ICICI Prud.Asset Man", "ICICIAMC", "fuzzy"),  # ahead of ICICIBANK and ICICIPRULI
        ("PolicyBazaar", "POLICYBZR", "fuzzy"),  # brand name: only the symbol is close
        ("Aditya Infotech", "CPPLUS", "name"),  # company name; the symbol is the brand
    ],
)
def test_match_ranks_the_right_instrument_first(name, symbol, method):
    best = match(name, sample_instruments(), {})[0]
    assert (best.instrument.symbol, best.method) == (symbol, method)


def test_confirmed_alias_beats_everything():
    instruments = sample_instruments()
    rba = next(i for i in instruments if i.symbol == "RBA")
    [best] = match("restau  brands asia", instruments, {normalise("Restau. Brands Asia"): rba})
    assert (best.instrument.symbol, best.method) == ("RBA", "alias")


def test_upsert_refreshes_and_deactivates(session):
    upsert_instruments(session, SAMPLE)
    renamed = [
        e if e.symbol != "RBA" else ListedEquity("RBA", e.isin, "New Name", "EQ")
        for e in SAMPLE
        if e.symbol != "PAYTM"
    ]
    upsert_instruments(session, renamed)

    rows = {i.symbol: i for i in session.scalars(select(Instrument))}
    assert rows["RBA"].name == "New Name"
    assert rows["PAYTM"].active is False
    assert rows["SYRMA"].active is True


def test_match_then_confirm_then_alias(client, session):
    session.add(
        Instrument(
            symbol="ZQXWIDGETS", isin="INE000000000", name="Zqx Widgets Limited", series="EQ"
        )
    )
    session.flush()

    [best, *_] = client.get("/api/instruments/match", params={"name": "Zqx Widgts"}).json()
    assert (best["symbol"], best["method"]) == ("ZQXWIDGETS", "fuzzy")

    body = {"alias": "Zqx Widgts", "instrument_id": best["instrument_id"]}
    for _ in range(2):  # confirming twice is harmless
        assert client.post("/api/instruments/aliases", json=body).status_code == 200

    [again] = client.get("/api/instruments/match", params={"name": "ZQX widgts"}).json()
    assert (again["symbol"], again["method"]) == ("ZQXWIDGETS", "alias")


def test_confirm_unknown_instrument_is_404(client):
    response = client.post("/api/instruments/aliases", json={"alias": "x", "instrument_id": -1})
    assert response.status_code == 404


@pytest.mark.private
@pytest.mark.skipif(not PRIVATE_SHEETS, reason="private sheets not present")
def test_every_name_in_my_sheets_resolves():
    # Reads the local database: run `python -m app.market.instruments` and
    # `python -m app.ingest.resolve_names --confirm` first.
    from app.ingest.resolve_names import unresolved_names

    assert unresolved_names(PRIVATE_SHEETS, confirm=False) == []
