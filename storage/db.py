"""
SQLite-backed storage for the Decision Log and trade history -- the
audit trail described in the HLD. This is the only place either the
live loop or the backtester should write decisions/fills; the
dashboard reads from here too.

`strategy` and `mode` columns exist so multiple strategies and
multiple backtest periods can share one database without their
results ever being mixed together (see docs/Trading_Bot_HLD_Approach.md
section 5 -- no cherry-picking, each strategy gets its own complete,
separate record).
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from core.models import Decision, Fill

DEFAULT_DB_PATH = Path(__file__).parent / "bot.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    ticker TEXT NOT NULL,
    action TEXT NOT NULL,
    reason TEXT NOT NULL,
    quantity REAL NOT NULL,
    strategy TEXT NOT NULL,
    mode TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    ticker TEXT NOT NULL,
    action TEXT NOT NULL,
    quantity REAL NOT NULL,
    price REAL NOT NULL,
    order_id TEXT,
    strategy TEXT NOT NULL,
    mode TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    cash REAL NOT NULL,
    equity REAL NOT NULL,
    positions_json TEXT NOT NULL,
    strategy TEXT NOT NULL,
    mode TEXT NOT NULL
);
"""


@contextmanager
def get_connection(db_path: Path = DEFAULT_DB_PATH):
    conn = sqlite3.connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


def init_db(db_path: Path = DEFAULT_DB_PATH) -> None:
    with get_connection(db_path) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


def log_decision(decision: Decision, strategy: str, mode: str, timestamp: datetime,
                  db_path: Path = DEFAULT_DB_PATH) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            "INSERT INTO decisions (timestamp, ticker, action, reason, quantity, strategy, mode) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (timestamp.isoformat(), decision.ticker, decision.action,
             decision.reason, decision.quantity, strategy, mode),
        )
        conn.commit()


def log_fill(fill: Fill, strategy: str, mode: str, db_path: Path = DEFAULT_DB_PATH) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            "INSERT INTO fills (timestamp, ticker, action, quantity, price, order_id, strategy, mode) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (fill.timestamp.isoformat(), fill.ticker, fill.action, fill.quantity,
             fill.price, fill.order_id, strategy, mode),
        )
        conn.commit()


def save_portfolio_snapshot(cash: float, equity: float, positions: dict, strategy: str,
                             mode: str, timestamp: datetime,
                             db_path: Path = DEFAULT_DB_PATH) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            "INSERT INTO portfolio_snapshots (timestamp, cash, equity, positions_json, strategy, mode) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (timestamp.isoformat(), cash, equity, json.dumps(positions), strategy, mode),
        )
        conn.commit()


def _select(table: str, strategy: str | None, mode: str | None, db_path: Path):
    query = f"SELECT * FROM {table}"
    conditions, params = [], []
    if strategy:
        conditions.append("strategy = ?")
        params.append(strategy)
    if mode:
        conditions.append("mode = ?")
        params.append(mode)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY timestamp"
    with get_connection(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(query, params).fetchall()]


def get_all_fills(strategy: str = None, mode: str = None, db_path: Path = DEFAULT_DB_PATH):
    return _select("fills", strategy, mode, db_path)


def get_all_decisions(strategy: str = None, mode: str = None, db_path: Path = DEFAULT_DB_PATH):
    return _select("decisions", strategy, mode, db_path)


def get_latest_portfolio(strategy: str = None, mode: str = None, db_path: Path = DEFAULT_DB_PATH):
    rows = _select("portfolio_snapshots", strategy, mode, db_path)
    return rows[-1] if rows else None
