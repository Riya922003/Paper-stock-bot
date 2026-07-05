"""
Unit tests for report.py (Component 6, PRD section 8.4).

reconstruct_trades / compute_max_drawdown / compute_metrics are pure --
tested with hand-built data, no database involved. generate_report()
itself is tested end-to-end against a real temporary SQLite file (no
network, no mocking) since report.py's whole job is reading exactly
what storage/db.py already recorded.
"""

import csv
from datetime import datetime

import pytest

from core.models import Decision, Fill
from report import compute_max_drawdown, compute_metrics, generate_report, reconstruct_trades
from storage import db


def fill(ticker, action, price, quantity, timestamp):
    return {"timestamp": timestamp, "ticker": ticker, "action": action, "quantity": quantity, "price": price}


# ---------------------------------------------------------------------------
# reconstruct_trades
# ---------------------------------------------------------------------------


def test_reconstruct_trades_pairs_buy_with_next_sell_same_ticker():
    fills = [
        fill("AAPL", "BUY", 100.0, 10, "2026-07-01T10:00:00"),
        fill("AAPL", "SELL", 110.0, 10, "2026-07-01T11:00:00"),
    ]
    trades = reconstruct_trades(fills)
    assert len(trades) == 1
    t = trades[0]
    assert t.ticker == "AAPL"
    assert t.entry_price == 100.0
    assert t.exit_price == 110.0
    assert t.pnl == pytest.approx(100.0)  # (110-100)*10
    assert t.pnl_pct == pytest.approx(10.0)


def test_reconstruct_trades_ignores_still_open_position():
    fills = [
        fill("AAPL", "BUY", 100.0, 10, "2026-07-01T10:00:00"),
        fill("MSFT", "BUY", 200.0, 5, "2026-07-01T10:05:00"),
        fill("MSFT", "SELL", 190.0, 5, "2026-07-01T11:00:00"),
        # AAPL never sold -- still open at period end, not a completed trade
    ]
    trades = reconstruct_trades(fills)
    assert len(trades) == 1
    assert trades[0].ticker == "MSFT"


def test_reconstruct_trades_handles_multiple_round_trips_same_ticker():
    fills = [
        fill("AAPL", "BUY", 100.0, 10, "2026-07-01T09:00:00"),
        fill("AAPL", "SELL", 105.0, 10, "2026-07-01T10:00:00"),
        fill("AAPL", "BUY", 106.0, 8, "2026-07-01T11:00:00"),
        fill("AAPL", "SELL", 100.0, 8, "2026-07-01T12:00:00"),
    ]
    trades = reconstruct_trades(fills)
    assert len(trades) == 2
    assert trades[0].pnl == pytest.approx(50.0)  # (105-100)*10
    assert trades[1].pnl == pytest.approx(-48.0)  # (100-106)*8


def test_reconstruct_trades_orders_by_timestamp_even_if_input_unsorted():
    fills = [
        fill("AAPL", "SELL", 110.0, 10, "2026-07-01T11:00:00"),
        fill("AAPL", "BUY", 100.0, 10, "2026-07-01T10:00:00"),
    ]
    trades = reconstruct_trades(fills)
    assert len(trades) == 1
    assert trades[0].pnl == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# compute_max_drawdown
# ---------------------------------------------------------------------------


def test_compute_max_drawdown_on_known_curve():
    # peak 100 -> trough 80 is 20%; later peak 120 -> trough 90 is 25% (the max)
    curve = [100, 90, 80, 95, 120, 90, 110]
    assert compute_max_drawdown(curve) == pytest.approx(25.0)


def test_compute_max_drawdown_on_ever_rising_curve_is_zero():
    assert compute_max_drawdown([100, 105, 110, 120]) == 0.0


def test_compute_max_drawdown_on_empty_curve_is_zero():
    assert compute_max_drawdown([]) == 0.0


# ---------------------------------------------------------------------------
# compute_metrics
# ---------------------------------------------------------------------------


