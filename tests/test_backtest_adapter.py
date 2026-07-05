"""
Unit tests for execution/backtest_adapter.py.

The bug being fixed: it used to fill at the CURRENT snapshot's price,
which is lookahead bias (the strategy decided using data up to time T,
but got a fill at time T's own price instead of a later, unknowable-at-
decision-time price). Per PRD 8.2/8.3, a simulated fill must use the
NEXT candle's open price, with 0.1% slippage applied against the trader
(buys cost slightly more, sells receive slightly less).
"""

from datetime import datetime

import pandas as pd
import pytest

from core.models import Decision, MarketSnapshot, TickerData
from execution.backtest_adapter import submit_order


def make_snapshot(last_price: float, next_open: float | None) -> MarketSnapshot:
    ticker_data = TickerData(
        last_price=last_price,
        bars=pd.DataFrame({"open": [last_price], "close": [last_price]}),
        is_stale=False,
        next_open=next_open,
    )
    return MarketSnapshot(timestamp=datetime(2026, 7, 4, 10, 0), tickers={"AAPL": ticker_data})


def test_hold_returns_no_fill():
    decision = Decision(ticker="AAPL", action="HOLD", reason="no signal")
    snapshot = make_snapshot(last_price=100.0, next_open=101.0)
    assert submit_order(decision, snapshot) is None


def test_buy_fills_at_next_open_plus_slippage():
    decision = Decision(ticker="AAPL", action="BUY", reason="signal", quantity=10)
    snapshot = make_snapshot(last_price=100.0, next_open=200.0)
    fill = submit_order(decision, snapshot)
    assert fill is not None
    assert fill.price == pytest.approx(200.0 * 1.001)


def test_sell_fills_at_next_open_minus_slippage():
    decision = Decision(ticker="AAPL", action="SELL", reason="signal", quantity=10)
    snapshot = make_snapshot(last_price=100.0, next_open=200.0)
    fill = submit_order(decision, snapshot)
    assert fill is not None
    assert fill.price == pytest.approx(200.0 * 0.999)


def test_fill_never_uses_the_current_snapshot_price():
    # last_price is wildly different from next_open -- if the fill price
    # matches last_price at all, the lookahead-bias bug is back.
    decision = Decision(ticker="AAPL", action="BUY", reason="signal", quantity=1)
    snapshot = make_snapshot(last_price=9999.0, next_open=50.0)
    fill = submit_order(decision, snapshot)
    assert fill.price == pytest.approx(50.0 * 1.001)
    assert fill.price != pytest.approx(9999.0)


def test_no_fill_when_next_open_is_unavailable():
    # e.g. the very last candle of a backtest period -- there's no future
    # bar to simulate a realistic fill against, so no fill happens.
    decision = Decision(ticker="AAPL", action="BUY", reason="signal", quantity=10)
    snapshot = make_snapshot(last_price=100.0, next_open=None)
    assert submit_order(decision, snapshot) is None


def test_fill_carries_over_ticker_quantity_and_timestamp():
    decision = Decision(ticker="AAPL", action="SELL", reason="signal", quantity=7)
    snapshot = make_snapshot(last_price=100.0, next_open=105.0)
    fill = submit_order(decision, snapshot)
    assert fill.ticker == "AAPL"
    assert fill.quantity == 7
    assert fill.timestamp == snapshot.timestamp
    assert fill.order_id == ""
