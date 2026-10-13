"""Check that every stock name in my sheets resolves to an NSE instrument.

Reads column A below the "Stock" header of every worksheet (both my sheets use that layout) and
matches each name. With --confirm, asks about each fuzzy match and saves the answer as an alias.
This only reads names: the real importers (M3) read everything else.

    uv run python -m app.ingest.resolve_names            # report
    uv run python -m app.ingest.resolve_names --confirm  # report and confirm fuzzy matches
"""

import argparse
from pathlib import Path

import openpyxl
from sqlalchemy import select

from app.api.deps import OWNER_USER_ID
from app.core.db import SessionLocal
from app.ingest.matching import EXACT_METHODS, confirm_alias, load_choices, match
from app.models.instruments import Instrument

PRIVATE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "private"


def stock_names(path: Path) -> list[str]:
    names = []
    for ws in openpyxl.load_workbook(path, read_only=True, data_only=True).worksheets:
        in_table = False
        for (cell,) in ws.iter_rows(min_col=1, max_col=1, values_only=True):
            text = str(cell).strip() if cell is not None else ""
            if not in_table:
                in_table = text == "Stock"
            elif not text or text.upper() == "TOTAL":
                break
            else:
                names.append(text)
    return names


def unresolved_names(paths: list[Path], confirm: bool) -> list[str]:
    names = list(dict.fromkeys(n for p in paths for n in stock_names(p)))
    unresolved = []
    with SessionLocal() as session:
        instruments, aliases = load_choices(session, OWNER_USER_ID)
        for name in names:
            candidates = match(name, instruments, aliases)
            if candidates and candidates[0].method in EXACT_METHODS:
                best = candidates[0]
                print(f"  ok  {name:24} -> {best.instrument.symbol} ({best.method})")
                continue
            print(
                f"  ??  {name:24} -> "
                + ", ".join(f"{c.instrument.symbol} {c.score:g}" for c in candidates[:3])
            )
            chosen = ask(name, candidates, session) if confirm else None
            if chosen is None:
                unresolved.append(name)
                continue
            confirm_alias(session, OWNER_USER_ID, name, chosen.id)
            session.commit()
            print(f"      confirmed {name!r} -> {chosen.symbol}")
    return unresolved


def ask(name, candidates, session) -> Instrument | None:
    for n, c in enumerate(candidates, 1):
        print(f"      {n}. {c.instrument.symbol:12} {c.instrument.name} ({c.score:g})")
    while True:
        answer = input("      number, an NSE symbol, or Enter to skip: ").strip()
        if not answer:
            return None
        if answer.isdigit() and 1 <= int(answer) <= len(candidates):
            return candidates[int(answer) - 1].instrument
        found = session.scalar(select(Instrument).where(Instrument.symbol == answer.upper()))
        if found is not None:
            return found
        print(f"      {answer!r} is not a listed symbol")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="*", type=Path, help="default: tests/fixtures/private")
    parser.add_argument("--confirm", action="store_true", help="ask about fuzzy matches")
    args = parser.parse_args()

    paths = args.files or sorted(PRIVATE_DIR.glob("*.xlsx"))
    if not paths:
        raise SystemExit(f"No .xlsx files given or in {PRIVATE_DIR}")
    unresolved = unresolved_names(paths, args.confirm)
    if unresolved:
        raise SystemExit(f"{len(unresolved)} name(s) not resolved: {', '.join(unresolved)}")
    print("Every name resolves.")


if __name__ == "__main__":
    main()
