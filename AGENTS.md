# AGENTS.md

This file is the entry point for any AI coding agent working on this repository. Read it fully before writing or changing anything. It exists so the human running you does not need to re-explain this project from scratch — everything you need is either below or linked below.

---

## 1. Read This First — Mandatory Startup Sequence

Before writing code, answering a question, or proposing a change, read every file in `docs/` completely, in this order:

1. **`docs/Onboarding Task 1.pdf`** — the original task brief from the user's employer. This is the ground-truth requirements document. If anything else conflicts with this, this document wins.
2. **`docs/PRD.md`** — the authoritative implementation spec. Exact strategy, exact numeric thresholds, exact file structure, exact tech stack. If you are about to write code, this is the document that tells you precisely what to write and where. **Status: ready for implementation.**
3. **`docs/Trading_Bot_HLD_Approach.md`** — the high-level architecture rationale: *why* the system is shaped the way it is (why Strategy Core is a pure function, why there's a swappable strategy slot, why live/backtest share one interface). Superseded by the PRD for specifics (exact numbers, file names) — read it for *reasoning*, not for facts that might now be stale.
4. **`docs/analysis.html`** — earlier, exploratory research (platform comparison, an early draft of the EMA/RSI strategy idea). Historical context only. Where it differs from the PRD, **the PRD wins** — this file predates the PRD and was largely superseded by it.

**Document hierarchy, if any two disagree:** `docs/PRD.md` > `docs/Trading_Bot_HLD_Approach.md` > `docs/analysis.html`, and the original task PDF overrides all three on *requirements* (not implementation detail).

Do not ask the human to re-explain the project, the architecture, or the requirements — it's all in these four documents. Only ask when: a document doesn't answer your question, two documents genuinely conflict in a way this file doesn't already resolve, or a real product decision is still marked open below.

---

## 2. What This Project Is

An automated stock trading bot that trades exactly 8 US equities (`AMZN, TSLA, MSFT, AAPL, META, NVDA, GOOGL, JPM`), running first against Alpaca's paper trading account, architected so a later switch to real money is a config change, not a rewrite. The strategy logic must be identical between live trading and backtesting — same function, same thresholds, fed live data or historical data respectively. See `docs/PRD.md` section 1 for the full framing.

---

## 3. Non-Negotiable Design Rules

These hold regardless of what task you're given. Don't violate them even if a request seems to imply otherwise — flag the tension to the human instead.

- **The Strategy Core must stay a pure function.** No API calls, no disk I/O, no `datetime.now()`, no randomness, inside any `strategy/*.py` module's `decide()` function. This is what makes live and backtest runs provably identical.
- **Every decision gets logged, including HOLD.** Never skip logging a "no signal" decision — this is the anti-cherry-picking mechanism the whole task depends on (see `docs/Onboarding Task 1.pdf` section 6).
- **No lookahead bias in the backtester.** A `MarketSnapshot` built for timestamp T must never contain data from after T. Fills in backtest mode must use the *next* candle's open price, not the signal candle's own price (see `docs/PRD.md` section 8.2/8.3) — **this is currently NOT correctly implemented, see section 5 below.**
- **The same strategy runs across all 6 backtest periods, unmodified.** Never swap logic mid-comparison. If multiple strategies are tested, each gets its own complete 6-period run, never mixed (see `docs/PRD.md` section 8.1).
- **Only the 8 listed tickers, ever.** Refuse to extend the ticker list without an explicit human decision.
- **`PortfolioState` changes only through `apply_fill()`.** Never let a strategy or adapter mutate cash/positions directly just because an order was placed.
- **`execution/live_adapter.py` and `execution/backtest_adapter.py` share one function signature** (`submit_order(decision, snapshot) -> Fill | None`) so the run loop never needs to know which is active.
- **Don't reintroduce scope explicitly ruled out** in `docs/PRD.md` section 14 (no multi-user product, no cloud deployment, no ML models, no second strategy until the first is fully backtested, etc.) unless the human asks for it directly.

---

## 4. Project Structure

Matches `docs/PRD.md` section 12 exactly — do not invent an alternative layout (e.g. no `src/` folder, no `config.py`, no `main.py`):

```
paper-stock-bot/
├── .env / .env.example / .gitignore / requirements.txt / README.md
├── AGENTS.md                     # this file
├── docs/                         # mandatory reading, see section 1 above
│
├── core/models.py                # MarketSnapshot, TickerData, PortfolioState, Position, Decision, Fill
├── strategy/                     # __init__.py (registry) + mean_reversion.py, trend_following.py, breakout.py
├── data/                         # live_feed.py (Alpaca), historical_feed.py (yfinance)
├── portfolio/state.py            # apply_fill()
├── execution/                    # live_adapter.py, backtest_adapter.py -- both submit_order(decision, snapshot)
├── storage/db.py                 # SQLite: decisions, fills, portfolio_snapshots tables
├── dashboard/app.py              # Streamlit, read-only viewer
├── reports/                      # generated backtest output lands here
├── tests/test_strategy_core.py
├── backtest.py                   # entry point -- all 6 periods
├── run_live.py                   # entry point -- live loop
└── report.py                     # NOT YET CREATED -- Component 6
```

---

## 5. Current Implementation Status

Don't assume more is built than actually is. As of this writing:

**Fully implemented, real logic:**
- `core/models.py` — all shared dataclasses
- `portfolio/state.py` — `apply_fill()`
- `storage/db.py` — full SQLite schema and read/write functions
- `strategy/__init__.py` — the registry
- `dashboard/app.py` — working Streamlit viewer

**Wired end-to-end, but calling stubs underneath (`backtest.py`, `run_live.py`):**
- These will raise `NotImplementedError` the moment they hit an unimplemented dependency below. That's expected, not a bug.

**Stubs — raise `NotImplementedError`, need real logic:**
- `data/live_feed.py`, `data/historical_feed.py` — no Alpaca/yfinance wiring yet
- `execution/live_adapter.py` — no real Alpaca order submission yet
- `strategy/mean_reversion.py`, `strategy/breakout.py` — candidate strategies, intentionally not built (see section 14, PRD)
- `strategy/trend_following.py` — **this is the MVP strategy** (`docs/PRD.md` section 5, EMA 9/21 crossover + RSI 14 filter). Currently a stub. This is the highest-priority file to implement.

**Known bug to fix, not just a missing feature:**
- `execution/backtest_adapter.py` currently fills a simulated order at the *current* snapshot's price. `docs/PRD.md` section 8.2/8.3 requires filling at the **next candle's open price** (with 0.1% slippage applied) specifically to avoid lookahead bias. Fix this before trusting any backtest numbers it produces — this directly affects the "proof requirement" in the original task brief.

**Does not exist yet:**
- `report.py` (Component 6) — needs to read `storage/db.py` and produce the per-period metrics required by `docs/PRD.md` section 8.4

**Likely stale:**
- `tests/test_strategy_core.py` currently references `"mean_reversion"` as the strategy under test; once `trend_following.py` is implemented, add/switch tests to cover it, since that's the actual MVP strategy.

---

## 6. How to Run

```
pip install -r requirements.txt
cp .env.example .env         # then fill in your Alpaca paper trading keys
python run_live.py           # live paper-trading loop
python backtest.py           # backtest across all 6 required periods
streamlit run dashboard/app.py
pytest
```

---

## 7. Open Decisions — Ask the Human, Don't Assume

- The formal multi-platform research document (comparing Alpaca against other brokers/APIs) is a separate task deliverable, not yet written — don't assume it exists or fabricate one.
- Whether/when to implement `strategy/mean_reversion.py` and `strategy/breakout.py` — `docs/PRD.md` section 14 says not until `trend_following.py` is complete and backtested. Confirm with the human before starting either.
- Anything that would expand scope beyond `docs/PRD.md` section 14's explicit exclusions — always flag, never silently build.
