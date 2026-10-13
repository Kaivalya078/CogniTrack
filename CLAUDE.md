# PortfolioOS

A personal investment-intelligence app that replaces my two Excel portfolio trackers with a
live dashboard, daily briefs and (later) a chatbot. It monitors, records and analyses my
investments. It never places trades: my brokers stay where I trade.

I am building this to use it and to learn. When you make a non-obvious choice (Docker, the VM,
migrations, an architecture decision), explain it in two or three sentences.

## How to work with me

- Build one milestone at a time (see Milestones). Do not start features from a later milestone.
- At the start of each milestone, write a short plan (files, tables, endpoints, tests) and wait
  for my go-ahead before coding.
- At the end of each milestone, stop and show me how to verify the "done when" condition.
- Ask before adding any dependency that is not in the Tech stack table.
- Small, focused commits. Run `ruff` and `pytest` before every commit.
- When something depends on an unofficial or changeable source (yfinance, NSE URLs), say so in
  the code and in your summary.

## Non-negotiable rules

1. **The ledger is the source of truth.** Brokers, files, screenshots and chat feed it; none of
   them is the record.
2. **Nothing writes to the ledger directly.** Every import, extraction and chat update becomes a
   staging item. The ledger is written in exactly one place: committing a batch I confirmed.
3. **Code computes, the LLM explains.** Every number comes from Python. The LLM (later) only
   interprets facts passed to it through tools, and never queries the database directly.
4. **Money is exact.** `Decimal` in Python, `NUMERIC` in Postgres. Never floats. Round only for
   display.
5. **Every transaction records its origin:** `source` (contract_note, broker_report, sheet,
   screenshot, chat, opening_balance), `source_ref`, `charges_estimated`, and the lot's
   `date_confidence` (exact, approximate, unknown). The UI must be able to say how much of a
   number rests on exact data.
6. **No invented explanations.** If a move has no identifiable cause, or simply followed its
   sector, the app says so.
7. **Replaceable data sources.** Every price source implements `PriceProvider`; every file
   format implements `Importer`. Swapping one never touches the rest of the app.
8. **Jobs are idempotent.** Re-running a date replaces its provisional results; it never
   duplicates rows. Missed days are filled by a backfill command.
9. **Secrets live in `.env`**, never in git. `.env.example` lists every setting with no real
   values. My real spreadsheets and statements are never committed.
10. **Every table carries `user_id`** even though there is one user for now, so friends can be
    added later without a rewrite. Multi-user features themselves are out of scope.

## Tech stack

| Layer | Choice |
| --- | --- |
| Backend | Python 3.12, FastAPI, Pydantic v2, pydantic-settings |
| Packaging | uv (lockfile committed) |
| Database | PostgreSQL 16 (pgvector later, for news matching) |
| ORM / migrations | SQLAlchemy 2.0 (typed, 2.0 style), Alembic; psycopg 3 driver |
| Scheduler | APScheduler in its own container, timezone `Asia/Kolkata` |
| Data handling | pandas, openpyxl |
| Name matching | rapidfuzz |
| Market data | NSE bhavcopy (primary), yfinance with `.NS` symbols (backfill and fallback) |
| PDF parsing (M7+) | pdfplumber |
| Frontend | React, TypeScript, Vite, TanStack Query, Tailwind CSS |
| Charts | TradingView Lightweight Charts (price charts), ECharts (everything else) |
| AI (M10+) | OpenAI SDK with GPT-4o mini, behind an `LLMClient` interface so the model can be swapped |
| Quality | pytest, ruff, GitHub Actions |
| Infrastructure | Docker Compose, Caddy, Tailscale |
| Hosting | Oracle Cloud Always Free Arm VM (arm64) |

Deliberately excluded: Redis, Celery, Kubernetes (not needed for one user); paid data APIs.
Groww's trade API (paid after a trial) and DhanHQ's Data API (₹499/month, and Dhan's API only
sees Dhan accounts) are not used. Zerodha's Kite Connect Personal API is free but optional and
comes much later.

## Architecture

A modular monolith: one Python codebase running as two processes, `api` (FastAPI) and
`scheduler` (APScheduler), sharing one Postgres. Caddy serves the built React app and proxies
`/api`. Access is over Tailscale only; no public ports.

