"""
Unit tests for the pure parts of data/live_feed.py: build_snapshot() and
is_market_open(). fetch_bars() and get_snapshot() are deliberately not
unit tested here -- they require a real Alpaca connection.

The real alpaca-py request/response shapes this module depends on
(StockBarsRequest's feed parameter, Bar's attribute names) were
verified against the live API while building this, not guessed from
memory -- see fetch_bars()'s docstring for the specific gotcha found
(the free-tier IEX feed silently returns empty data if `end` is inside
its ~15-minute delay window, rather than erroring).
"""

from datetime import datetime

from data.live_feed import build_snapshot, is_market_open


def make_bar(close, ts):
    return {"timestamp": ts, "open": close, "high": close, "low": close, "close": close, "volume": 1000}


def test_build_snapshot_normal_ticker():
    bars = [make_bar(100.0 + i, datetime(2026, 7, 4, 10, i)) for i in range(5)]
    snapshot = build_snapshot({"AAPL": bars}, timestamp=datetime(2026, 7, 4, 10, 5))
    td = snapshot.tickers["AAPL"]
    assert td.is_stale is False
    assert td.last_price == 104.0  # last bar's close
    assert len(td.bars) == 5


def test_build_snapshot_marks_empty_ticker_as_stale():
    snapshot = build_snapshot({"AAPL": []}, timestamp=datetime(2026, 7, 4, 10, 5))
    assert snapshot.tickers["AAPL"].is_stale is True


def test_build_snapshot_marks_none_ticker_as_stale():
    snapshot = build_snapshot({"AAPL": None}, timestamp=datetime(2026, 7, 4, 10, 5))
    assert snapshot.tickers["AAPL"].is_stale is True


def test_build_snapshot_windows_to_last_n_bars():
    bars = [make_bar(100.0 + i, datetime(2026, 7, 4, 10, i)) for i in range(10)]
    snapshot = build_snapshot({"AAPL": bars}, timestamp=datetime(2026, 7, 4, 10, 10), window=3)
    assert len(snapshot.tickers["AAPL"].bars) == 3
    assert list(snapshot.tickers["AAPL"].bars["close"]) == [107.0, 108.0, 109.0]


def test_build_snapshot_keeps_every_ticker_present_even_when_stale():
    snapshot = build_snapshot(
        {"AAPL": [make_bar(100.0, datetime(2026, 7, 4, 10, 0))], "MSFT": []},
        timestamp=datetime(2026, 7, 4, 10, 5),
    )
    assert set(snapshot.tickers.keys()) == {"AAPL", "MSFT"}
    assert snapshot.tickers["AAPL"].is_stale is False
    assert snapshot.tickers["MSFT"].is_stale is True


class FakeClock:
    def __init__(self, is_open):
        self.is_open = is_open


class FakeTradingClient:
    def __init__(self, is_open):
        self._is_open = is_open

    def get_clock(self):
        return FakeClock(self._is_open)


def test_is_market_open_true():
    assert is_market_open(FakeTradingClient(is_open=True)) is True


def test_is_market_open_false():
    assert is_market_open(FakeTradingClient(is_open=False)) is False
