"""
Entry point: runs the configured strategy across all 6 required
historical periods (1 week, 1 month, 3 months, 6 months, 1 year,
3 years) and writes results into the database.

Each period is tagged with its own `mode` (e.g. "backtest_1_year") so
results never get mixed across periods or across strategies -- see
Trading_Bot_HLD_Approach.md section 5.

Usage: python backtest.py
"""

import os
from datetime import datetime, timedelta

from dotenv import load_dotenv

from core.models import PortfolioState
from data import historical_feed
from execution import backtest_adapter
from portfolio.state import apply_fill
from report import generate_report
from storage import db
from strategy import get_strategy

load_dotenv()

PERIODS = {
    "1_week": timedelta(weeks=1),
    "1_month": timedelta(days=30),
    "3_months": timedelta(days=90),
    "6_months": timedelta(days=180),
    "1_year": timedelta(days=365),
    "3_years": timedelta(days=365 * 3),
}

STARTING_CASH = 100_000.0


def run_period(strategy_name: str, period_name: str, lookback: timedelta) -> None:
    decide = get_strategy(strategy_name)
    portfolio = PortfolioState(cash=STARTING_CASH, starting_capital=STARTING_CASH)
    mode = f"backtest_{period_name}"
    end = datetime.now()
    start = end - lookback

    for snapshot in historical_feed.iter_snapshots(start, end):
        decisions = decide(snapshot, portfolio)
        for decision in decisions:
            db.log_decision(decision, strategy_name, mode=mode, timestamp=snapshot.timestamp)
            fill = backtest_adapter.submit_order(decision, snapshot)
            if fill:
                db.log_fill(fill, strategy_name, mode=mode)
                apply_fill(portfolio, fill)

        db.save_portfolio_snapshot(
            cash=portfolio.cash,
            equity=portfolio.equity(snapshot),
            positions={t: p.qty for t, p in portfolio.positions.items()},
            strategy=strategy_name,
            mode=mode,
            timestamp=snapshot.timestamp,
        )

    metrics = generate_report(strategy_name, period_name, starting_capital=STARTING_CASH)
    print(f"  {period_name}: return {metrics.return_pct:.2f}%, {metrics.total_trades} trades, "
          f"win rate {metrics.win_rate:.1f}%, max drawdown {metrics.max_drawdown_pct:.2f}%")


def main() -> None:
    db.init_db()
    strategy_name = os.getenv("STRATEGY", "trend_following")
    for period_name, lookback in PERIODS.items():
        print(f"Running {strategy_name} over {period_name}...")
        run_period(strategy_name, period_name, lookback)


if __name__ == "__main__":
    main()