```
backend/app/
  core/        settings, db session, logging, date helpers (trade dates IST, timestamps UTC)
  models/      SQLAlchemy tables
  ledger/      lots, sell allocations, P&L math — pure functions, no I/O
  ingest/      importers/, staging, matching, the single commit into the ledger
  market/      providers/, trading calendar, corporate actions
  analytics/   daily snapshots, what drove each day, trade statistics
  jobs/        scheduler entry point, end-of-day job, backfill CLI
  api/         FastAPI routers
  agent/       (M10+) LLM tools that call ledger/analytics functions
backend/migrations/   Alembic revisions
backend/tests/fixtures/            synthetic sample files, committed
backend/tests/fixtures/private/    my real sheets, gitignored
frontend/src/  pages/ (Dashboard, Lot, Staging, Strategies, Settings), components/, api/
infra/         docker-compose.yml, docker-compose.prod.yml, Caddyfile, backup.sh
```

The two core interfaces:

```python
class PriceProvider(Protocol):
    name: str
    def eod_prices(self, day: date) -> list[PriceBar]: ...
    def history(self, symbol: str, start: date, end: date) -> list[PriceBar]: ...

class Importer(Protocol):
    source: str  # "momentum_sheet", "groww_order_history", "zerodha_console_xlsx", ...
    def detect(self, data: bytes, filename: str) -> bool: ...
    def parse(self, data: bytes, filename: str) -> list[ProposedItem]: ...
```

Importers only return staging items. They never touch ledger tables.

## Domain model

**Strategy lives on the lot, not on the broker or the stock.** Each purchase is a lot with its
own strategy, target ladder, stop and optional thesis. The broker account is just where the lot
sits (any broker, or none). A position is the roll-up of a stock's open lots. One stock can be
held under two strategies at once as two separate lots that are never merged.

Core tables (phase 1):

| Table | Key columns |
| --- | --- |
| users | id, name |
| accounts | user_id, broker (zerodha, groww, other, none), label |
| instruments | symbol, isin, name, series, sector, active |
| instrument_aliases | instrument_id, alias (remembers confirmed name matches) |
| strategies | user_id, name, version, config JSONB, status, supersedes_id |
| lots | user_id, instrument_id, strategy_id, account_id, opened_on, date_confidence, qty_initial, qty_open, avg_cost, stop_price, targets JSONB, thesis, status |
| transactions | lot_id, kind (buy, sell, dividend, bonus, split, charge), trade_date, qty, price, charges, charges_estimated, source, source_ref |
| sell_allocations | sell_txn_id, lot_id, qty |
| staging_batches, staging_items | source, status, payload JSONB, match_status, diff, needs_input |
| prices_daily | instrument_id, date, open, high, low, close, volume, source |
| trading_holidays | date, description |
| corporate_actions | instrument_id, ex_date, kind, ratio, amount |
| position_snapshots, portfolio_snapshots | date, qty, close, market_value, cost, day_pnl, unrealised, realised, status (provisional, final, needs_review) |
| job_runs | job, run_date, status, started_at, finished_at, error |

P&L rules:

- Daily P&L per position: `MV_today − MV_yesterday + sell_proceeds − buy_cost + dividends`.
  A lot bought today earns (close − buy price) × qty, not the full day's move.
- Realised and unrealised are kept separate. Show gross and net of charges.
- **Strategy P&L** follows sell_allocations (which lot I said I sold). **Tax P&L** follows FIFO
  per demat account. When they disagree, the app says so before a sale (FIFO view: M7 or later).
- Corporate actions (splits, bonuses) adjust quantity and cost basis before any P&L is computed.
- Where charges are unknown, estimate them from published delivery-trade rates and set
  `charges_estimated = true`; real charges from contract notes replace estimates later.

## My strategies (seed data)

Accounts: momentum lots sit in **Zerodha**, long-term lots in **Groww**.

Momentum, as currently understood:

```yaml
strategy: momentum
account: zerodha
idea_source: advisor picks (stocks with good volume, found via a supertrend indicator)
horizon: 4–8 months
at_8_months: reassess        # not a hard exit; loss-making long drags are usually sold earlier
exits:
  targets: T1 and T2; T2 is the full expected move, T1 part of the way
  sizing: about 50% sold at T1, the rest at T2
  at_entry: T1 and stop-loss GTTs are placed as soon as the buy completes (both required)
  stop: the GTT trigger; I may sell earlier when the setup weakens ("sold before SL hit")
  runner: sometimes ride part after T2 with a GTT band   # unconfirmed, do not enforce
status: confirmed except runner
```

In the sheet, a single exit of the whole quantity is a stop-loss (or early) exit. Outcomes are
still labelled from prices (`exit_outcome`), and on the sheet the two agree. Observed in the data
(guidance, not enforced): T1's gain is usually 60–80% of T2's.

Long-term: no stop; each lot carries a thesis and a review trigger instead.

From M10, new momentum trades arrive by chat as: stock, entry price, T1, T2, SL, qty. The bot
drafts a staging item showing amount at risk, (entry − stop) × qty, and each target's
reward-to-risk multiple, and commits only after I confirm.

