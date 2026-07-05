# Paper Stock Trading Bot

Automated paper-trading bot for `AMZN, TSLA, MSFT, AAPL, META, NVDA, GOOGL, JPM`.
See `Trading_Bot_HLD_Approach.md` for the full design and architecture.

## Setup

1. `python -m venv .venv` then `.venv\Scripts\activate` (Windows)
2. `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and fill in your Alpaca paper trading keys
4. `python -c "from storage import db; db.init_db()"` to create the database

## Run the live paper-trading bot

```
python run_live.py
```

## Run the backtest (all 6 required periods)

```
python backtest.py
```

## View the dashboard

```
streamlit run dashboard/app.py
```

## Run tests

```
pytest
```

## Project structure

```
core/         shared data contracts (Market Snapshot, Portfolio State, Decision, Fill)
strategy/     the swappable rulebook -- mean_reversion, trend_following, breakout
data/         builds Market Snapshots (live_feed.py = Alpaca, historical_feed.py = yfinance)
portfolio/    Portfolio State updates, applied only from confirmed Fills
execution/    Order Handler -- live_adapter.py (Alpaca) and backtest_adapter.py (simulated)
storage/      SQLite Decision Log + trade history, shared by live, backtest, and dashboard
dashboard/    Streamlit UI, reads directly from storage/db.py
tests/        Strategy Core unit tests, no network required
backtest.py   entry point -- runs one strategy across all 6 required periods
run_live.py   entry point -- the live paper-trading loop
```

## Status

Design complete (see the HLD doc). Strategy thresholds and the actual
per-strategy buy/sell logic are still pending -- see "Open Items for
Review" in `Trading_Bot_HLD_Approach.md`.
