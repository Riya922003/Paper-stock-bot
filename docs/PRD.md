# Product Requirements Document
# Automated Paper Trading Bot

**Author:** Riya  
**Date:** 2026-07-04  
**Status:** Ready for implementation  
**Target reader:** AI coding agent implementing this from scratch

---

## 1. What We're Building and Why

We are building an automated stock trading bot that runs in "paper trading" mode — meaning it places simulated trades with fake money so we can prove the strategy works before risking real capital. The bot will watch 8 specific US stocks, make buy/sell decisions automatically every 5 minutes during market hours, and keep a complete log of every single decision it makes.

The most important design constraint is this: **the bot must be built so that switching to real money later is a one-line config change, not a rewrite.** Every architectural decision flows from this requirement.

The second most important constraint is: **the backtest must use the exact same strategy code that the live bot uses.** No separate backtest logic. No different rules. Same functions, same thresholds, same everything — just fed historical data instead of live data.

---

## 2. The 8 Stocks We Trade

The bot only ever trades these 8 US equities. No others. Ever.

```
AMZN, TSLA, MSFT, AAPL, META, NVDA, GOOGL, JPM
```

These are hardcoded. The bot should refuse to place orders on any other symbol.

---

## 3. The Platform: Alpaca Markets

We use **Alpaca Markets** as our broker API. This decision is final.

**Why Alpaca:**
- Paper trading and live trading use the exact same API — the only difference is the base URL and API keys. Switching to live is literally changing two environment variables.
- Commission-free US equity trading.
- Clean REST API + WebSocket streaming. Well-documented Python SDK.
- No minimum account balance for paper accounts.
- Supports fractional shares, which we need for precise position sizing with high-priced stocks like NVDA and GOOGL.

**The two modes and how they differ:**

| Mode | Base URL env var | What happens |
|---|---|---|
| Paper | `ALPACA_BASE_URL=https://paper-api.alpaca.markets` | Fake money, real market prices |
| Live | `ALPACA_BASE_URL=https://api.alpaca.markets` | Real money, real trades |

The bot reads this from environment. It never has the URL hardcoded.

**Alpaca account setup required before running:**
- Create a free Alpaca account at alpaca.markets
- Generate paper trading API key and secret
- Store them as `ALPACA_API_KEY` and `ALPACA_SECRET_KEY` in a `.env` file (see `.env.example`)

---

## 4. System Architecture

The system is made of 7 distinct components. They must be implemented as separate modules. No component is allowed to reach into another component's internals — everything passes through defined inputs and outputs.

### 4.1 The 7 Components

**Component 1: Market Snapshot**

Shared dataclasses (`MarketSnapshot`, `TickerData`) live in `core/models.py`. Two separate fetcher modules build them:
- `data/live_feed.py` — calls Alpaca's bars endpoint for live mode
- `data/historical_feed.py` — reads pre-downloaded/yfinance historical data for backtest mode, bar by bar

The snapshot must always contain, for each ticker:
- Current price (last close of the most recent completed candle)
- The last 50 candles of OHLCV data (Open, High, Low, Close, Volume)
- A flag indicating whether the data is complete or missing/stale (`is_stale`)

If a ticker's data is missing or stale, the snapshot marks it as unavailable. It does NOT silently drop the ticker or substitute fake data. It flags it. The rest of the system handles the flagged case by skipping that ticker for the cycle.

The snapshot object (`core.models.MarketSnapshot`) looks the same regardless of which fetcher built it. This is critical — the Strategy Core never knows which mode it's in.

**Component 2: Portfolio State**

`PortfolioState` and `Position` dataclasses live in `core/models.py`. The only way to mutate one is `portfolio.state.apply_fill(portfolio, fill)` in `portfolio/state.py`. It tracks:
- Current cash balance
- For each open position: ticker symbol, quantity held, entry price, timestamp of entry

