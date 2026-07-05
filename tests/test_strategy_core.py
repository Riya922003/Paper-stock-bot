"""
Unit tests for the trend-following Strategy Core (strategy/trend_following.py).

Rules under test come directly from docs/PRD.md section 5.2-5.3. These run
with no network access at all -- every MarketSnapshot here is built by hand
from literal price data. That's the whole point of a pure Strategy Core:
it's fully testable without touching Alpaca or yfinance.

Write these BEFORE implementing decide() (test-first): they should all fail
with NotImplementedError until strategy/trend_following.py is filled in,
then all pass once it is -- with no changes to this file in between.
"""

from datetime import datetime, timedelta

import pandas as pd
import pytest

from core.models import MarketSnapshot, TickerData, PortfolioState, Position
from strategy import get_strategy

decide = get_strategy("trend_following")

STARTING_CAPITAL = 10_000.0
POSITION_SIZE = STARTING_CAPITAL * 0.125  # $1,250, per PRD 5.3

# ---------------------------------------------------------------------------
# Price fixtures. Each series was verified against a hand-run reference
# EMA(9)/EMA(21)/RSI(14) calculation (Wilder smoothing -- the pandas-ta
# default) before being hardcoded here, checked against both common EMA
# seeding conventions to make sure the crossover/RSI classification is
# robust to that implementation detail.
# ---------------------------------------------------------------------------

# Decline from 100 -> 83, then a choppy-but-net-upward recovery. On the
# FINAL candle: EMA9 crosses above EMA21 for the first time, RSI(14) ~= 52.5
# (comfortably inside the 40-65 buy window). The clean BUY case.
BUY_SIGNAL_CLOSES = [
    99.5, 99.0, 98.5, 98.0, 97.5, 97.0, 96.5, 96.0, 95.5, 95.0,
    94.5, 94.0, 93.5, 93.0, 92.5, 92.0, 91.5, 91.0, 90.5, 90.0,
    89.5, 89.0, 88.5, 88.0, 87.5, 87.0, 86.5, 86.0, 85.5, 85.0,
    84.5, 84.0, 83.5, 83.0,
    83.72, 83.54, 84.26, 84.08, 84.8, 84.62, 85.34, 85.16, 85.88, 85.7,
    86.42, 86.24, 86.96, 86.78, 87.5, 87.32,
]

# Same shape, much steeper recovery. EMA9 still crosses above EMA21 on the
# final candle, but the sharp rally pushes RSI(14) to ~81.8 -- past the 65
# overbought ceiling. Should be blocked by the RSI filter even though the
# crossover itself is real.
#
# Note: there is deliberately no matching "RSI too low blocks an otherwise
# valid buy" fixture. An exhaustive search (smooth curves and 20,000
# randomized noisy paths) never produced a case where EMA9 freshly crosses
# above EMA21 while RSI(14) is under 40 -- the price action needed to flip
# the fast average above the slow one always lifts RSI past 40 too. The RSI
# filter's real job is blocking overbought spikes like this one, not
# oversold dips.
OVERBOUGHT_CLOSES = [
    99.8, 99.6, 99.4, 99.2, 99.0, 98.8, 98.6, 98.4, 98.2, 98.0,
    97.8, 97.6, 97.4, 97.2, 97.0, 96.8, 96.6, 96.4, 96.2, 96.0,
    95.8, 95.6, 95.4, 95.2, 95.0, 94.8, 94.6, 94.4, 94.2, 94.0,
    93.8, 93.6, 93.4, 93.2, 93.0, 92.8, 92.6, 92.4, 92.2, 92.3,
    92.0, 92.1, 91.8, 91.9, 91.6, 91.7, 91.4, 91.5, 91.2, 101.2,
]

# Steady, uninterrupted decline for all 50 candles -- EMA9 stays below
# EMA21 throughout (no crossover, ever). Correct response: HOLD, no signal.
NO_CROSSOVER_CLOSES = [round(100 - 0.4 * i, 2) for i in range(50)]

