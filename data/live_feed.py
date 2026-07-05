"""
Builds a MarketSnapshot from live Alpaca market data.

TODO:
- use alpaca-py's StockHistoricalDataClient to fetch the latest price
  and recent bars for each of the 8 tickers
- check the /v2/clock endpoint first; the caller should skip this
  cycle entirely if the market is closed
- if a ticker's data call fails or returns nothing, still include it
  in the snapshot with is_stale=True instead of dropping it silently
"""

from core.models import MarketSnapshot

TICKERS = ["AMZN", "TSLA", "MSFT", "AAPL", "META", "NVDA", "GOOGL", "JPM"]


def get_snapshot() -> MarketSnapshot:
    raise NotImplementedError("Wire up alpaca-py StockHistoricalDataClient here")
