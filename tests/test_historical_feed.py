"""
Unit tests for the pure, testable parts of data/historical_feed.py:
choose_interval() and build_snapshots(). Both run with no network access --
build_snapshots() takes already-downloaded bar data (as build_snapshots
would receive from download_bars()), so it's fully testable by hand, the
same way strategy/trend_following.py is.

download_bars() and iter_snapshots() (the thin wrappers that actually call
yfinance) are deliberately NOT unit tested here -- that would require
either hitting the network or mocking yfinance's exact response shape,
neither of which proves anything about our own logic.
"""

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from data.historical_feed import build_snapshots, choose_interval

# ---------------------------------------------------------------------------
# choose_interval -- PRD section 6's day-count rule, extended with a third
# tier for the 3-year period (PRD 8.1), since yfinance's 1-hour bars only
# go back ~730 days in practice.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "days,expected",
    [
        (7, "5m"),  # 1 week
        (30, "5m"),  # 1 month
        (60, "5m"),  # boundary -- PRD 6 says "<= 60 days"
        (61, "1h"),  # just past the boundary
        (90, "1h"),  # 3 months -- intentionally 1h, not 5m (see PRD conflict)
        (180, "1h"),  # 6 months
        (365, "1h"),  # 1 year
        (730, "1h"),  # boundary -- yfinance's practical 1h lookback limit
        (731, "1d"),  # just past the boundary
        (365 * 3, "1d"),  # 3 years
    ],
)
def test_choose_interval(days, expected):
    end = datetime(2026, 7, 4)
    start = end - timedelta(days=days)
    assert choose_interval(start, end) == expected


# ---------------------------------------------------------------------------
# build_snapshots -- given already-downloaded bars sharing one DatetimeIndex
# (exactly what yfinance's multi-ticker download normalizes to), yield one
# MarketSnapshot per timestamp with no lookahead.
# ---------------------------------------------------------------------------


def make_df(closes, opens=None, index=None):
    n = len(closes)
    if opens is None:
        opens = closes
    if index is None:
        start = datetime(2026, 6, 1, 9, 30)
        index = [start + timedelta(minutes=5 * i) for i in range(n)]
    return pd.DataFrame(
        {
            "open": opens,
            "high": [c + 0.5 for c in closes],
            "low": [c - 0.5 for c in closes],
            "close": closes,
            "volume": [1000] * n,
        },
        index=index,
    )


def test_yields_one_snapshot_per_shared_timestamp():
    bars = {
        "AAPL": make_df([10, 11, 12, 13, 14]),
        "MSFT": make_df([100, 101, 102, 103, 104]),
    }
    snapshots = list(build_snapshots(bars, window=10))
    assert len(snapshots) == 5
    assert [s.timestamp for s in snapshots] == list(bars["AAPL"].index)


def test_snapshot_never_contains_future_bars():
    closes = [10, 11, 12, 13, 14]
    bars = {"AAPL": make_df(closes)}
    snapshots = list(build_snapshots(bars, window=10))
    for i, snap in enumerate(snapshots):
        ticker_bars = snap.tickers["AAPL"].bars
        assert len(ticker_bars) == i + 1  # only bars up to and including i
        assert ticker_bars["close"].iloc[-1] == closes[i]
        assert list(ticker_bars["close"]) == closes[: i + 1]


def test_bars_windowed_to_last_n_candles():
    closes = [10, 11, 12, 13, 14]
    bars = {"AAPL": make_df(closes)}
    snapshots = list(build_snapshots(bars, window=2))
    last = snapshots[-1]
    assert len(last.tickers["AAPL"].bars) == 2
    assert list(last.tickers["AAPL"].bars["close"]) == [13, 14]


def test_last_price_is_current_close_not_open_or_future():
    closes = [10, 11, 12]
    opens = [9.5, 10.5, 11.5]
    bars = {"AAPL": make_df(closes, opens=opens)}
    snapshots = list(build_snapshots(bars, window=10))
    for i, snap in enumerate(snapshots):
        assert snap.tickers["AAPL"].last_price == closes[i]


def test_next_open_is_the_following_bars_open():
    closes = [10, 11, 12]
    opens = [9.5, 10.5, 11.5]
    bars = {"AAPL": make_df(closes, opens=opens)}
    snapshots = list(build_snapshots(bars, window=10))
    assert snapshots[0].tickers["AAPL"].next_open == 10.5
    assert snapshots[1].tickers["AAPL"].next_open == 11.5


def test_next_open_is_none_on_the_last_bar():
    bars = {"AAPL": make_df([10, 11, 12])}
    snapshots = list(build_snapshots(bars, window=10))
    assert snapshots[-1].tickers["AAPL"].next_open is None


def test_is_stale_flagged_for_missing_data():
    closes = [10, 11, np.nan, 13, 14]
    opens = [9.5, 10.5, np.nan, 12.5, 13.5]
    bars = {"AAPL": make_df(closes, opens=opens)}
    snapshots = list(build_snapshots(bars, window=10))
    assert snapshots[2].tickers["AAPL"].is_stale is True
    assert snapshots[0].tickers["AAPL"].is_stale is False
    assert snapshots[1].tickers["AAPL"].is_stale is False
    assert snapshots[3].tickers["AAPL"].is_stale is False


def test_next_open_is_none_when_next_bar_is_missing():
    closes = [10, np.nan, 12]
    opens = [9.5, np.nan, 11.5]
    bars = {"AAPL": make_df(closes, opens=opens)}
    snapshots = list(build_snapshots(bars, window=10))
    # bar 0's "next" bar (index 1) is itself missing -> no usable next_open
    assert snapshots[0].tickers["AAPL"].next_open is None


def test_all_tickers_present_in_every_snapshot_even_when_stale():
    bars = {
        "AAPL": make_df([10, 11, 12]),
        "MSFT": make_df([100, np.nan, 102], opens=[99.5, np.nan, 101.5]),
    }
    snapshots = list(build_snapshots(bars, window=10))
    for snap in snapshots:
        assert set(snap.tickers.keys()) == {"AAPL", "MSFT"}
    assert snapshots[1].tickers["MSFT"].is_stale is True
    assert snapshots[1].tickers["AAPL"].is_stale is False