# Smooth, sustained uptrend -- EMA9 has been above EMA21 for a while and
# stays there (no NEW cross on the final candle). Represents "still in an
# open, healthy trend" for sell-side HOLD tests.
SUSTAINED_UPTREND_CLOSES = [round(100 + 0.3 * i, 2) for i in range(50)]

# Rise from 100 -> 110, then a choppy-but-net-downward reversal. On the
# FINAL candle: EMA9 crosses below EMA21 for the first time -- the "thesis
# invalidated" sell trigger (PRD 5.2, sell rule #1).
TREND_BROKEN_CLOSES = [
    100.3, 100.6, 100.9, 101.2, 101.5, 101.8, 102.1, 102.4, 102.7, 103.0,
    103.3, 103.6, 103.9, 104.2, 104.5, 104.8, 105.1, 105.4, 105.7, 106.0,
    106.3, 106.6, 106.9, 107.2, 107.5, 107.8, 108.1, 108.4, 108.7, 109.0,
    109.3, 109.6, 109.9, 110.2,
    110.38, 109.86, 110.04, 109.52, 109.7, 109.18, 109.36, 108.84, 109.02, 108.5,
    108.68, 108.16, 108.34, 107.82, 108.0, 107.48,
]


def make_bars(closes: list[float]) -> pd.DataFrame:
    """Build a minimal OHLCV frame, oldest first, matching TickerData.bars."""
    start = datetime(2026, 6, 1, 9, 30)
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c * 1.001 for c in closes],
            "low": [c * 0.999 for c in closes],
            "close": closes,
            "volume": [10_000] * len(closes),
        },
        index=[start + timedelta(minutes=5 * i) for i in range(len(closes))],
    )


def make_snapshot(ticker_bars: dict) -> MarketSnapshot:
    """ticker_bars maps ticker -> (closes, is_stale)."""
    tickers = {}
    for ticker, (closes, is_stale) in ticker_bars.items():
        tickers[ticker] = TickerData(
            last_price=closes[-1], bars=make_bars(closes), is_stale=is_stale
        )
    return MarketSnapshot(timestamp=datetime(2026, 7, 4, 10, 0), tickers=tickers)


def fresh_portfolio(cash=STARTING_CAPITAL, starting_capital=STARTING_CAPITAL, positions=None):
    return PortfolioState(cash=cash, starting_capital=starting_capital, positions=positions or {})


def decision_for(decisions, ticker):
    matches = [d for d in decisions if d.ticker == ticker]
    assert len(matches) == 1, f"expected exactly one decision for {ticker}, got {len(matches)}"
    return matches[0]


# ---------------------------------------------------------------------------
# Buy signal (PRD 5.2) -- all 6 conditions must hold
# ---------------------------------------------------------------------------


def test_buy_when_all_six_conditions_met():
    snapshot = make_snapshot({"AAPL": (BUY_SIGNAL_CLOSES, False)})
    portfolio = fresh_portfolio()
    d = decision_for(decide(snapshot, portfolio), "AAPL")
    assert d.action == "BUY"
    assert d.quantity == round(POSITION_SIZE / BUY_SIGNAL_CLOSES[-1], 2)


def test_hold_when_no_ema_crossover():
    snapshot = make_snapshot({"AAPL": (NO_CROSSOVER_CLOSES, False)})
    portfolio = fresh_portfolio()
    d = decision_for(decide(snapshot, portfolio), "AAPL")
    assert d.action == "HOLD"
    assert d.quantity == 0.0


def test_hold_when_rsi_overbought_despite_real_crossover():
    snapshot = make_snapshot({"AAPL": (OVERBOUGHT_CLOSES, False)})
    portfolio = fresh_portfolio()
    d = decision_for(decide(snapshot, portfolio), "AAPL")
    assert d.action == "HOLD"
    assert "rsi" in d.reason.lower()


def test_hold_when_already_holding_the_ticker():
    # Entry at 88.0 vs last close 87.32 is -0.77% -- nowhere near a
    # stop-loss/take-profit trigger, and this fixture's crossover is
    # upward, not a down-cross, so there's no sell trigger either.
    snapshot = make_snapshot({"AAPL": (BUY_SIGNAL_CLOSES, False)})
    portfolio = fresh_portfolio(
        positions={"AAPL": Position(qty=5, avg_entry_price=88.0, entry_time=datetime(2026, 7, 1))}
    )
    d = decision_for(decide(snapshot, portfolio), "AAPL")
    assert d.action == "HOLD"


