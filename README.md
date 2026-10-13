# CogniTrack

A personal investment-intelligence app (PortfolioOS): live dashboard, daily briefs, and later a
chatbot over my own portfolio ledger. It never places trades. See `CLAUDE.md` for the full design.

## Prerequisites

| Tool | Check |
| --- | --- |
| Docker Desktop | `docker compose version` |
| uv | `uv --version` (installs Python 3.12 itself) |
| Node 22.12+ | `node --version` |

## Run locally

All commands are run from the repo root unless a `cd` is shown.

```sh
# 1. Settings: copy the template and set a real password (.env is gitignored).
#    If a Postgres installed on your machine already uses port 5432, set POSTGRES_PORT=5433
#    and change the port in DATABASE_URL to match.
cp .env.example .env

# 2. Database (Postgres 16 in Docker)
docker compose -f infra/docker-compose.yml --env-file .env up -d

# 3. Backend: install, migrate, serve on http://localhost:8000
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload

# 4. Frontend (second terminal): serve on http://localhost:5173, proxies /api to the backend
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The card shows API and DB health.

## Tests and lint

```sh
cd backend
uv run ruff check && uv run ruff format --check
uv run pytest          # needs the Postgres from step 2
```

```sh
cd frontend
npm run build          # type-check and production build
```

CI (`.github/workflows/ci.yml`) runs all of these on every push, against a throwaway Postgres.

## Instruments (NSE symbols)

```sh
cd backend
uv run python -m app.market.instruments              # load NSE's equity list (re-run to refresh)
uv run python -m app.ingest.resolve_names            # does every name in my sheets resolve?
uv run python -m app.ingest.resolve_names --confirm  # confirm the fuzzy matches one by one
```

The list comes from `EQUITY_L.csv` on nsearchives.nseindia.com. That URL is not an official API
and has moved before; if the download fails, find the current link on nseindia.com and update
`EQUITY_LIST_URL` in `app/market/instruments.py`. Confirmed matches are saved as aliases. The API
offers the same through `GET /api/instruments/match?name=...` and `POST /api/instruments/aliases`
(try them at http://localhost:8000/docs).

`resolve_names` reads the sheets in `backend/tests/fixtures/private/` (gitignored).

## Importing trades (staging)

Nothing writes the ledger directly. Open http://localhost:5173/#/staging and upload:

| File | Becomes |
| --- | --- |
| Momentum sheet (`momentum portfolio.xlsx`) | momentum lots in Zerodha |
| Groww order history (Groww: Stocks > Orders > Download, .xlsx) | long-term lots in Groww, one per buy; sales matched to lots oldest first |

Each row becomes a staging item marked `new`, `unchanged`, `changed` or `conflict`. Fill in what
it asks for (an open momentum lot needs T1 and a stop), skip what you don't want, then
**Commit to ledger**. A commit is all or nothing. Re-uploading a newer version of either file is
safe: only new rows and new exits are added, and an edited past row shows as a conflict instead
of being applied. The cash card (unutilised funds) is optional.

Charges are estimated from Zerodha's and Groww's published delivery rates (checked 13 Oct 2026,
`app/ledger/charges.py`) and marked `charges_estimated`. Brokers change these: re-check now and then.

```sh
cd backend
uv run python -m app.ledger.summary --as-of 2026-10-12   # headline numbers from the ledger
uv run pytest -m private                                 # golden numbers on my real files
```

## Database migrations

Schema changes only go through Alembic:

```sh
cd backend
uv run alembic revision -m "describe the change"   # then edit the new file in migrations/versions
uv run alembic upgrade head
```

## Deploy

The app runs on an Oracle Cloud Arm VM reachable only over Tailscale. Step-by-step setup,
backups, the restore test and updating are in [`docs/deploy.md`](docs/deploy.md). In short, on
the VM:

```sh
cd ~/CogniTrack && git pull
docker compose -f infra/docker-compose.prod.yml --env-file .env up -d --build
infra/backup.sh                                   # also runs nightly from cron
infra/restore-test.sh /var/backups/cognitrack/<file>.dump
```
