"""
Characterization tests for storage/db.py's public API.

These exist to make the upcoming SQLAlchemy migration safe: written
and confirmed passing against the ORIGINAL raw-sqlite3 implementation
first, then re-run unchanged against the SQLAlchemy rewrite. If both
pass without editing this file, the migration is behavior-preserving --
seven other files (backtest.py, run_live.py, report.py, dashboard/
app.py, and their tests) depend on this exact API shape.

Uses a real temporary SQLite file per test (tmp_path) -- no mocking,
no network.
"""

from datetime import datetime

import pytest

from core.models import Decision, Fill
from storage import db
from storage.db import _resolve_url


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    db.init_db(path)
    return path


def test_init_db_is_idempotent(db_path):
    # Calling init_db twice on the same file must not error or wipe data.
    db.log_decision(Decision(ticker="AAPL", action="HOLD", reason="x"), "s", "m", datetime(2026, 1, 1), db_path)
    db.init_db(db_path)
    assert len(db.get_all_decisions(db_path=db_path)) == 1


def test_log_and_get_decisions(db_path):
    db.log_decision(
        Decision(ticker="AAPL", action="BUY", reason="signal", quantity=10),
        strategy="trend_following", mode="live", timestamp=datetime(2026, 7, 4, 10, 0), db_path=db_path,
    )
    rows = db.get_all_decisions(db_path=db_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["ticker"] == "AAPL"
    assert row["action"] == "BUY"
    assert row["reason"] == "signal"
    assert row["quantity"] == 10
    assert row["strategy"] == "trend_following"
    assert row["mode"] == "live"
    assert row["timestamp"] == datetime(2026, 7, 4, 10, 0).isoformat()


def test_log_and_get_fills(db_path):
    db.log_fill(
        Fill(ticker="MSFT", action="SELL", quantity=5, price=200.5, timestamp=datetime(2026, 7, 4, 11, 0), order_id="ord-1"),
        strategy="trend_following", mode="backtest_1_week", db_path=db_path,
    )
    rows = db.get_all_fills(db_path=db_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["ticker"] == "MSFT"
    assert row["action"] == "SELL"
    assert row["quantity"] == 5
    assert row["price"] == 200.5
    assert row["order_id"] == "ord-1"


def test_fill_default_order_id_is_empty_string_not_none(db_path):
    db.log_fill(
        Fill(ticker="AAPL", action="BUY", quantity=1, price=100.0, timestamp=datetime(2026, 7, 4)),
        strategy="s", mode="m", db_path=db_path,
    )
    assert db.get_all_fills(db_path=db_path)[0]["order_id"] == ""


def test_save_and_get_latest_portfolio(db_path):
    db.save_portfolio_snapshot(
        cash=1000.0, equity=1500.0, positions={"AAPL": 5}, strategy="s", mode="m",
        timestamp=datetime(2026, 7, 4, 9, 0), db_path=db_path,
    )
    db.save_portfolio_snapshot(
        cash=900.0, equity=1600.0, positions={"AAPL": 5, "MSFT": 2}, strategy="s", mode="m",
        timestamp=datetime(2026, 7, 4, 10, 0), db_path=db_path,
    )
    latest = db.get_latest_portfolio(strategy="s", mode="m", db_path=db_path)
    assert latest["cash"] == 900.0
    assert latest["equity"] == 1600.0
    assert latest["timestamp"] == datetime(2026, 7, 4, 10, 0).isoformat()


def test_positions_json_stored_as_raw_json_string_not_auto_parsed(db_path):
    db.save_portfolio_snapshot(
        cash=100.0, equity=100.0, positions={"AAPL": 3.5}, strategy="s", mode="m",
        timestamp=datetime(2026, 7, 4), db_path=db_path,
    )
    row = db.get_latest_portfolio(strategy="s", mode="m", db_path=db_path)
    assert row["positions_json"] == '{"AAPL": 3.5}'  # raw JSON string, matching current behavior


def test_get_all_portfolio_snapshots_returns_every_row_in_order(db_path):
    for i in range(3):
        db.save_portfolio_snapshot(
            cash=100.0 + i, equity=200.0 + i, positions={}, strategy="s", mode="m",
            timestamp=datetime(2026, 7, 4, 9 + i, 0), db_path=db_path,
        )
    rows = db.get_all_portfolio_snapshots(strategy="s", mode="m", db_path=db_path)
    assert len(rows) == 3
    assert [r["equity"] for r in rows] == [200.0, 201.0, 202.0]


def test_get_latest_portfolio_returns_none_when_nothing_saved(db_path):
    assert db.get_latest_portfolio(strategy="s", mode="m", db_path=db_path) is None


def test_filtering_by_strategy_and_mode_excludes_other_rows(db_path):
    db.log_fill(Fill(ticker="AAPL", action="BUY", quantity=1, price=1.0, timestamp=datetime(2026, 7, 4)),
                strategy="trend_following", mode="live", db_path=db_path)
    db.log_fill(Fill(ticker="AAPL", action="BUY", quantity=1, price=1.0, timestamp=datetime(2026, 7, 4)),
                strategy="mean_reversion", mode="live", db_path=db_path)
    db.log_fill(Fill(ticker="AAPL", action="BUY", quantity=1, price=1.0, timestamp=datetime(2026, 7, 4)),
                strategy="trend_following", mode="backtest_1_week", db_path=db_path)

    only_tf_live = db.get_all_fills(strategy="trend_following", mode="live", db_path=db_path)
    assert len(only_tf_live) == 1

    only_tf = db.get_all_fills(strategy="trend_following", db_path=db_path)
    assert len(only_tf) == 2

    everything = db.get_all_fills(db_path=db_path)
    assert len(everything) == 3


def test_results_ordered_by_timestamp_regardless_of_insert_order(db_path):
    db.log_decision(Decision(ticker="AAPL", action="HOLD", reason="x"), "s", "m", datetime(2026, 7, 4, 12, 0), db_path)
    db.log_decision(Decision(ticker="AAPL", action="HOLD", reason="y"), "s", "m", datetime(2026, 7, 4, 9, 0), db_path)
    db.log_decision(Decision(ticker="AAPL", action="HOLD", reason="z"), "s", "m", datetime(2026, 7, 4, 10, 0), db_path)

    rows = db.get_all_decisions(strategy="s", mode="m", db_path=db_path)
    assert [r["reason"] for r in rows] == ["y", "z", "x"]


def test_resolve_url_falls_back_to_sqlite_when_no_database_url_set(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db_path = tmp_path / "bot.db"
    assert _resolve_url(db_path) == f"sqlite:///{db_path}"


def test_resolve_url_prefers_database_url_env_var_when_set(tmp_path, monkeypatch):
    # This is the entire point of the migration (PRD 16.2): a deployed
    # instance can point at hosted Postgres via one env var, with
    # db_path completely ignored, mirroring the existing Alpaca
    # paper/live env-var-swap pattern.
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host:5432/mydb")
    db_path = tmp_path / "bot.db"
    assert _resolve_url(db_path) == "postgresql://user:pass@host:5432/mydb"


def test_two_different_db_files_are_fully_isolated(tmp_path):
    path_a = tmp_path / "a.db"
    path_b = tmp_path / "b.db"
    db.init_db(path_a)
    db.init_db(path_b)

    db.log_decision(Decision(ticker="AAPL", action="HOLD", reason="only in a"), "s", "m", datetime(2026, 7, 4), path_a)

    assert len(db.get_all_decisions(db_path=path_a)) == 1
    assert len(db.get_all_decisions(db_path=path_b)) == 0