def test_hold_when_max_positions_reached():
    snapshot = make_snapshot({"AAPL": (BUY_SIGNAL_CLOSES, False)})
    other_positions = {
        ticker: Position(qty=1, avg_entry_price=100.0, entry_time=datetime(2026, 7, 1))
        for ticker in ["MSFT", "GOOGL", "NVDA", "JPM"]
    }
    portfolio = fresh_portfolio(positions=other_positions)
    d = decision_for(decide(snapshot, portfolio), "AAPL")
    assert d.action == "HOLD"
    assert "position" in d.reason.lower() or "max" in d.reason.lower()


def test_hold_when_insufficient_cash():
    snapshot = make_snapshot({"AAPL": (BUY_SIGNAL_CLOSES, False)})
    portfolio = fresh_portfolio(cash=500.0)  # less than the $1,250 slice
    d = decision_for(decide(snapshot, portfolio), "AAPL")
    assert d.action == "HOLD"
    assert "cash" in d.reason.lower()


def test_position_size_uses_starting_capital_not_current_cash():
    # Cash has grown to $20,000 from profits, but starting_capital is still
    # $10,000 -- PRD 5.3 sizes off STARTING capital, so the buy should
    # still be $1,250, not $2,500.
    snapshot = make_snapshot({"AAPL": (BUY_SIGNAL_CLOSES, False)})
    portfolio = fresh_portfolio(cash=20_000.0, starting_capital=10_000.0)
    d = decision_for(decide(snapshot, portfolio), "AAPL")
    assert d.action == "BUY"
    assert d.quantity == round(1_250.0 / BUY_SIGNAL_CLOSES[-1], 2)


# ---------------------------------------------------------------------------
# Sell signal (PRD 5.2) -- priority: stop-loss, then take-profit, then EMA cross
# ---------------------------------------------------------------------------


def test_sell_stop_loss_wins_over_trend_broken():
    entry_price = 112.0  # last close (107.48) is ~4% below this -> stop-loss
    snapshot = make_snapshot({"AAPL": (TREND_BROKEN_CLOSES, False)})
    portfolio = fresh_portfolio(
        positions={"AAPL": Position(qty=10, avg_entry_price=entry_price, entry_time=datetime(2026, 7, 1))}
    )
    d = decision_for(decide(snapshot, portfolio), "AAPL")
    assert d.action == "SELL"
    assert d.quantity == 10
    assert "stop" in d.reason.lower()


def test_sell_take_profit_wins_over_trend_broken():
    entry_price = 100.45  # last close (107.48) is ~7% above this -> take-profit
    snapshot = make_snapshot({"AAPL": (TREND_BROKEN_CLOSES, False)})
    portfolio = fresh_portfolio(
        positions={"AAPL": Position(qty=10, avg_entry_price=entry_price, entry_time=datetime(2026, 7, 1))}
    )
    d = decision_for(decide(snapshot, portfolio), "AAPL")
    assert d.action == "SELL"
    assert "profit" in d.reason.lower()
    assert "stop" not in d.reason.lower()


def test_sell_on_trend_broken_when_no_stop_or_profit_trigger():
    entry_price = TREND_BROKEN_CLOSES[-1]  # 0% change -- neither triggers
    snapshot = make_snapshot({"AAPL": (TREND_BROKEN_CLOSES, False)})
    portfolio = fresh_portfolio(
        positions={"AAPL": Position(qty=10, avg_entry_price=entry_price, entry_time=datetime(2026, 7, 1))}
    )
    d = decision_for(decide(snapshot, portfolio), "AAPL")
    assert d.action == "SELL"
    assert "stop" not in d.reason.lower()
    assert "profit" not in d.reason.lower()


