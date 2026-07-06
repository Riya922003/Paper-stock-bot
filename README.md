# Paper Trading Bot

An automated paper-trading bot for 8 US stocks — `AMZN, TSLA, MSFT, AAPL, META, NVDA, GOOGL, JPM` — built on Alpaca's paper trading API, with a from-scratch backtester that proves the strategy across 6 historical periods using the exact same code that runs live.

**Status:** fully built and tested. Strategy Core, backtester, live trading loop, and dashboard are all implemented and passing 81 automated tests. See [`DELIVERABLES.md`](DELIVERABLES.md) for the full submission checklist against the original task requirements.

**Full client-facing submission document:** [Google Doc](https://docs.google.com/document/d/1tejiwQ0DlO76RFh1agO0xA8w1RNWE7kc1C-N5Pux4mU/edit?usp=sharing) — research document, platform/strategy explanations, backtest results, and the going-live checklist, written for a reviewer rather than a developer.

---

## Requirements

- **Python 3.11, 3.12, or 3.13 — not 3.14.** `pandas-ta`'s `numba` dependency doesn't support 3.14 yet; this will fail to install otherwise.
- A free [Alpaca](https://alpaca.markets) paper trading account, if you want to run live trading or fetch live data.

## Setup

```
git clone <this-repo>
cd paper-stock-bot

py -3.11 -m venv venv          # or -3.12 / -3.13
venv\Scripts\activate            # Windows. Use: source venv/bin/activate on Mac/Linux

pip install -r requirements.txt

cp .env.example .env
```

Then open `.env` and fill in:

| Variable | Required for | Notes |
|---|---|---|
| `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` | Live trading only | From your Alpaca **paper trading** dashboard → generate a **Trading API** key pair (not Broker/Market Data/Connect — those are different products) |
| `STRATEGY` | Everything | Already defaults to `trend_following` — the only fully implemented strategy right now |
| `DATABASE_URL` | Optional | Leave unset to use a local SQLite file (`storage/bot.db`). Set it to a Postgres connection string (e.g. from Neon) if you want this machine to read/write the same database a deployed dashboard uses |

Backtesting does **not** need Alpaca keys at all — it only uses `yfinance` for historical data.

## Run the tests

```
pytest
```

81 tests, no network access required, runs in a few seconds.

## Run the backtest (all 6 required periods)

```
python backtest.py
```

Downloads real historical price data and runs the strategy — unmodified — across all 6 required periods: 1 week, 1 month, 3 months, 6 months, 1 year, 3 years. Takes a few minutes (real network calls to yfinance for each period). For each period, it writes two files into `reports/`:

- `report_<period>_trend_following_summary.txt` — starting/ending capital, net P&L, return %, win rate, max drawdown, best/worst trade, slippage/commission assumptions
- `report_<period>_trend_following_trades.csv` — every completed trade, entry to exit

The 6 official results from this run are already committed in `reports/` — you don't need to re-run this unless you want fresh numbers.

## Run the live paper-trading loop

```
python run_live.py
```

Checks the market every 5 minutes during US market hours (9:30 AM–4:00 PM ET, Mon–Fri) and places real paper trades through Alpaca whenever the strategy signals one.

**This needs to keep running continuously** — it's not a one-off command. Leave the terminal open; it holds the current portfolio (cash, open positions) in memory and updates it after every trade, so closing the terminal stops the bot and loses that in-memory state (the database keeps everything that already happened, though).

## View the dashboard

```
streamlit run dashboard/app.py
```

Opens a local web UI (usually `http://localhost:8501`) showing equity curves, P&L, current positions, and the full trade/decision log — filterable by strategy and time period.

**Important:** this shows whatever's in *your* database, nothing more. If you haven't run `backtest.py` or `run_live.py` yet (or pointed `DATABASE_URL` at a database that already has data), every view will say "No portfolio snapshots yet." That's expected, not a bug — run a backtest first if you want something to look at.

## Project structure

```
core/         shared data contracts (MarketSnapshot, PortfolioState, Decision, Fill)
strategy/     the swappable rulebook -- trend_following.py is the only implemented strategy
data/         builds MarketSnapshots -- live_feed.py (Alpaca), historical_feed.py (yfinance)
portfolio/    Portfolio State updates, applied only from confirmed Fills
execution/    Order Handler -- live_adapter.py (real Alpaca orders), backtest_adapter.py (simulated)
storage/      SQLAlchemy-backed decision/fill/portfolio log (SQLite locally, Postgres when deployed)
report.py     turns logged decisions/fills into the required per-period metrics
dashboard/    Streamlit UI -- has its own minimal requirements.txt for deployment
docs/         PRD, HLD, and the original task brief -- the authoritative technical reference
tests/        81 tests, no network access required
backtest.py   entry point -- runs the strategy across all 6 required periods
run_live.py   entry point -- the live paper-trading loop
```

## Deployment

The dashboard is deployed as a public, shareable link backed by a hosted Postgres database — see `docs/PRD.md` section 16 for the full architecture and reasoning. The live trading loop and backtester are not hosted; they run locally, on whichever machine has the Alpaca credentials.

## Going live with real money

See [`DELIVERABLES.md`](DELIVERABLES.md) for the full checklist — in short, switching from paper to live is designed to be a handful of environment variable changes, not a rewrite.
