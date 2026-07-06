"""
Entry point: runs the live paper-trading loop on a schedule.

Usage: python run_live.py
"""

import os

from alpaca.trading.client import TradingClient
from apscheduler.schedulers.blocking import BlockingScheduler
from dotenv import load_dotenv

from core.models import PortfolioState
from data import live_feed
from execution import live_adapter
from portfolio.state import apply_fill
from storage import db
from strategy import get_strategy

load_dotenv()

STARTING_CASH = 100_000.0
CHECK_INTERVAL_MINUTES = int(os.getenv("CHECK_INTERVAL_MINUTES", 5))

portfolio = PortfolioState(cash=STARTING_CASH, starting_capital=STARTING_CASH)
_trading_client = TradingClient(os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY"), paper=True)


def tick() -> None:
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


def main() -> None:
    db.init_db()
    scheduler = BlockingScheduler()
    scheduler.add_job(tick, "interval", minutes=CHECK_INTERVAL_MINUTES)
    print(f"Starting live loop, checking every {CHECK_INTERVAL_MINUTES} minutes...")
    tick()  # run once immediately on startup
    scheduler.start()


if __name__ == "__main__":
    main()