**The rule:** Portfolio State is only ever updated by `apply_fill()`, called with a confirmed Fill. The strategy is not allowed to optimistically update it when it places an order. Only a real confirmed fill changes this state.

In live mode, this should be periodically synced against Alpaca's account endpoint to catch any drift. In backtest mode, it is maintained purely by `apply_fill()` fed from simulated fills.

**Component 3: Strategy Core**

This is the brain. It is a **pure function** with signature `decide(snapshot: MarketSnapshot, portfolio: PortfolioState) -> list[Decision]`, implemented once per strategy module under `strategy/`.

Pure function means: no API calls, no reading from disk, no writing to disk, no checking the current time, no randomness. It takes inputs and returns outputs. That's it. This is what makes the backtest identical to the live run — the same function, called with the same inputs, produces the same outputs every time.

The Strategy Core is a **swappable slot**, implemented as a registry in `strategy/__init__.py` (`get_strategy(name)`), keyed by the `STRATEGY` environment variable. Candidate modules: `strategy/mean_reversion.py`, `strategy/trend_following.py`, `strategy/breakout.py`. The MVP strategy described in section 5 is implemented inside `strategy/trend_following.py`. The registry is designed so that adding a new strategy later means adding a new module and one registry entry — not changing any existing strategy's code.

The Strategy Core produces one `Decision` (from `core.models`) per ticker per cycle. A Decision is always one of:
- `BUY` — with the reason
- `SELL` — with the reason
- `HOLD` — with the reason (even "no signal" is a logged decision)

**Component 4: Decision Log**

Implemented in `storage/db.py` as a single SQLite database (`storage/bot.db`) with three append-only tables: `decisions`, `fills`, and `portfolio_snapshots`. Every decision from every cycle gets written to `decisions` via `log_decision()`. No exceptions. Even "HOLD — no signal" gets logged.

This is the anti-cherry-picking mechanism. Anyone reviewing the results can see every decision the bot considered, not just the ones that led to trades. The log is the evidence that the strategy is being applied consistently.

Every row carries a `strategy` and `mode` column (e.g. `mode="live"` or `mode="backtest_1_year"`), so results from different strategies or different backtest periods share one database file without ever being mixed together in a query (see section 5 — no cherry-picking).

**Component 5: Order Handler**

This is the only component layer that talks to Alpaca. The Strategy Core never calls Alpaca directly. Only these two modules do, sharing the same function signature (`submit_order(decision, snapshot) -> Fill | None`):
- `execution/live_adapter.py` — places a real order via Alpaca REST API (paper or real depending on env vars)
- `execution/backtest_adapter.py` — simulates a fill at the open price of the next candle (not the signal candle — the next one, to avoid lookahead bias)

Whichever module `run_live.py` or `backtest.py` imports is the active backend. The Strategy Core doesn't know which one is active.

**Order failure handling:** If an order fails (network error, insufficient funds, market closed, etc.), `live_adapter.submit_order()` logs the error with full details and returns `None` instead of placing the order. It does NOT retry immediately. It does NOT throw an exception that kills the loop. On the next scheduled cycle, the strategy will re-evaluate and may place the order again naturally.

**Component 6: Report Generator**

Built entirely from `storage/db.py`'s `decisions` and `fills` tables. Never re-runs the strategy. Queries the log, slices it by `strategy` + `mode` (period), and produces the required metrics for each period, including a CSV export of the trade log for submission alongside the SQLite database.

**Component 7: Dashboard (local visibility only)**

The original task brief requires the bot to "show current holdings and profit/loss." This is satisfied with a minimal, read-only Streamlit app (`dashboard/app.py`) that queries `storage/db.py` directly — the same SQLite database both live and backtest runs write to. It has no write access and never talks to Alpaca directly; it is strictly a viewer.

This is not a general web product — no user accounts, no auth, no multi-user support (see section 14). It's a local dashboard for whoever is running the bot to see current cash, open positions with unrealized P&L, and the trade/decision history, filterable by strategy and mode. Run with `streamlit run dashboard/app.py`.

