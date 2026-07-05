"""
Builds MarketSnapshots from historical data (yfinance) for backtesting.

Split into a pure part and a network part on purpose:
- choose_interval() and build_snapshots() are pure -- fully unit-testable
  with hand-built DataFrames, no network involved (see
  tests/test_historical_feed.py).
- download_bars() and iter_snapshots() actually call yfinance, and are
  deliberately thin so there's as little untested code as possible.
"""

from datetime import datetime
from typing import Iterator

import pandas as pd

from core.models import MarketSnapshot, TickerData

TICKERS = ["AMZN", "TSLA", "MSFT", "AAPL", "META", "NVDA", "GOOGL", "JPM"]
BARS_WINDOW = 50  # last 50 candles per snapshot, per PRD section 4.1


def choose_interval(start: datetime, end: datetime) -> str:
    """
    PRD section 6's day-count rule: yfinance only keeps 5-minute bars for
    the last ~60 days, and 1-hour bars for roughly the last 730 days
    (~2 years) -- beyond that, only daily bars are available. This is why
    the 3-year backtest period (PRD 8.1) uses daily bars.

    Note: PRD section 8.1's table lists the 3-month period as using
    5-minute bars, which is inconsistent with this day-count rule (90
    days > 60-day limit) -- confirmed with the human, this rule wins, so
    the 3-month period runs on 1-hour bars instead.
    """
    days = (end - start).days
    if days <= 60:
        return "5m"
    if days <= 730:
        return "1h"
    return "1d"


def build_snapshots(bars_by_ticker: dict[str, pd.DataFrame], window: int = BARS_WINDOW) -> Iterator[MarketSnapshot]:
    """
    Given already-downloaded OHLCV bars per ticker -- all sharing one
    DatetimeIndex, with NaN rows wherever a ticker has no data at that
    timestamp (exactly what yfinance's multi-ticker download normalizes
    to) -- yield one MarketSnapshot per timestamp, oldest first.

    At timestamp i, a ticker's bars are windowed to the last `window`
    candles up to and including i, never later -- this is what keeps a
    backtest from leaking future data into the Strategy Core. next_open
    (the following bar's open) is attached for the backtest fill
    simulator only; decide() must never read it.
    """
    if not bars_by_ticker:
        return

    index = next(iter(bars_by_ticker.values())).index

    for i, timestamp in enumerate(index):
        tickers = {}
        for ticker, df in bars_by_ticker.items():
            row = df.iloc[i]
            is_stale = bool(pd.isna(row["close"]))

            next_open = None
            if i + 1 < len(df):
                candidate = df.iloc[i + 1]["open"]
                if not pd.isna(candidate):
                    next_open = float(candidate)

            tickers[ticker] = TickerData(
                last_price=0.0 if is_stale else float(row["close"]),
                bars=df.iloc[max(0, i - window + 1): i + 1],
                is_stale=is_stale,
                next_open=next_open,
            )

        yield MarketSnapshot(timestamp=timestamp, tickers=tickers)


def download_bars(tickers: list[str], start: datetime, end: datetime, interval: str) -> dict[str, pd.DataFrame]:
    """
    Thin wrapper around yfinance. Not unit tested (would need real
    network access or a hand-faked replica of yfinance's exact response
    shape, neither of which would prove anything about our own logic).
    Normalizes the multi-ticker download into one lowercase-column
    DataFrame per ticker, all sharing the same DatetimeIndex.
    """
    import yfinance as yf

    raw = yf.download(
        tickers,
        start=start,
        end=end,
        interval=interval,
        group_by="ticker",
        auto_adjust=False,
        progress=False,
    )
    return {
        ticker: raw[ticker][["Open", "High", "Low", "Close", "Volume"]].rename(columns=str.lower)
        for ticker in tickers
    }


def iter_snapshots(start: datetime, end: datetime) -> Iterator[MarketSnapshot]:
    """Yields one MarketSnapshot per bar, in chronological order."""
    interval = choose_interval(start, end)
    bars = download_bars(TICKERS, start, end, interval)
    yield from build_snapshots(bars)