def test_compute_metrics_basic_aggregation():
    fills = [
        fill("AAPL", "BUY", 100.0, 10, "2026-07-01T09:00:00"),
        fill("AAPL", "SELL", 110.0, 10, "2026-07-01T10:00:00"),  # win: +100
        fill("MSFT", "BUY", 200.0, 5, "2026-07-01T09:00:00"),
        fill("MSFT", "SELL", 190.0, 5, "2026-07-01T10:00:00"),  # loss: -50
    ]
    trades = reconstruct_trades(fills)
    metrics = compute_metrics(
        trades=trades,
        equity_curve=[100_000, 100_050, 99_950],
        starting_capital=100_000.0,
        ending_capital=99_950.0,
    )
    assert metrics.total_trades == 2
    assert metrics.winning_trades == 1
    assert metrics.losing_trades == 1
    assert metrics.win_rate == pytest.approx(50.0)
    assert metrics.net_pnl == pytest.approx(-50.0)
    assert metrics.return_pct == pytest.approx(-0.05)
    assert metrics.best_trade.ticker == "AAPL"
    assert metrics.worst_trade.ticker == "MSFT"


def test_compute_metrics_with_no_trades():
    metrics = compute_metrics(
        trades=[], equity_curve=[100_000.0], starting_capital=100_000.0, ending_capital=100_000.0
    )
    assert metrics.total_trades == 0
    assert metrics.win_rate == 0.0
    assert metrics.best_trade is None
    assert metrics.worst_trade is None


# ---------------------------------------------------------------------------
# generate_report -- end to end against a real temporary SQLite file
# ---------------------------------------------------------------------------


def test_generate_report_end_to_end(tmp_path):
    db_path = tmp_path / "test.db"
    db.init_db(db_path)

    strategy, period_name = "trend_following", "1_week"
    mode = f"backtest_{period_name}"

    db.log_decision(
        Decision(ticker="AAPL", action="HOLD", reason="no signal"),
        strategy, mode, datetime(2026, 7, 1, 9, 0), db_path,
    )
    db.log_fill(
        Fill(ticker="AAPL", action="BUY", quantity=10, price=100.0, timestamp=datetime(2026, 7, 1, 10, 0)),
        strategy, mode, db_path,
    )
    db.log_fill(
        Fill(ticker="AAPL", action="SELL", quantity=10, price=110.0, timestamp=datetime(2026, 7, 1, 11, 0)),
        strategy, mode, db_path,
    )
    db.log_fill(
        Fill(ticker="MSFT", action="BUY", quantity=5, price=200.0, timestamp=datetime(2026, 7, 1, 10, 0)),
        strategy, mode, db_path,
    )
    db.save_portfolio_snapshot(
        cash=99_000.0, equity=100_000.0, positions={}, strategy=strategy, mode=mode,
        timestamp=datetime(2026, 7, 1, 9, 30), db_path=db_path,
    )
    db.save_portfolio_snapshot(
        cash=98_000.0, equity=101_000.0, positions={"AAPL": 10, "MSFT": 5}, strategy=strategy, mode=mode,
        timestamp=datetime(2026, 7, 1, 10, 30), db_path=db_path,
    )
    db.save_portfolio_snapshot(
        cash=99_000.0, equity=100_100.0, positions={"MSFT": 5}, strategy=strategy, mode=mode,
        timestamp=datetime(2026, 7, 1, 11, 30), db_path=db_path,
    )

    output_dir = tmp_path / "reports"
    metrics = generate_report(strategy, period_name, starting_capital=100_000.0, db_path=db_path, output_dir=output_dir)

    assert metrics.total_trades == 1  # only AAPL closed; MSFT still open
    assert metrics.ending_capital == pytest.approx(100_100.0)

    summary_path = output_dir / "report_1_week_trend_following_summary.txt"
    trades_path = output_dir / "report_1_week_trend_following_trades.csv"
    assert summary_path.exists()
    assert trades_path.exists()

    summary_text = summary_path.read_text()
    assert "AAPL" in summary_text
    assert "slippage" in summary_text.lower()
    assert "commission" in summary_text.lower()

    with open(trades_path, newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["ticker"] == "AAPL"
