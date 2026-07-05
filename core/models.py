"""
Shared data contracts used across the whole system.

These are the boxes from the architecture diagram: Market Snapshot,
Portfolio State, Decision, and Fill. Every other module (strategy,
data, execution, storage) imports these instead of inventing its own
shape for the same concept -- that's what keeps live trading and
backtesting provably running the same logic.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

import pandas as pd


@dataclass(frozen=True)
class TickerData:
    """One ticker's slice of a Market Snapshot.

    next_open is the opening price of the bar immediately after this
    snapshot's timestamp (None if this is the last known bar). It exists
    only for the backtest fill simulator (execution/backtest_adapter.py),
    which needs to know the next price to avoid lookahead bias -- the
    Strategy Core's decide() must never read this field.
    """
    last_price: float
    bars: pd.DataFrame  # recent OHLCV history, oldest first
    is_stale: bool = False
    next_open: float | None = None


@dataclass(frozen=True)
class MarketSnapshot:
    """A frozen picture of all 8 tickers at one moment in time.

    Built the same way whether the source is live Alpaca data or
    replayed historical data -- the Strategy Core cannot tell the
    difference, and must never see data from after `timestamp`
    (this is how lookahead bias sneaks into a backtest -- see the HLD).
    """
    timestamp: datetime
    tickers: dict[str, TickerData]


@dataclass
class Position:
    qty: float
    avg_entry_price: float
    entry_time: datetime


@dataclass
class PortfolioState:
    """Our own record of cash + holdings. Changed only by applying a Fill
    (see portfolio/state.py) -- never mutated directly by a strategy.

    starting_capital is set once at bot startup and never changes -- it's
    what position sizing is a percentage of (PRD 5.3), as opposed to
    `cash`, which fluctuates with every fill.
    """
    cash: float
    starting_capital: float
    positions: dict[str, Position] = field(default_factory=dict)

    def equity(self, snapshot: MarketSnapshot) -> float:
        market_value = sum(
            pos.qty * snapshot.tickers[ticker].last_price
            for ticker, pos in self.positions.items()
            if ticker in snapshot.tickers
        )
        return self.cash + market_value


@dataclass(frozen=True)
class Decision:
    """One decision for one ticker, produced every cycle -- including HOLD.
    Every decision gets logged, whether or not it results in a trade."""
    ticker: str
    action: Literal["BUY", "SELL", "HOLD"]
    reason: str
    quantity: float = 0.0


@dataclass(frozen=True)
class Fill:
    """A confirmed completed trade, real (live) or simulated (backtest)."""
    ticker: str
    action: Literal["BUY", "SELL"]
    quantity: float
    price: float
    timestamp: datetime
    order_id: str = ""
