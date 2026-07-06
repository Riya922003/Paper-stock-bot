"""
Unit tests for portfolio/state.py's load_portfolio_state() -- needed so
run_live.py can run as a stateless, one-shot process (e.g. a GitHub
Actions job that starts fresh every invocation) instead of requiring
one continuously-running process holding portfolio state in memory.

Uses a real temporary SQLite file per test (tmp_path) -- no mocking,
no network, same pattern as tests/test_db.py.
"""

from datetime import datetime

import pytest

from core.models import Decision, Fill
from portfolio.state import load_portfolio_state
from storage import db

STRATEGY = "trend_following"
MODE = "live"
STARTING_CAPITAL = 100_000.0


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    db.init_db(path)
    return path


def test_no_snapshot_yet_returns_fresh_portfolio(db_path):
    portfolio = load_portfolio_state(STRATEGY, MODE, STARTING_CAPITAL, db_path=db_path)
    assert portfolio.cash == STARTING_CAPITAL
    assert portfolio.starting_capital == STARTING_CAPITAL
    assert portfolio.positions == {}


def test_snapshot_with_no_open_positions(db_path):
    db.save_portfolio_snapshot(
        cash=95_000.0, equity=95_000.0, positions={}, strategy=STRATEGY, mode=MODE,
        timestamp=datetime(2026, 7, 6, 10, 0), db_path=db_path,
    )
    portfolio = load_portfolio_state(STRATEGY, MODE, STARTING_CAPITAL, db_path=db_path)
    assert portfolio.cash == 95_000.0
    assert portfolio.positions == {}


def test_reconstructs_a_single_open_position_from_its_buy_fill(db_path):
    db.log_fill(
        Fill(ticker="AAPL", action="BUY", quantity=10, price=150.0, timestamp=datetime(2026, 7, 6, 10, 0)),
        STRATEGY, MODE, db_path,
    )
    db.save_portfolio_snapshot(
        cash=98_500.0, equity=100_000.0, positions={"AAPL": 10}, strategy=STRATEGY, mode=MODE,
        timestamp=datetime(2026, 7, 6, 10, 0), db_path=db_path,
    )

    portfolio = load_portfolio_state(STRATEGY, MODE, STARTING_CAPITAL, db_path=db_path)

    assert portfolio.cash == 98_500.0
    assert "AAPL" in portfolio.positions
    position = portfolio.positions["AAPL"]
    assert position.qty == 10
    assert position.avg_entry_price == 150.0
    assert position.entry_time == datetime(2026, 7, 6, 10, 0)


def test_reconstructs_multiple_open_positions_independently(db_path):
    db.log_fill(Fill(ticker="AAPL", action="BUY", quantity=10, price=150.0, timestamp=datetime(2026, 7, 6, 9, 0)),
                STRATEGY, MODE, db_path)
    db.log_fill(Fill(ticker="MSFT", action="BUY", quantity=5, price=300.0, timestamp=datetime(2026, 7, 6, 9, 30)),
                STRATEGY, MODE, db_path)
    db.save_portfolio_snapshot(
        cash=96_000.0, equity=100_000.0, positions={"AAPL": 10, "MSFT": 5}, strategy=STRATEGY, mode=MODE,
        timestamp=datetime(2026, 7, 6, 9, 30), db_path=db_path,
    )

    portfolio = load_portfolio_state(STRATEGY, MODE, STARTING_CAPITAL, db_path=db_path)

    assert portfolio.positions["AAPL"].avg_entry_price == 150.0
    assert portfolio.positions["MSFT"].avg_entry_price == 300.0


def test_ignores_a_closed_round_trip_not_in_current_positions(db_path):
    # AAPL was bought and sold -- fully closed, should not reappear as
    # an open position just because a BUY fill exists in history.
    db.log_fill(Fill(ticker="AAPL", action="BUY", quantity=10, price=150.0, timestamp=datetime(2026, 7, 6, 9, 0)),
                STRATEGY, MODE, db_path)
    db.log_fill(Fill(ticker="AAPL", action="SELL", quantity=10, price=155.0, timestamp=datetime(2026, 7, 6, 10, 0)),
                STRATEGY, MODE, db_path)
    db.save_portfolio_snapshot(
        cash=101_500.0, equity=101_500.0, positions={}, strategy=STRATEGY, mode=MODE,
        timestamp=datetime(2026, 7, 6, 10, 0), db_path=db_path,
    )

    portfolio = load_portfolio_state(STRATEGY, MODE, STARTING_CAPITAL, db_path=db_path)
    assert portfolio.positions == {}


def test_uses_the_most_recent_buy_when_a_ticker_was_bought_sold_and_bought_again(db_path):
    db.log_fill(Fill(ticker="AAPL", action="BUY", quantity=10, price=150.0, timestamp=datetime(2026, 7, 6, 9, 0)),
                STRATEGY, MODE, db_path)
    db.log_fill(Fill(ticker="AAPL", action="SELL", quantity=10, price=155.0, timestamp=datetime(2026, 7, 6, 10, 0)),
                STRATEGY, MODE, db_path)
    db.log_fill(Fill(ticker="AAPL", action="BUY", quantity=8, price=160.0, timestamp=datetime(2026, 7, 6, 11, 0)),
                STRATEGY, MODE, db_path)
    db.save_portfolio_snapshot(
        cash=90_220.0, equity=91_500.0, positions={"AAPL": 8}, strategy=STRATEGY, mode=MODE,
        timestamp=datetime(2026, 7, 6, 11, 0), db_path=db_path,
    )

    portfolio = load_portfolio_state(STRATEGY, MODE, STARTING_CAPITAL, db_path=db_path)

    position = portfolio.positions["AAPL"]
    assert position.qty == 8
    assert position.avg_entry_price == 160.0  # the second buy, not the first
    assert position.entry_time == datetime(2026, 7, 6, 11, 0)


def test_only_affects_the_given_strategy_and_mode(db_path):
    db.log_fill(Fill(ticker="AAPL", action="BUY", quantity=10, price=150.0, timestamp=datetime(2026, 7, 6, 9, 0)),
                strategy="mean_reversion", mode="live", db_path=db_path)
    db.save_portfolio_snapshot(
        cash=1.0, equity=1.0, positions={"AAPL": 10}, strategy="mean_reversion", mode="live",
        timestamp=datetime(2026, 7, 6, 9, 0), db_path=db_path,
    )

    portfolio = load_portfolio_state(STRATEGY, MODE, STARTING_CAPITAL, db_path=db_path)
    assert portfolio.cash == STARTING_CAPITAL  # unaffected by the other strategy's data
    assert portfolio.positions == {}
