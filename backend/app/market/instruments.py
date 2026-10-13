"""Load NSE's list of listed equities into `instruments`.

Source: EQUITY_L.csv on nsearchives.nseindia.com. This is NOT an official API: NSE moved the file
once already (archives.nseindia.com -> nsearchives) and may again. If the download starts
failing, find the current link on nseindia.com (Market Data -> Securities available for trading).
Columns are read by name, and a short or malformed file aborts the load instead of deactivating
half the market.

    uv run python -m app.market.instruments              # download and load
    uv run python -m app.market.instruments --file x.csv # load a saved copy
"""

import argparse
import csv
import io
import urllib.request
from dataclasses import asdict, dataclass

from sqlalchemy import func, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models.instruments import Instrument

EQUITY_LIST_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
# NSE rejects requests that do not look like a browser.
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept": "text/csv,*/*",
}
COLUMNS = {"SYMBOL": "symbol", "ISIN NUMBER": "isin", "NAME OF COMPANY": "name", "SERIES": "series"}
# The real file has ~2,600 rows. Fewer than this means a truncated or wrong download.
MIN_ROWS = 1000


@dataclass(frozen=True)
class ListedEquity:
    symbol: str
    isin: str
    name: str
    series: str


def parse_equity_list(data: bytes) -> list[ListedEquity]:
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
    # NSE's headers carry leading spaces (" SERIES", " ISIN NUMBER").
    reader.fieldnames = [f.strip() for f in reader.fieldnames or []]
    missing = COLUMNS.keys() - set(reader.fieldnames)
    if missing:
        raise ValueError(f"NSE equity list is missing columns {sorted(missing)}")
    return [
        ListedEquity(**{field: row[col].strip() for col, field in COLUMNS.items()})
        for row in reader
        if row["SYMBOL"].strip()
    ]


def upsert_instruments(session: Session, equities: list[ListedEquity]) -> tuple[int, int]:
    """Insert or refresh every listed symbol; deactivate symbols no longer listed.

    Returns (rows upserted, rows deactivated).
    """
    stmt = insert(Instrument).values([asdict(e) | {"active": True} for e in equities])
    stmt = stmt.on_conflict_do_update(
        index_elements=[Instrument.symbol],
        set_={
            "isin": stmt.excluded.isin,
            "name": stmt.excluded.name,
            "series": stmt.excluded.series,
            "active": True,
            "updated_at": func.now(),
        },
    )
    session.execute(stmt)
    # ponytail: keyed on symbol, so a renamed symbol becomes a new row and the old one is
    # deactivated. Carry lots across via ISIN when symbol changes are handled (corporate actions).
    deactivated = session.execute(
        update(Instrument)
        .where(Instrument.active, Instrument.symbol.not_in([e.symbol for e in equities]))
        .values(active=False, updated_at=func.now())
    ).rowcount
    return len(equities), deactivated


def download() -> bytes:
    request = urllib.request.Request(EQUITY_LIST_URL, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--file", help="load a saved EQUITY_L.csv instead of downloading")
    args = parser.parse_args()

    if args.file:
        with open(args.file, "rb") as f:
            data = f.read()
    else:
        data = download()
    equities = parse_equity_list(data)
    if len(equities) < MIN_ROWS:
        raise SystemExit(f"Only {len(equities)} rows in the NSE equity list; refusing to load.")

    with SessionLocal.begin() as session:
        loaded, deactivated = upsert_instruments(session, equities)
    print(f"Loaded {loaded} instruments, deactivated {deactivated}.")


if __name__ == "__main__":
    main()
