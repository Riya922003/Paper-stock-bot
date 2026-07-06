"""
Helpers for updating Portfolio State. The only legitimate way state
changes is by applying a confirmed Fill -- nothing else (least of all
the Strategy Core) should mutate cash or positions directly.
"""

import json
from datetime import datetime
from pathlib import Path

from core.models import Fill, PortfolioState, Position
from storage import db


def apply_fill(portfolio: PortfolioState, fill: Fill) -> PortfolioState:
    if fill.action == "BUY":
        cost = fill.quantity * fill.price
        existing = portfolio.positions.get(fill.ticker)
        if existing:
            total_qty = existing.qty + fill.quantity
            avg_price = (
                existing.qty * existing.avg_entry_price + fill.quantity * fill.price
            ) / total_qty
            portfolio.positions[fill.ticker] = Position(
                qty=total_qty, avg_entry_price=avg_price, entry_time=existing.entry_time
            )
        else:
            portfolio.positions[fill.ticker] = Position(
                qty=fill.quantity, avg_entry_price=fill.price, entry_time=fill.timestamp
            )
        portfolio.cash -= cost

    elif fill.action == "SELL":
        proceeds = fill.quantity * fill.price
        portfolio.cash += proceeds
        existing = portfolio.positions.get(fill.ticker)
        if existing:
            remaining = existing.qty - fill.quantity
            if remaining <= 0:
                del portfolio.positions[fill.ticker]
            else:
                portfolio.positions[fill.ticker] = Position(
                    qty=remaining,
                    avg_entry_price=existing.avg_entry_price,
                    entry_time=existing.entry_time,
                )

    return portfolio


def load_portfolio_state(
    strategy: str, mode: str, starting_capital: float, db_path: Path = db.DEFAULT_DB_PATH
) -> PortfolioState:
    """
    Reconstructs the current PortfolioState from the database instead
    of relying on an in-memory object -- needed for a process that
    starts fresh every invocation (e.g. a GitHub Actions job), unlike
    the continuously-running run_live.py loop, which just keeps
    portfolio in memory across ticks.

    Cash comes from the latest portfolio_snapshot. Each open position's
    entry price/time is recovered from its most recent BUY fill --
    exact, not an approximation, because this system never holds more
    than one open position per ticker or partially fills an order
    (PRD 5.2/5.3), so the latest unmatched BUY for a currently-held
    ticker IS its entry.
    """
    latest = db.get_latest_portfolio(strategy=strategy, mode=mode, db_path=db_path)
    if latest is None:
        return PortfolioState(cash=starting_capital, starting_capital=starting_capital)

    held_quantities = json.loads(latest["positions_json"])
    if not held_quantities:
        return PortfolioState(cash=latest["cash"], starting_capital=starting_capital)

    fills = db.get_all_fills(strategy=strategy, mode=mode, db_path=db_path)
    positions = {}
    for ticker, qty in held_quantities.items():
        last_buy = [f for f in fills if f["ticker"] == ticker and f["action"] == "BUY"][-1]
        positions[ticker] = Position(
            qty=qty,
            avg_entry_price=last_buy["price"],
            entry_time=datetime.fromisoformat(last_buy["timestamp"]),
        )

    return PortfolioState(cash=latest["cash"], starting_capital=starting_capital, positions=positions)
