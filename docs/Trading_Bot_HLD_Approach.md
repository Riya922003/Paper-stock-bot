# Automated Trading Bot — Approach & High-Level Design

**Status:** Design review — not yet implemented. Superseded for implementation-level detail by `docs/PRD.md`, which locks in the exact strategy, thresholds, tech stack, and file layout. This document remains the source for the high-level architecture rationale (why each component exists, why it's shaped this way).
**Author:** Riya
**Purpose:** Review of proposed approach before implementation begins

---

## 1. Objective

Build an automated trading bot that:
- Trades only these 8 US stocks: `AMZN, TSLA, MSFT, AAPL, META, NVDA, GOOGL, JPM`
- Runs first on a paper (simulated money) trading account
- Is architected so switching to a real-money account later requires minimal changes
- Produces a provable, reproducible backtest across 6 historical periods (1 week, 1 month, 3 months, 6 months, 1 year, 3 years)

---

## 2. Chosen Execution Platform: Alpaca

**Decision:** Alpaca Markets API

**Reasoning:**
- Paper trading and live trading use the **identical REST/WebSocket API** — switching later is an API key + base URL change, not a rewrite
- Free access to historical bar data (IEX feed), sufficient for backtesting across all 6 required periods
- Commission-free US equity trading, supports the order types needed for automated execution
- Well-documented, widely used for exactly this use case (paper-to-live automated trading)

**Open item:** a full written comparison against alternative platforms (e.g. Interactive Brokers API, TD Ameritrade/Schwab API) is still pending as a separate research deliverable — this document covers the design built on the platform decision, not the full comparative research write-up.

---

## 3. System Architecture

### 3.1 Diagram (text form)

```
   [ MARKET SNAPSHOT ]              [ PORTFOLIO STATE ]
   (prices, all 8 stocks,           (cash + what we
    right now)                       currently own)
            \                              /
             \                            /
              v                          v
         +--------------------------------------+
         |            STRATEGY CORE              |
         |     (runs ONE active rulebook,        |
         |      picked by a config setting)      |
         +--------------------------------------+
                            ^
                            |
              (only one plugged in at a time)
                            |
        +-------------------+--------------------+
        |                   |                    |
+-----------------+ +-------------------+ +-------------------+
| MEAN-REVERSION   | | TREND-FOLLOWING    | |    BREAKOUT        |
| (buy the dip)    | | (ride the trend)   | | (buy new highs)    |
+-----------------+ +-------------------+ +-------------------+

                 (Strategy Core, after picking one, continues below)
                            |
                            v
                 +----------------------+
                 |      DECISION         |
                 | (per stock: action +  |
                 |   reason, always)     |
                 +----------------------+
                     |              |
                     v              v
        +-------------------+   +-------------------+
        |   DECISION LOG     |   |   ORDER HANDLER    |
        | (every decision,   |   | (same rulebook,    |
        |  logged, forever)  |   |  two modes below)  |
        +-------------------+   +-------------------+
                 |                    |        |
                 |                    v        v
                 |          +-------------+ +----------------+
                 |          |  LIVE MODE   | | BACKTEST MODE  |
                 |          | (Alpaca:     | | (replays old   |
                 |          |  paper/real) | |  price history)|
                 |          +-------------+ +----------------+
                 |                    |        |
                 |                    +---+----+
                 |                        v
                 |                 +-------------+
                 |                 |    FILL      |
                 |                 | (a completed |
                 |                 |  trade)      |
                 |                 +-------------+
                 |                        |
                 |     (updates cash/holdings, loops
                 |      back up into PORTFOLIO STATE)
                 |                        |
                 |    <-------------------+
                 |
                 v
          +-------------------+
          |      REPORT        |
          | (P/L, win/loss,     |
          |  trade log, per     |
          |  time period)       |
          +-------------------+
```

### 3.2 Components

| Component | What it is | Notes |
|---|---|---|
| **Market Snapshot** | A point-in-time picture of prices + recent bars for all 8 tickers | Same shape whether sourced live or from historical replay. Must explicitly flag missing/stale data rather than silently omitting a ticker |
| **Portfolio State** | Our own record of cash + current holdings (qty, entry price) | Updated only by confirmed Fills, never mutated directly by the strategy |
| **Strategy Core** | Pure decision function: `(snapshot, portfolio) -> decisions` | No I/O, no API calls, no wall-clock reads — this isolation is what makes the backtest reproducible and keeps live/backtest logic identical. It is a **swappable slot**, not one fixed rulebook — see 3.1 diagram and section 4 |
| **Decision Log** | Append-only record of every decision made, including "hold, no signal" | This is the evidence against cherry-picking — every consideration is recorded, not just executed trades |
| **Order Handler** | Single interface with two backends: Live (Alpaca) and Backtest (historical replay) | Strategy Core never talks to Alpaca directly — only this layer does |
| **Fill** | A confirmed completed trade, real or simulated | Feeds back into Portfolio State, closing the loop for the next cycle |
| **Report** | Built from Decision Log + trade history | Source for all required backtest metrics per period |

### 3.3 Main Loop

1. Wake up on a schedule (proposed: every few minutes during market hours)
2. Build a fresh Market Snapshot for all 8 tickers; flag any missing data
3. Read current Portfolio State
4. For each held position: check sell triggers (stop-loss / profit-target / thesis invalidated)
5. For each non-held ticker: check buy rule; execute if within position limits and capital rules
6. Log every decision made this cycle, regardless of outcome
7. On order failure: log and retry next scheduled cycle (no immediate forced retries)
8. Sleep until next cycle

---

## 4. Strategy Rule Set (8 required decisions — task section 3)

| # | Rule | Status |
|---|---|---|
| 1 | Buy signal | Pending — see strategy options below |
| 2 | Sell signal (stop-loss / profit-target / thesis-invalidated) | Pending |
| 3 | Capital allocated per stock | Pending |
| 4 | Max open positions | Pending |
| 5 | Check frequency | Pending |
| 6 | Missing-data handling | Decided — skip ticker for that cycle, log reason |
| 7 | Order-failure handling | Decided — log and retry on next scheduled cycle |
| 8 | Underlying signal/theory | Pending — see below |

### Strategy options under consideration
- **Mean-reversion** — buy on an unusual dip below recent average, expecting a bounce
- **Trend-following** — buy on a sustained upward move, expecting continuation
- **Breakout** — buy on a push above a recent high, expecting momentum continuation

**Proposed approach:** implement Strategy Core as swappable (config-selected), fully build and backtest one strategy first for the MVP deliverable, add the others afterward as time permits — each getting its own complete, separate backtest.

**How the selection actually works:** a single config value (e.g. `STRATEGY=mean_reversion` in `.env`) tells the system which rulebook to load. Everything else — Market Snapshot, Portfolio State, Order Handler, Decision Log, Report — behaves identically no matter which one is active. This is what later lets a real user (if this becomes a multi-user product) pick their own strategy without touching any other part of the system.

---

## 5. Backtesting Approach (task sections 5–6)

- Same strategy logic is run, unmodified, across all 6 required periods: 1 week, 1 month, 3 months, 6 months, 1 year, 3 years
- If multiple strategies are tested, each gets its own complete 6-period report — results are never mixed across strategies
- Each period's report includes: starting capital, ending capital, P/L, % return, trade count, win/loss count, max drawdown, fee/slippage assumptions, full trade log
- No manual editing of results; the same code path produces backtest and (later) live results

---

## 6. Real Market Constraints (not design choices — must be respected regardless of strategy)

- Regular market hours: 9:30 AM – 4:00 PM ET
- Pattern Day Trader rule: accounts under $25,000 restricted after 4+ same-day round trips in 5 business days — relevant before going live, paper accounts don't enforce this the same way
- Cash settlement time in a plain cash account

---

## 7. Path to Live Trading

- Strategy Core, Decision Log, and Portfolio State logic remain unchanged
- Only the Order Handler's live backend changes: paper API keys → live API keys
- Before enabling live trading: sufficient backtest + paper track record, reduced starting capital, manual approval step, closer monitoring than paper required

---

## 8. Open Items for Review

Resolved since this document was written — see `docs/PRD.md` for the decided specifics:
- ~~Final choice of first strategy to implement~~ → trend-following (EMA 9/21 crossover + RSI 14 filter), PRD section 5
- ~~Exact numeric thresholds~~ → PRD sections 5.2–5.3 (stop-loss 3%, take-profit 6%, 12.5% sizing, max 4 positions)
- ~~Tech stack for implementation~~ → PRD section 11

Still genuinely open:
- Formal multi-platform comparison document (task requires this as a separate research deliverable — not part of the PRD's scope, since the PRD documents the chosen implementation, not the platform survey)
