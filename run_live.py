"""
Entry point: runs the live paper-trading loop.

Two ways to run this:
- Continuously on one machine: `python run_live.py` -- keeps portfolio
  in memory across ticks, scheduled every CHECK_INTERVAL_MINUTES.
- One-shot, e.g. from a GitHub Actions cron job: `run_single_tick()`
  -- reconstructs portfolio from the database instead of memory, since
  each invocation is a fresh process with nothing carried over.

Both paths call the same tick() and the same Strategy Core/Order
Handler -- the only difference is where portfolio state comes from.
"""

import os

from alpaca.trading.client import TradingClient
from apscheduler.schedulers.blocking import BlockingScheduler
from dotenv import load_dotenv

from core.models import PortfolioState
from data import live_feed
from execution import live_adapter
from portfolio.state import apply_fill, load_portfolio_state
from storage import db
from strategy import get_strategy

load_dotenv()

STARTING_CASH = 100_000.0
CHECK_INTERVAL_MINUTES = int(os.getenv("CHECK_INTERVAL_MINUTES", 5))

_trading_client = TradingClient(os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY"), paper=True)


def tick(portfolio: PortfolioState) -> None:
    if not live_feed.is_market_open(_trading_client):
        print("Market is closed -- skipping this cycle.")
        return

    strategy_name = os.getenv("STRATEGY", "trend_following")
    decide = get_strategy(strategy_name)

    snapshot = live_feed.get_snapshot()
    decisions = decide(snapshot, portfolio)

    for decision in decisions:
        db.log_decision(decision, strategy_name, mode="live", timestamp=snapshot.timestamp)
        fill = live_adapter.submit_order(decision, snapshot)
        if fill:
            db.log_fill(fill, strategy_name, mode="live")
            apply_fill(portfolio, fill)

    db.save_portfolio_snapshot(
        cash=portfolio.cash,
        equity=portfolio.equity(snapshot),
        positions={t: p.qty for t, p in portfolio.positions.items()},
        strategy=strategy_name,
        mode="live",
        timestamp=snapshot.timestamp,
    )


def run_single_tick() -> None:
    """Entry point for a stateless invocation (e.g. GitHub Actions) --
    reconstructs portfolio from the database, does one tick, exits."""
    db.init_db()
    strategy_name = os.getenv("STRATEGY", "trend_following")
    portfolio = load_portfolio_state(strategy_name, mode="live", starting_capital=STARTING_CASH)
    tick(portfolio)


def main() -> None:
    """Entry point for a continuously-running process on one machine --
    keeps portfolio in memory across ticks."""
    db.init_db()
    portfolio = PortfolioState(cash=STARTING_CASH, starting_capital=STARTING_CASH)
    scheduler = BlockingScheduler()
    scheduler.add_job(lambda: tick(portfolio), "interval", minutes=CHECK_INTERVAL_MINUTES)
    print(f"Starting live loop, checking every {CHECK_INTERVAL_MINUTES} minutes...")
    tick(portfolio)  # run once immediately on startup
    scheduler.start()


if __name__ == "__main__":
    main()
