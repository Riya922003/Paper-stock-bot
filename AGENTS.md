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
- **No lookahead bias in the backtester.** A `MarketSnapshot` built for timestamp T must never contain data from after T. Fills in backtest mode must use the *next* candle's open price, not the signal candle's own price (see `docs/PRD.md` section 8.2/8.3) — fixed and tested in `execution/backtest_adapter.py`.
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
├── DELIVERABLES.md               # client-facing submission checklist -- distinct from docs/, which is agent-facing
├── docs/                         # mandatory reading, see section 1 above
│
├── core/models.py                # MarketSnapshot, TickerData, PortfolioState, Position, Decision, Fill
├── strategy/                     # __init__.py (registry) + mean_reversion.py, trend_following.py, breakout.py
├── data/                         # live_feed.py (Alpaca), historical_feed.py (yfinance)
├── portfolio/state.py            # apply_fill(); load_portfolio_state() reconstructs state from the DB
├── execution/                    # live_adapter.py, backtest_adapter.py -- both submit_order(decision, snapshot)
├── storage/db.py                 # SQLAlchemy: decisions, fills, portfolio_snapshots -- SQLite locally/tests,
│                                  # Postgres via DATABASE_URL when deployed
├── dashboard/                    # app.py (Streamlit, read-only viewer) + its own minimal requirements.txt
├── reports/                      # generated backtest output -- the 6 official trend_following results are committed
├── tests/                        # 82 tests, no network access required
├── backtest.py                   # entry point -- all 6 periods
├── run_live.py                   # entry point -- live loop
└── report.py                     # Component 6 -- implemented
```

---

## 5. Current Implementation Status

Don't assume more is built than actually is. As of this writing, **strategy 1 (trend_following) is fully complete end-to-end** — implemented, tested, backtested across all 6 required periods, run live against a real Alpaca paper account during actual market hours, and deployed via a public dashboard. The only genuinely unbuilt pieces are the second and third candidate strategies.

**Fully implemented, real logic, tested:**
- `core/models.py` — all shared dataclasses, including `PortfolioState.starting_capital` and `TickerData.next_open` (added during implementation, not in the original stub)
- `portfolio/state.py` — `apply_fill()`, plus `load_portfolio_state()` (reconstructs portfolio from the DB for a process that doesn't hold state in memory across cycles)
- `storage/db.py` — migrated from raw `sqlite3` to SQLAlchemy. SQLite locally/in tests, Postgres via the `DATABASE_URL` env var when deployed (mirrors the Alpaca paper/live env-var pattern)
- `strategy/__init__.py` — the registry
- `strategy/trend_following.py` — **the MVP strategy**, EMA 9/21 crossover + RSI 14 filter, fully implemented (`docs/PRD.md` section 5)
- `data/historical_feed.py` — yfinance wiring, no-lookahead snapshot builder
- `data/live_feed.py` — real Alpaca market data, verified against the live API
- `execution/backtest_adapter.py` — fills at the next candle's open + 0.1% slippage (the lookahead-bias bug described in older versions of this file is fixed)
- `execution/live_adapter.py` — real Alpaca order submission, logs and returns `None` on failure per PRD Component 5, rather than raising
- `report.py` (Component 6) — reads `storage/db.py`, produces the PRD 8.4 per-period metrics, writes both required output files
- `dashboard/app.py` — Streamlit viewer with its own minimal `requirements.txt` (deliberately excludes `pandas-ta`/`alpaca-py`/etc., which the dashboard doesn't need) — deployed publicly, backed by hosted Postgres (Neon). See `docs/PRD.md` section 16 for the deployment architecture.
- `backtest.py`, `run_live.py` — both fully wired, no stub dependencies left

**Stubs — raise `NotImplementedError`, the only remaining unbuilt strategy logic:**
- `strategy/mean_reversion.py`, `strategy/breakout.py` — candidate strategies. `docs/PRD.md` section 14's gate ("not until the first is complete and backtested") is now satisfied, so building these is no longer blocked — see section 7 below.

**Test suite:** 82 tests across `tests/`, no network access required, all passing.

**Official results committed:** `reports/` contains the real 6-period backtest output for `trend_following` (summary + trade log per period) — not a smoke test, the actual submission data.

---

## 6. How to Run

See `README.md` for the full, current, step-by-step guide (Python version requirement, `.env` setup, which Alpaca API key type to use, and the important note that the dashboard shows nothing until a backtest or live run has actually generated data). Don't duplicate those instructions here — update `README.md` instead if they change, so there's one canonical source.

Quick reference:
```
pip install -r requirements.txt
cp .env.example .env         # then fill in your Alpaca paper trading keys
pytest                       # 82 tests, no network required
python backtest.py           # backtest across all 6 required periods
python run_live.py           # live paper-trading loop -- must keep running continuously
streamlit run dashboard/app.py
```

Live dashboard (no local setup needed to view it): see `README.md`'s top section for the current deployed link.

---

## 7. Open Decisions — Ask the Human, Don't Assume

**Resolved since this file was last written:**
- ~~The formal multi-platform research document~~ — written. Content covers Interactive Brokers, Schwab, Tradier, Alpaca, and a cautionary note on unofficial APIs (Robinhood/Webull), each with real findings, not just feature lists. Not committed to this repo as a file by choice — lives in an external document linked from `README.md`. `DELIVERABLES.md` section 1 tracks this.
- ~~Whether/when to implement `strategy/mean_reversion.py` and `strategy/breakout.py`~~ — confirmed: yes, build both, now that `trend_following.py` is complete and backtested (the PRD section 14 gate is satisfied). This is the active next priority, not an open question. Same rigor applies: test-first, full 6-period backtest each, never mixed with `trend_following`'s results.

**Still genuinely open:**
- A live small-order test — `execution/live_adapter.py`'s real order-submission path is thoroughly unit-tested against a fake client, but as of this writing every real signal observed during actual live market hours has been HOLD. No real BUY/SELL fill has yet been confirmed against the live Alpaca API. Don't claim this is proven until it is.
- Anything that would expand scope beyond `docs/PRD.md` section 14's explicit exclusions (multi-user support, cloud-hosting the live trading loop itself, ML models, etc.) — always flag, never silently build. Note: the *dashboard* is deployed (section 16 of the PRD) — that's a deliberate, already-approved exception; the live trading loop and backtester are not, and stay local.