## My existing data (M3 input)

Two Excel files in `backend/tests/fixtures/private/` (gitignored). **Inspect a file's actual
structure before writing an importer for it; do not assume column names.**

- **Momentum sheet** (`momentum_sheet` importer, Zerodha): a trade log. One row per trade with
  symbol (NSE symbols already), entry date, entry price, quantity, total amount, up to four
  partial exits, and remarks. Dates may be Excel serials.
  - A target column holds a **planned** target when the row has no exit date, and an **actual
    exit price** when it does (including stop-loss exits, e.g. NESTLEIND at 1,362.9, and
    breakeven exits). Plans go to the lot's targets, fills to sell transactions. Outcomes are
    labelled from the data, not from the remarks (SIKA's second exit at 1,197 was essentially
    its 1,196.80 entry, though the remark says "both targets achieved").
  - Some entries are averages of several buys (AGI 744.625, RATNAVEER 180.81). They are one
    buy with `source = sheet`, cost from Total Amount; M7 splits them using Console data.
  - P&L in the sheet is gross of charges. The sheet has no stops: every open momentum lot gets
    its stop (and T1, if the sheet has none) on the staging page.
  - Open on 12 Oct 2026: ACE, PITTIENG, SOMANYCERA, SYRMA, DIFFNKG, JGCHEM, AZAD, RRKABEL
    (bought 8 Oct; the sheet has no date, entered on the staging page).
- **Groww order history** (`groww_order_history` importer, Groww, long-term): the export from
  01-04-2026, one row per order with symbol, ISIN, BUY/SELL, quantity, total value, exchange
  order id and execution time. It is the source for long-term lots; the old long-term sheet
  and screenshots are not used. One lot per buy, sales matched to lots oldest first (FIFO),
  `source = broker_report`, `source_ref` = exchange order id. Charges are estimated.
- Cash: Groww unutilised funds ₹547 on 13 Oct 2026, entered on the staging page.
- Syrma SGS and Paytm are held under both strategies, as separate lots.

Golden-number tests (marked `@pytest.mark.private`, skipped when the private fixtures are
absent; CI runs the same logic against synthetic fixtures). They run the real files through
upload, staging and commit, then read the numbers back from the ledger.

The files keep growing, so numbers are pinned to dates. All rows below reproduce exactly from
the momentum sheet of 12 Oct 2026 and the order history to 12 Oct 2026.

| Check | Expected |
| --- | --- |
| AGI realised P&L across three partial exits (gross) | ₹934.50 |
| Momentum, as of 24 Sep 2026: closed trades, realised P&L (gross) | 13, ₹4,025.09 |
| Same: win rate, average win, average loss, median duration | 8 of 13, ₹794.89, ₹466.81, 26 days |
| Momentum, as of 12 Oct 2026: closed trades, realised P&L (gross) | 15, ₹2,875.69 |
| Same: win rate, average win, average loss, median duration | 8 of 15, ₹794.89, ₹497.64, 26 days |
| Long-term on 18 Sep 2026: stocks held, invested | 22, ₹1,31,052.45 (the old sheet said ₹1,31,052.40: it rounded Lenskart and Sakar by a few paise) |
| Long-term on 12 Oct 2026: open lots, stocks, invested, realised (gross) | 31, 23, ₹1,33,381.63, −₹1,940.45 |
| Syrma SGS | Two separate lots: momentum 3 bought, 2 open; long-term 7 |

If the importer cannot reproduce a number, stop and show me the difference rather than
adjusting the logic to fit.

## Market data

- **End-of-day prices:** NSE's UDiFF CM bhavcopy (file name pattern
  `BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip`). NSE changed the format and location in
  July 2024 and may again: find the current URL from nseindia.com's all-reports page, parse by
  column name, send browser-like headers, and fail loudly into `job_runs` instead of storing
  bad data.
- **Instruments:** NSE's list of listed equities (symbol, name, ISIN). Verify the current URL.
- **History and fallback:** yfinance with `.NS` symbols. Unofficial; cache everything in
  `prices_daily`.
- **Holidays:** NSE's published trading-holiday list, stored in `trading_holidays`.
- **Corporate actions:** entered by hand in M5; automated later from NSE.
- **Intraday:** delayed polling every few minutes during market hours is enough (later
  milestone). No paid live feed.
- **Tests never hit the network.** Providers are tested against saved sample files.

## End-of-day job (M5)

Runs on every calendar day and exits early if it was not a trading day.

1. Calendar check.
2. Fetch closes for held symbols and benchmarks (Nifty 50, Nifty 500, sector indices).
3. Apply corporate actions.
4. Validate: missing symbols, a price unchanged while the index moved, a large move with no
   corporate action → `needs_review`.
