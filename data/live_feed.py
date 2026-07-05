"""
Builds a MarketSnapshot from live Alpaca market data.

Split into a pure part (build_snapshot) and thin network parts
(fetch_bars, is_market_open, get_snapshot) so the snapshot-building
logic is fully unit-testable without a real Alpaca connection -- same
pattern as data/historical_feed.py.
"""

import os
from datetime import datetime, timedelta, timezone

import pandas as pd
from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.trading.client import TradingClient

from core.models import MarketSnapshot, TickerData

TICKERS = ["AMZN", "TSLA", "MSFT", "AAPL", "META", "NVDA", "GOOGL", "JPM"]
BARS_WINDOW = 50

# Free-tier Alpaca accounts get IEX data with a ~15-minute delay.
# Requesting an `end` time inside that delay window silently returns
# EMPTY data instead of erroring (verified against the real API) --
# always request a bit further back than "now" to avoid this.
DATA_DELAY_BUFFER_MINUTES = 16
LOOKBACK_DAYS = 7  # generous enough for >= BARS_WINDOW 5-min bars even across a weekend


def build_snapshot(bars_by_ticker: dict, timestamp: datetime, window: int = BARS_WINDOW) -> MarketSnapshot:
    """
    Given already-fetched bars per ticker (empty list or None if the
    fetch failed or returned nothing for that ticker), build a
    MarketSnapshot. A ticker with no usable bars is marked is_stale
    rather than dropped, per PRD Component 1 -- the rest of the system
    handles the flagged case by skipping that ticker for the cycle.
    """
    tickers = {}
    for ticker, bars in bars_by_ticker.items():
        if not bars:
            tickers[ticker] = TickerData(
                last_price=0.0,
                bars=pd.DataFrame(columns=["open", "high", "low", "close", "volume"]),
                is_stale=True,
            )
            continue

        windowed = bars[-window:]
        df = pd.DataFrame(windowed)[["open", "high", "low", "close", "volume"]]
        tickers[ticker] = TickerData(
            last_price=float(df["close"].iloc[-1]),
            bars=df,
            is_stale=False,
        )

    return MarketSnapshot(timestamp=timestamp, tickers=tickers)


def is_market_open(client: TradingClient) -> bool:
    """Thin wrapper around Alpaca's /v2/clock endpoint."""
    return client.get_clock().is_open


def fetch_bars(client: StockHistoricalDataClient, tickers: list = None) -> dict:
    """
    Thin network wrapper -- not unit tested (would need a real Alpaca
    connection). Returns an empty list for any ticker whose data
    couldn't be fetched, rather than raising or dropping it, so
    build_snapshot can mark it is_stale.
    """
    tickers = tickers or TICKERS
    result = {ticker: [] for ticker in tickers}

    end = datetime.now(timezone.utc) - timedelta(minutes=DATA_DELAY_BUFFER_MINUTES)
    start = end - timedelta(days=LOOKBACK_DAYS)

    try:
        request = StockBarsRequest(
            symbol_or_symbols=tickers,
            timeframe=TimeFrame(5, TimeFrameUnit.Minute),
            start=start,
            end=end,
            feed=DataFeed.IEX,
        )
        response = client.get_stock_bars(request)
        for ticker in tickers:
            bars = response.data.get(ticker, [])
            result[ticker] = [
                {
                    "timestamp": b.timestamp,
                    "open": b.open,
                    "high": b.high,
                    "low": b.low,
                    "close": b.close,
                    "volume": b.volume,
                }
                for b in bars
            ]
    except Exception as e:
        print(f"[live_feed] Failed to fetch bars: {e}")
        # result stays all-empty -> every ticker gets marked is_stale

    return result


def _make_data_client() -> StockHistoricalDataClient:
    return StockHistoricalDataClient(os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY"))


def get_snapshot(client: StockHistoricalDataClient = None) -> MarketSnapshot:
    if client is None:
        client = _make_data_client()
    bars_by_ticker = fetch_bars(client)
    return build_snapshot(bars_by_ticker, timestamp=datetime.now(timezone.utc))
