# Submission Deliverables

This document maps directly to the 9 deliverables the original task brief asks for. It's written for a reviewer or client evaluating the submission — for the full technical spec and architecture reasoning, see `docs/` instead (that's the agent/developer-facing reference; this document is the client-facing one).

**Status at a glance:** 6 of 9 fully done, 3 partially done (content exists, being consolidated into this document).

---

## 1. Research Document

**Status: Not yet written as a standalone document.**

The original research focused on evaluating Alpaca against the field (see section 2 below for the outcome), but a full comparative write-up covering multiple platforms — Interactive Brokers, TD Ameritrade/Schwab, Tradier, and others, with what was learned from each — has not yet been produced as its own deliverable. This is the one genuinely open item in this list.

---

## 2. Selected Platform/API Explanation

**Status: Done.**

**Platform chosen: Alpaca Markets.**

**Why:**
- Paper trading and live trading use the identical REST/WebSocket API — switching from paper to live later is an environment variable change (base URL + keys), not a rewrite.
- Commission-free US equity trading.
- Well-documented Python SDK (`alpaca-py`), actively maintained.
- No minimum account balance required for paper trading.
- Supports fractional shares — needed for precise position sizing on high-priced stocks like NVDA and GOOGL, where a fixed dollar allocation rarely divides evenly into whole shares.

**The two modes:**

| Mode | Base URL | What happens |
|---|---|---|
| Paper | `https://paper-api.alpaca.markets` | Simulated money, real market prices |
| Live | `https://api.alpaca.markets` | Real money, real trades |

Historical data for backtesting comes from `yfinance` instead of Alpaca's own historical endpoint, specifically because yfinance's free-tier lookback window is longer — this keeps the 3-year backtest period possible without a paid data subscription.

---

## 3. Strategy Document

**Status: Done.**

**Strategy: EMA(9)/EMA(21) crossover, filtered by RSI(14).** A trend-following approach — it looks for stocks with genuine emerging upward momentum, using the RSI filter specifically to avoid chasing an already-overbought spike.

**Checks the market:** every 5 minutes, during US market hours only (9:30 AM–4:00 PM ET, Mon–Fri).

**Capital allocated per stock:** a fixed 12.5% of *starting* capital per position — not 12.5% of current cash, so sizing never inflates on a winning streak or shrinks after a loss.

**Maximum open positions:** 4 at a time, meaning at most 50% of capital is ever deployed simultaneously.

**Buy signal — all of the following must be true:**
1. EMA(9) crosses above EMA(21) on the most recently completed candle (a fresh cross, not an already-established trend)
2. RSI(14) is between 40 and 65 — confirms momentum without being overbought
3. This ticker isn't already held
4. Fewer than 4 positions are currently open
5. There's enough cash for the position size
6. The market is confirmed open

If any condition fails, the bot holds and logs exactly which condition failed.

**Sell signal — checked in this priority order, first match wins:**
1. **Stop-loss:** price has fallen 3% or more below entry
2. **Take-profit:** price has risen 6% or more above entry
3. **Trend broken:** EMA(9) crosses back below EMA(21)

**Risk limits, as a summary:** never more than 50% of capital deployed at once (4 positions × 12.5%), each individual position capped at a 3% loss before an automatic exit.

**What happens if the API fails:** order submission failures and market-data fetch failures are both caught and logged rather than crashing the bot — no retry is attempted immediately; the next scheduled cycle (5 minutes later) naturally re-evaluates and may act again if the signal still holds.

**What happens if market data is missing:** a ticker with missing or broken data for a cycle is flagged and skipped for that cycle only — the bot never trades on incomplete information, and this never blocks the other 7 tickers from being evaluated normally.

---

## 4. Working Paper Trading Bot

**Status: Done.**

Runs against a real Alpaca paper trading account. Verified end-to-end: the bot successfully connects, checks market hours, fetches live prices, evaluates the strategy, and has logged real decisions during actual market hours. See `run_live.py`; setup and run instructions are in `README.md`.

---

## 5. Backtesting Report

**Status: Done.**

All 6 required periods run with the identical strategy code used for live trading — no separate backtest-only logic. Full summaries are in `reports/`:

| Period | Return | Trades | Win rate | Max drawdown |
|---|---|---|---|---|
| 1 week | -0.22% | 27 | 25.9% | 0.75% |
| 1 month | -5.00% | 160 | 21.2% | 5.43% |
| 3 months | +4.02% | 46 | 37.0% | 2.91% |
| 6 months | +1.09% | 102 | 29.4% | 7.55% |
| 1 year | +2.62% | 201 | 32.8% | 8.81% |
| 3 years | +10.48% | 105 | 43.8% | 5.73% |

The results are deliberately left as-is, including the losing periods — no parameter tuning was done after seeing outcomes. The pattern is informative on its own: shorter periods (5-minute bars) show more overtrading/whipsaw behavior, while longer periods (hourly/daily bars, smoother data) perform better.

---

## 6. Trade Logs

**Status: Done.**

Every completed trade for all 6 periods is in `reports/report_<period>_trend_following_trades.csv` — ticker, entry date/price, exit date/price, quantity, P&L per trade. Also viewable interactively in the dashboard's Trade Log tab.

---

## 7. Profit/Loss Summary for All Required Periods

**Status: Done.** Same table as deliverable 5 — see `reports/*_summary.txt` for the full breakdown per period (starting/ending capital, net P&L, return %, win/loss counts, max drawdown, fee assumptions).

---

## 8. Instructions to Run the Bot

**Status: Done.** See `README.md` — covers setup, running tests, running the 6-period backtest, running the live loop, and viewing the dashboard.

---

## 9. What's Needed Before Using Real Money

**Status: Done.**

Going live is designed to require environment variable changes only — not a code rewrite. The complete checklist:

1. Change `ALPACA_BASE_URL` from the paper URL to the live URL
2. Change `ALPACA_API_KEY`/`ALPACA_SECRET_KEY` to the live account's credentials
3. Set `STARTING_CAPITAL` to the actual amount in the live account
4. **Verify account equity exceeds $25,000, or explicitly accept the Pattern Day Trader (PDT) restriction** — accounts under $25k are limited to 3 day-trades per rolling 5 business days. Paper accounts don't enforce this, so it's easy to overlook.
5. **Reduce position size for the first week of live trading** (e.g. well below the paper account's 12.5%) — a manual, deliberate decision, not automated.
6. **Add a human approval step** before the very first live order — the bot should notify and wait for explicit confirmation before it ever risks real money for the first time.

Nothing else changes — the strategy logic, database, and reporting all stay identical between paper and live.
