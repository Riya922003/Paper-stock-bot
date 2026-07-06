"""
Helpers for updating Portfolio State. The only legitimate way state
changes is by applying a confirmed Fill -- nothing else (least of all
the Strategy Core) should mutate cash or positions directly.
"""

from core.models import PortfolioState, Position, Fill


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