### 4.2 The Main Loop

This is what runs every 5 minutes during market hours:

```
1. Check if market is open right now (call Alpaca /v2/clock endpoint)
   → If market is closed: sleep until next scheduled time, do nothing
   
2. Build a fresh Market Snapshot for all 8 tickers
   → Flag any tickers with missing or stale data
   
3. Read current Portfolio State
   → In live mode: sync against Alpaca account first to catch any drift
   
4. Run Strategy Core with (snapshot, portfolio_state)
   → Get back one Decision per ticker
   
5. For each Decision:
   a. If it's SELL: send to the active Order Handler module (`live_adapter` or `backtest_adapter`) → get Fill → `apply_fill()` updates Portfolio State
   b. If it's BUY: check position limits first (see section 5), then same Order Handler → Fill → `apply_fill()`
   c. If it's HOLD: no order
   d. Always: write Decision to `storage/db.py` via `log_decision()`

6. Sleep until next scheduled run
```

Sell checks happen before buy checks in step 4. The Strategy Core handles this internally — it checks existing positions for exit signals before checking non-held tickers for entry signals.

---

## 5. Strategy: EMA Crossover + RSI Filter (MVP Strategy)

This is the first strategy we implement, inside `strategy/trend_following.py`. It is selected when `STRATEGY=trend_following` in the config (see `strategy/__init__.py`'s registry).

### 5.1 What this strategy is doing and why

This is a trend-following-style approach. Of three broader candidate approaches considered (mean-reversion, trend-following, breakout), trend-following was selected first for MVP; the Strategy Core's swappable design (section 4.1, Component 3) leaves room to add the others later as separate modules, per section 14's "no second strategy until the first is complete" rule.

We're looking for stocks that are showing genuine upward momentum — not just noise. The EMA crossover (9-period crossing above 21-period) tells us short-term momentum is building. The RSI filter (between 40 and 65) confirms the move is real momentum rather than an overbought spike. Together, they filter out a lot of false signals.

### 5.2 The exact rules — no ambiguity

**Data required:**
- Last 50 candles of 5-minute OHLCV data per ticker
- For backtests longer than 60 days: switch to 30-minute or 1-hour candles and adjust EMA periods proportionally (document this adjustment in the backtest report)

**Indicators to compute (per ticker, per cycle):**
- EMA(9) — 9-period Exponential Moving Average of close prices
- EMA(21) — 21-period Exponential Moving Average of close prices
- RSI(14) — 14-period Relative Strength Index of close prices

Compute these using the `pandas-ta` library. Do not implement indicator math from scratch.

**Buy signal — ALL of these must be true:**
1. EMA(9) just crossed above EMA(21) in the most recent completed candle (previous candle had EMA9 <= EMA21, current candle has EMA9 > EMA21)
2. RSI(14) is between 40 and 65 (inclusive) at the most recent completed candle
3. We do not already hold a position in this ticker
4. We have fewer than 4 open positions across all tickers
5. We have enough cash to buy the calculated position size (see section 5.3)
6. The market is confirmed open (from the market clock check in the main loop)

If all 6 are true: Decision = BUY.  
If any one is false: Decision = HOLD (log which condition failed and why).

**Sell signal — ANY of these triggers a sell:**
1. EMA(9) crosses below EMA(21) — thesis invalidated (primary exit)
2. Current price is 3% or more below the entry price — stop-loss hit
3. Current price is 6% or more above the entry price — take-profit hit

Check sells in this order: stop-loss first, take-profit second, EMA cross third. The first one that triggers wins. Log which condition triggered.

If none trigger on a held position: Decision = HOLD (log "position open, no exit signal").

### 5.3 Position Sizing

- Each position gets exactly **12.5% of total starting capital** (not 12.5% of current cash — of the original starting amount)
- Maximum **4 open positions** at any time
- This means at peak deployment we have 50% of capital at work, never more
- Use fractional shares — calculate the dollar amount, divide by current price, that's the quantity to order
- Round quantity to 2 decimal places (Alpaca supports fractional shares)

Example: starting capital $10,000 → each position = $1,250 → if NVDA is at $875, buy 1.43 shares.

### 5.4 What the Strategy Core function signature looks like

Implemented in `strategy/trend_following.py`, importing `MarketSnapshot`/`PortfolioState`/`Decision` from `core.models`:

```python
def decide(snapshot: MarketSnapshot, portfolio: PortfolioState) -> list[Decision]:
    """
    Pure function. No side effects. No I/O.
    Returns exactly one Decision per ticker in snapshot.
    """
```

Every strategy module under `strategy/` must expose a `decide` function with this exact signature — `strategy/__init__.py`'s registry depends on it.

---

## 6. Data Sources

**For live trading (`data/live_feed.py`):**
- Price data: Alpaca's `/v2/stocks/{symbol}/bars` endpoint (5-minute bars)
- Account/portfolio: Alpaca's `/v2/account` and `/v2/positions` endpoints (used for periodic reconciliation, see Component 2)
- Market hours: Alpaca's `/v2/clock` endpoint

**For backtesting (`data/historical_feed.py`):**
- Historical OHLCV data: `yfinance` Python library
- Download all data upfront before the backtest starts (not during the run)
- May cache downloaded bars locally (e.g. as Parquet) to avoid re-fetching on every run — an internal implementation detail of `historical_feed.py`, not a separate pipeline step
- For periods ≤ 60 days: use 5-minute bars
- For periods > 60 days: yfinance only provides 5-min data for the last 60 days, so use 1-hour bars and adjust EMA periods accordingly. Document this clearly in the report.

**Important:** The strategy logic does not know or care where the data came from. It only sees the standardized `MarketSnapshot` object from `core/models.py`.

---

## 7. Decision Logging Specification

Implemented in `storage/db.py` as one SQLite database (`storage/bot.db`), used for both live and backtest runs — there is no separate CSV logging path. Three tables:

**`decisions`** — written via `log_decision()`, one row per Decision per cycle, no exceptions (even HOLD):

| Field | Type | Description |
|---|---|---|
| `timestamp` | ISO 8601 datetime | When this decision was made |
| `ticker` | string | Which stock |
| `action` | enum: BUY / SELL / HOLD | What the strategy decided |
| `reason` | string | Human-readable reason, including indicator values. E.g. "EMA9 crossed above EMA21, RSI=52.3" or "Stop-loss: entry $142.00, current $137.74 (-2.99%)" or "Hold: no buy signal, RSI=71.2 (above 65)" |
| `quantity` | float | Quantity the decision calls for (0 for HOLD) |
| `strategy` | string | Which strategy module produced this (e.g. `trend_following`) |
| `mode` | string | `live`, or `backtest_{period}` (e.g. `backtest_1_year`) |

**`fills`** — written via `log_fill()`, one row per confirmed/simulated fill:

| Field | Type | Description |
|---|---|---|
| `timestamp`, `ticker`, `action`, `quantity`, `price` | — | The confirmed trade |
| `order_id` | string | Alpaca order ID (blank for simulated backtest fills) |
| `strategy`, `mode` | string | Same tagging as `decisions`, for filtering |

**`portfolio_snapshots`** — written via `save_portfolio_snapshot()` once per cycle: `cash`, `equity`, `positions_json`, `strategy`, `mode`, `timestamp`.

Note: per-decision EMA/RSI values are embedded in the `reason` text rather than stored as separate numeric columns. If a future need arises for querying/plotting indicator values independent of the reason string, extend the `decisions` table schema in `storage/db.py` — not required for the base task deliverables, which only need the reason to be human-readable and traceable.

For the final submission, `report.py`'s CSV export (see Component 6) turns the `fills` table into the required trade-log CSV per period.

---

## 8. Backtesting Requirements

### 8.1 The 6 required time periods

Run the backtest across all 6 of these periods. The same strategy, the same code, the same thresholds. Nothing changes between periods except the date range of data fed in.

| Period | Date range (from today 2026-07-04) | Data interval |
|---|---|---|
| 1 week | 2026-06-27 → 2026-07-04 | 5-minute bars |
| 1 month | 2026-06-04 → 2026-07-04 | 5-minute bars |
| 3 months | 2026-04-04 → 2026-07-04 | 5-minute bars |
| 6 months | 2026-01-04 → 2026-07-04 | 1-hour bars (5-min unavailable beyond 60d in yfinance) |
| 1 year | 2025-07-04 → 2026-07-04 | 1-hour bars |
| 3 years | 2023-07-04 → 2026-07-04 | 1-day bars |

### 8.2 How the backtester works

The backtester (`backtest.py`, root) is a custom implementation — approximately 150-200 lines. Do NOT use Backtrader, Zipline, or any other backtesting framework as a black box. The reason: we need to prove that the exact same `decide()` function runs in the backtest and in the live bot. A third-party framework wrapping the logic breaks that proof.

The backtester simulates the main loop on historical data:

1. Load historical OHLCV data via `data/historical_feed.py`
2. For each 5-minute (or hourly, or daily) timestep, in order:
   a. Build a `MarketSnapshot` from data up to and including this timestep only — no future data leaks in
   b. Run the same `strategy.<name>.decide()` function used by `run_live.py`
   c. Simulate fills via `execution/backtest_adapter.py` at the **open price of the next candle** (not the signal candle's close — this is how we avoid lookahead bias)
   d. Update simulated Portfolio State via `portfolio.state.apply_fill()`
   e. Write to `storage/db.py` (`log_decision()`, `log_fill()`, `save_portfolio_snapshot()`)
3. At end: `report.py` generates the Report for this period from `storage/db.py`

### 8.3 Slippage and fee assumptions

We assume these in every backtest. They must be documented in every report output:
- Slippage: 0.1% of trade value (both entry and exit)
- Commission: $0 (Alpaca is commission-free)
- Apply slippage by adjusting fill price: buys fill 0.1% higher than next-candle open, sells fill 0.1% lower

### 8.4 What each period's report must contain

| Metric | Description |
|---|---|
| Starting capital | Dollar amount at period start |
| Ending capital | Dollar amount at period end |
| Net P&L | Ending minus starting, in dollars |
| Return % | Net P&L / starting capital × 100 |
| Total trades | Count of completed round-trips (buy + sell pairs) |
| Winning trades | Count of trades that closed with a profit |
| Losing trades | Count of trades that closed at a loss |
| Win rate | Winning trades / total trades × 100 |
| Max drawdown | Largest peak-to-trough drop in portfolio value during the period |
| Best single trade | Ticker, entry, exit, P&L of the most profitable trade |
| Worst single trade | Ticker, entry, exit, P&L of the most losing trade |
| Slippage assumption | Stated explicitly (0.1%) |
| Commission assumption | Stated explicitly ($0) |
| Full trade log | Every completed trade: ticker, entry date, entry price, exit date, exit price, qty, P&L |

Each period outputs two files:
- `report_{period}_{strategy}_summary.txt` — human-readable summary
- `report_{period}_{strategy}_trades.csv` — machine-readable trade log

---

## 9. Real Market Constraints the Bot Must Respect

These are not design choices — they are real-world rules the bot must follow regardless of what the strategy says.

**Market hours:** The bot only places orders between 9:30 AM and 4:00 PM Eastern Time, Monday through Friday. At the start of every main loop cycle, check Alpaca's `/v2/clock` endpoint. If the market is closed, skip the cycle entirely and sleep.

**No pre-market or after-hours trading.** Even if Alpaca allows it, we don't do it.

**Pattern Day Trader (PDT) rule:** Any account under $25,000 in equity is limited to 3 day trades (same-day round-trips) in any 5-business-day rolling window. Paper accounts don't enforce this restriction, but when we document the "going live" checklist, this must be included as a risk. The bot does NOT try to count PDT violations — that's a human concern before going live.

**Cash settlement:** In a cash account, funds from a sell don't settle immediately. We paper trade in a margin account setting to avoid worrying about this for now, but the going-live checklist must flag it.

---

## 10. Path to Live Trading

When we are ready to go live (after sufficient paper track record), here is the complete list of changes required:

1. Change `ALPACA_BASE_URL` from `https://paper-api.alpaca.markets` to `https://api.alpaca.markets`
2. Change `ALPACA_API_KEY` and `ALPACA_SECRET_KEY` to the live account credentials
3. Set `STARTING_CAPITAL` to the actual amount in the live account
4. Verify account equity exceeds $25,000 OR acknowledge and accept PDT restriction before running
5. Reduce `POSITION_SIZE_PCT` from 12.5% to a lower number for the first week of live trading (manual decision, not automated)
6. Add human approval step: the bot should send a notification (email or terminal alert) before placing the first live order and wait for confirmation

**Nothing else changes.** `strategy/trend_following.py`, `storage/db.py`, `portfolio/state.py`, `report.py` — all identical. Only `execution/live_adapter.py` starts hitting the live base URL instead of paper.

---

## 11. Tech Stack

These are the technology decisions. An AI agent implementing this should use these exact libraries.

| Component | Technology |
|---|---|
| Language | Python 3.11+ |
| Alpaca integration | `alpaca-py` Python SDK |
| Historical data | `yfinance` |
| Technical indicators | `pandas-ta` |
| Data manipulation | `pandas`, `numpy` |
| Scheduler | `APScheduler` (runs the main loop every 5 minutes during market hours) |
| Database (live and backtest) | SQLite via Python's built-in `sqlite3` (`storage/db.py`) — one database, both modes, distinguished by the `mode` column |
| Environment config | `python-dotenv` (`.env` file, loaded by each entry point) |
| Testing | `pytest` |
| Local dashboard | `streamlit` (read-only viewer, see Component 7) |

No web framework or backend server is needed. The bot itself is a background process; Streamlit reads `storage/db.py` directly, it does not sit behind an API.

---

## 12. Project File Structure

This is the actual, decided module structure — an AI agent implementing this should create files here, not invent an alternative layout:

```
paper-stock-bot/
├── .env                          # API keys and config (never commit to git)
├── .env.example                  # Template showing required variables
├── .gitignore
├── requirements.txt
├── README.md
│
├── docs/                         # Task brief, HLD, this PRD, prior research — see AGENTS.md
│
├── core/
│   ├── __init__.py
│   └── models.py                 # MarketSnapshot, TickerData, PortfolioState, Position, Decision, Fill
│
├── strategy/
│   ├── __init__.py               # Registry — reads STRATEGY env var, returns the matching decide()
│   ├── mean_reversion.py         # candidate strategy, not yet implemented
│   ├── trend_following.py        # the MVP strategy: EMA(9)/EMA(21) crossover + RSI(14) filter
│   └── breakout.py               # candidate strategy, not yet implemented
│
├── data/
│   ├── __init__.py
│   ├── live_feed.py              # builds MarketSnapshot from Alpaca (live mode)
│   └── historical_feed.py        # builds MarketSnapshot from yfinance, bar-by-bar (backtest mode)
│
├── portfolio/
│   ├── __init__.py
│   └── state.py                  # apply_fill() — the only legitimate way PortfolioState changes
│
├── execution/
│   ├── __init__.py
│   ├── live_adapter.py           # submit_order() via Alpaca (paper or live)
│   └── backtest_adapter.py       # submit_order() — simulated fill from historical price
│
├── storage/
│   ├── __init__.py
│   └── db.py                     # SQLite: decisions, fills, portfolio_snapshots tables
│
├── dashboard/
│   └── app.py                    # Streamlit viewer — holdings, P&L, trade/decision history (read-only)
│
├── reports/                      # Generated backtest report output (summary .txt + trade .csv per period)
│
├── tests/
│   └── test_strategy_core.py     # Strategy Core unit tests, no network required
│
├── backtest.py                   # Entry point — runs the configured strategy across all 6 periods
├── run_live.py                   # Entry point — the live paper-trading loop (APScheduler)
└── report.py                     # NOT YET CREATED — Component 6, reads storage/db.py, writes into reports/
```

There is no `config.py` — each entry point (`run_live.py`, `backtest.py`) reads `os.getenv()` directly after `load_dotenv()`, matching the level of indirection already in the codebase.

`report.py` (Component 6) does not exist yet — create it at the repo root, alongside `backtest.py` and `run_live.py`, reading from `storage/db.py` and writing its output into `reports/`.

---

## 13. Environment Variables (.env)

All config lives here. No hardcoded values anywhere in the code.

```env
# Alpaca credentials
ALPACA_API_KEY=your_paper_api_key_here
ALPACA_SECRET_KEY=your_paper_secret_key_here
ALPACA_BASE_URL=https://paper-api.alpaca.markets

# Strategy selection
STRATEGY=trend_following

# Capital config
STARTING_CAPITAL=10000
POSITION_SIZE_PCT=0.125
MAX_POSITIONS=4

# Risk thresholds
STOP_LOSS_PCT=0.03
TAKE_PROFIT_PCT=0.06

# Strategy thresholds (EMA crossover + RSI, used inside strategy/trend_following.py)
EMA_FAST=9
EMA_SLOW=21
RSI_PERIOD=14
RSI_MIN=40
RSI_MAX=65

# Timing
CHECK_INTERVAL_MINUTES=5

# Mode
MODE=paper

# Where storage/db.py writes the SQLite database
DATABASE_PATH=storage/bot.db
```

This matches `.env.example` at the repo root exactly — keep both in sync if either changes.

---

## 14. What Is Explicitly Out of Scope

These are things we are NOT building. If an AI agent sees an opportunity to add these, it should resist.

- No web product, no user accounts, no auth, no public deployment of the dashboard — it is a local, read-only Streamlit viewer only (see Component 7), not a general web UI
- No Telegram/Slack/email notifications (except the manual approval alert for live mode)
- No portfolio optimization or Kelly criterion position sizing
- No options trading, crypto, ETFs, or anything other than the 8 listed equities
- No ML models, neural networks, or any learned parameters
- No multi-user support (this is a single-user local process)
- No cloud deployment (runs locally for now)
- No automatic hyperparameter tuning or strategy optimization
- No second or third strategy implementation until the first is complete and backtested

---

## 15. Definition of Done

The project is complete when all of the following are true:

- [ ] Bot runs autonomously on the 8 tickers during paper trading hours with no manual intervention
- [ ] Every decision (including HOLDs) is logged with full detail
- [ ] Backtest produces complete reports for all 6 time periods using the same strategy code
- [ ] Each backtest report includes all metrics listed in section 8.4
- [ ] There is a trade log CSV for each backtest period showing every trade
- [ ] Switching from paper to live requires only environment variable changes (verified by code review, not just claim)
- [ ] Strategy Core has unit tests that prove it is a pure function (no side effects, deterministic output)
- [ ] A `README.md` exists explaining how to run the bot and how to run the backtest
- [ ] A local dashboard (`dashboard/app.py`) shows current holdings and profit/loss at any time, satisfying the task brief's visibility requirement
- [ ] A "going live" checklist document exists covering the 6 steps in section 10