5. Write position and portfolio snapshots.
6. Compute what drove the day (per position and versus benchmark).
7. Record the run in `job_runs`.

Two passes: provisional (about 16:15 IST, fallback provider) and final (about 20:00 IST from the
bhavcopy, retried next morning if not yet published). Times are settings. A final snapshot is
never overwritten. `python -m app.jobs.backfill --from YYYY-MM-DD --to YYYY-MM-DD` fills gaps.

## Milestones

| # | Build | Done when |
| --- | --- | --- |
| M0 Setup | Repo layout, Docker Compose with Postgres, FastAPI `/health` (checks DB), Alembic with users and accounts, Vite app calling `/health`, one pytest, ruff config, GitHub Actions running both | Frontend shows API health; first CI run passes |
| M1 Instruments | Load NSE equity list; alias table; rapidfuzz matcher returning ranked candidates; confirm endpoint | Every name in both sheets resolves to an NSE symbol, fuzzy matches confirmed by me |
| M2 Ledger core | lots, transactions, sell_allocations, strategies tables; pure P&L functions; strategy seed data | Golden-number logic passes on synthetic fixtures |
| M3 Import sheets | Both importers into staging; staging page to review, edit, fill targets and stops, and confirm; single commit path | The momentum sheet and the Groww order history in the ledger; golden-number tests pass on my real files; open momentum lots have T1 and a stop |
| M4 Deploy | Oracle VM (2 OCPU / 12 GB or less; Oracle halved the free Arm allowance in June 2026), SSH keys only, firewall at both cloud and VM level, Tailscale, automatic security updates, `docker-compose.prod.yml`, Caddy, nightly `pg_dump` copied off the VM, a documented restore test. Write `docs/deploy.md` as a step-by-step guide I can follow and learn from | App opens on my phone over Tailscale; a backup lands off the VM and restores cleanly |
| M5 Prices and daily job | Bhavcopy provider, yfinance backfill, holidays, manual corporate actions, two-pass EOD job, backfill CLI | Job runs unattended for five trading days; snapshots match a manual check |
| M6 Dashboard and charts | Holdings by strategy, cash, day and total P&L (gross and net), weights by cost and market value; lot page with price chart, my buy/sell markers, average cost, targets and stop; in-app alerts: stop breached without a sale, target hit, 4-month mark, 8-month review, no progress toward target | I stop updating the Excel sheets |
| M7 Console backfill | Zerodha Console XLSX importer (contract notes and tradebook, one financial year per file); match to sheet trades by symbol, date and quantity; broker data overrides prices, dates and charges, sheet keeps targets, remarks and strategy; mismatches become questions | AGI and RATNAVEER show their individual buys; realised P&L is net of real charges |

Later, each with its own plan when we get there:

- **M8 Signals:** NSE and BSE filings plus news RSS matched to holdings; Telegram bot; alerts.
- **M9 Briefs:** data-only pre-market (about 08:45 IST) and post-market briefs: overnight
  moves, filings on holdings, scheduled events, positions near target or stop, day P&L
  drivers, underperformers (versus both sector index and benchmark), strong sectors
  (outperforming over day, week and month with broad participation and above-average volume),
  FII/DII flows.
- **M10 Chatbot:** GPT-4o mini with tools over the ledger and analytics; chat trade entry with
  confirmation cards; strategy onboarding interview; versioned strategy updates.
- **M11 AI extras:** written briefs; screenshot onboarding (vision model, PaddleOCR fallback,
  matched to NSE list, totals cross-checked); exposure maps and second-order news ("AI news →
  AI hardware holding"), labelled as possible exposure and checked against the price reaction.

## AI behaviour (M10+), so early design does not block it

- Every analysis has fixed sections: facts, evidence for, evidence against, interpretation,
  uncertainty. Searching for contrary evidence is mandatory.
- My stated strategy decides what gets checked, never the verdict. If a stop was breached and I
  did not sell, the bot says so plainly.
- "Why did it move?" requires a cited cause; otherwise the answer is "no identifiable catalyst"
  or "moved with its sector".
- The bot proposes ledger and strategy changes as staging items; it never writes directly.
- Keep a test set of prompts where I am wrong (a broken thesis, a rationalised loser) and check
  the bot disagrees before any prompt change ships.
- The AI describes my own data; it does not issue buy or sell recommendations.

## Conventions

- Trade dates are Indian calendar dates (`date`); timestamps are UTC (`timestamptz`).
- Schema changes only through Alembic migrations, never by hand.
- API responses use Pydantic models; money is serialised as strings to keep precision.
- Frontend must work well at phone width; I will mostly check it on my phone.
- `README.md` stays current: how to run locally, run tests, run a backfill, and deploy.