def test_hold_when_holding_with_no_exit_signal():
    entry_price = SUSTAINED_UPTREND_CLOSES[-1]  # 0% change, trend still intact
    snapshot = make_snapshot({"AAPL": (SUSTAINED_UPTREND_CLOSES, False)})
    portfolio = fresh_portfolio(
        positions={"AAPL": Position(qty=10, avg_entry_price=entry_price, entry_time=datetime(2026, 7, 1))}
    )
    d = decision_for(decide(snapshot, portfolio), "AAPL")
    assert d.action == "HOLD"


# ---------------------------------------------------------------------------
# Cross-cutting requirements (PRD 4.1 Components 1 & 3)
# ---------------------------------------------------------------------------


def test_stale_ticker_is_skipped_not_traded():
    snapshot = make_snapshot({"AAPL": (BUY_SIGNAL_CLOSES, True)})  # is_stale=True
    portfolio = fresh_portfolio()
    d = decision_for(decide(snapshot, portfolio), "AAPL")
    assert d.action == "HOLD"
    assert "stale" in d.reason.lower() or "missing" in d.reason.lower()


def test_does_not_crash_on_a_single_bar_of_history():
    # Regression test: the very first candle of a backtest has no history
    # before it (data/historical_feed.py yields a 1-row bars frame at
    # i=0). decide() must not crash just because there isn't enough data
    # yet for a real EMA/RSI signal -- it should just HOLD.
    snapshot = make_snapshot({"AAPL": ([100.0], False)})
    portfolio = fresh_portfolio()
    d = decision_for(decide(snapshot, portfolio), "AAPL")
    assert d.action == "HOLD"


def test_does_not_crash_on_a_held_position_with_a_single_bar_of_history():
    snapshot = make_snapshot({"AAPL": ([100.0], False)})
    portfolio = fresh_portfolio(
        positions={"AAPL": Position(qty=5, avg_entry_price=100.0, entry_time=datetime(2026, 7, 1))}
    )
    d = decision_for(decide(snapshot, portfolio), "AAPL")
    assert d.action == "HOLD"


def test_does_not_crash_with_fewer_bars_than_ema_fast_period():
    # Regression test: with 2-8 bars (more than 1, but fewer than
    # EMA_FAST=9), pandas-ta's ema()/rsi() return None outright rather
    # than a NaN-filled Series -- comparing None <= None raises
    # TypeError in plain Python, unlike NaN comparisons which safely
    # evaluate to False. This only shows up in this exact bar-count
    # range, which the single-bar test above doesn't cover.
    for n in range(2, 9):
        snapshot = make_snapshot({"AAPL": ([100.0 + i for i in range(n)], False)})
        portfolio = fresh_portfolio()
        d = decision_for(decide(snapshot, portfolio), "AAPL")
        assert d.action == "HOLD"


def test_one_decision_per_ticker_in_snapshot():
    snapshot = make_snapshot(
        {
            "AAPL": (BUY_SIGNAL_CLOSES, False),
            "MSFT": (SUSTAINED_UPTREND_CLOSES, False),
            "TSLA": (BUY_SIGNAL_CLOSES, True),
        }
    )
    portfolio = fresh_portfolio(
        positions={
            "MSFT": Position(
                qty=5, avg_entry_price=SUSTAINED_UPTREND_CLOSES[-1], entry_time=datetime(2026, 7, 1)
            )
        }
    )
    decisions = decide(snapshot, portfolio)
    assert {d.ticker for d in decisions} == {"AAPL", "MSFT", "TSLA"}
    assert len(decisions) == 3


def test_pure_function_same_input_same_output():
    snapshot = make_snapshot({"AAPL": (BUY_SIGNAL_CLOSES, False)})
    portfolio = fresh_portfolio()
    first = decide(snapshot, portfolio)
    second = decide(snapshot, portfolio)
    assert [(d.ticker, d.action, d.quantity) for d in first] == [
        (d.ticker, d.action, d.quantity) for d in second
    ]


def test_decide_does_not_mutate_portfolio():
    snapshot = make_snapshot({"AAPL": (BUY_SIGNAL_CLOSES, False)})
    portfolio = fresh_portfolio()
    positions_before = dict(portfolio.positions)
    cash_before = portfolio.cash
    decide(snapshot, portfolio)
    assert portfolio.positions == positions_before
    assert portfolio.cash == cash_before
