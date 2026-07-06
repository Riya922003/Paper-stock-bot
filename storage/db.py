"""
SQLAlchemy-backed storage for the Decision Log and trade history -- the
audit trail described in the HLD. This is the only place either the
live loop or the backtester should write decisions/fills; the
dashboard reads from here too.

`strategy` and `mode` columns exist so multiple strategies and
multiple backtest periods can share one database without their
results ever being mixed together (see docs/Trading_Bot_HLD_Approach.md
section 5 -- no cherry-picking, each strategy gets its own complete,
separate record).

Engine selection (PRD section 16.2): if the DATABASE_URL environment
variable is set, that's used directly (the deployed instance points
this at a hosted PostgreSQL database). Otherwise, falls back to a
local SQLite file at `db_path` -- this is what local development and
the test suite use, keeping tests fast with zero setup. Every public
function below keeps its original signature and return shape (list of
plain dicts / a single dict / None) so this migration is a drop-in
replacement -- nothing calling into this module needed to change.
"""

import json
import os
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from sqlalchemy import (
    Column,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    insert,
    select,
)

from core.models import Decision, Fill

DEFAULT_DB_PATH = Path(__file__).parent / "bot.db"

metadata = MetaData()

decisions_table = Table(
    "decisions",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("timestamp", String, nullable=False),
    Column("ticker", String, nullable=False),
    Column("action", String, nullable=False),
    Column("reason", String, nullable=False),
    Column("quantity", Float, nullable=False),
    Column("strategy", String, nullable=False),
    Column("mode", String, nullable=False),
)

fills_table = Table(
    "fills",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("timestamp", String, nullable=False),
    Column("ticker", String, nullable=False),
    Column("action", String, nullable=False),
    Column("quantity", Float, nullable=False),
    Column("price", Float, nullable=False),
    Column("order_id", String),
    Column("strategy", String, nullable=False),
    Column("mode", String, nullable=False),
)

portfolio_snapshots_table = Table(
    "portfolio_snapshots",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("timestamp", String, nullable=False),
    Column("cash", Float, nullable=False),
    Column("equity", Float, nullable=False),
    Column("positions_json", String, nullable=False),
    Column("strategy", String, nullable=False),
    Column("mode", String, nullable=False),
)


def _resolve_url(db_path: Path) -> str:
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return database_url
    return f"sqlite:///{db_path}"


@lru_cache(maxsize=None)
def _get_engine(url: str):
    # pool_pre_ping tests each pooled connection with a lightweight
    # query before handing it to the caller, transparently reconnecting
    # if it's gone stale -- needed because hosted Postgres (e.g. Neon)
    # can close idle connections server-side. run_live.py holds one
    # connection open for hours between actual writes (market is closed
    # most of the day), so without this, the first write after a long
    # idle stretch fails with "server closed the connection
    # unexpectedly" instead of just reconnecting.
    return create_engine(url, pool_pre_ping=True)


def _engine_for(db_path: Path):
    return _get_engine(_resolve_url(db_path))


def init_db(db_path: Path = DEFAULT_DB_PATH) -> None:
    metadata.create_all(_engine_for(db_path))


def log_decision(decision: Decision, strategy: str, mode: str, timestamp: datetime,
                  db_path: Path = DEFAULT_DB_PATH) -> None:
    engine = _engine_for(db_path)
    with engine.begin() as conn:
        conn.execute(
            insert(decisions_table).values(
                timestamp=timestamp.isoformat(),
                ticker=decision.ticker,
                action=decision.action,
                reason=decision.reason,
                quantity=decision.quantity,
                strategy=strategy,
                mode=mode,
            )
        )


def log_fill(fill: Fill, strategy: str, mode: str, db_path: Path = DEFAULT_DB_PATH) -> None:
    engine = _engine_for(db_path)
    with engine.begin() as conn:
        conn.execute(
            insert(fills_table).values(
                timestamp=fill.timestamp.isoformat(),
                ticker=fill.ticker,
                action=fill.action,
                quantity=fill.quantity,
                price=fill.price,
                order_id=fill.order_id,
                strategy=strategy,
                mode=mode,
            )
        )


def save_portfolio_snapshot(cash: float, equity: float, positions: dict, strategy: str,
                             mode: str, timestamp: datetime,
                             db_path: Path = DEFAULT_DB_PATH) -> None:
    engine = _engine_for(db_path)
    with engine.begin() as conn:
        conn.execute(
            insert(portfolio_snapshots_table).values(
                timestamp=timestamp.isoformat(),
                cash=cash,
                equity=equity,
                positions_json=json.dumps(positions),
                strategy=strategy,
                mode=mode,
            )
        )


def _select(table: Table, strategy: str | None, mode: str | None, db_path: Path) -> list[dict]:
    engine = _engine_for(db_path)
    query = select(table)
    if strategy:
        query = query.where(table.c.strategy == strategy)
    if mode:
        query = query.where(table.c.mode == mode)
    query = query.order_by(table.c.timestamp)

    with engine.begin() as conn:
        rows = conn.execute(query).mappings().all()
        return [dict(row) for row in rows]


def get_all_fills(strategy: str = None, mode: str = None, db_path: Path = DEFAULT_DB_PATH):
    return _select(fills_table, strategy, mode, db_path)


def get_all_decisions(strategy: str = None, mode: str = None, db_path: Path = DEFAULT_DB_PATH):
    return _select(decisions_table, strategy, mode, db_path)


def get_latest_portfolio(strategy: str = None, mode: str = None, db_path: Path = DEFAULT_DB_PATH):
    rows = _select(portfolio_snapshots_table, strategy, mode, db_path)
    return rows[-1] if rows else None


def get_all_portfolio_snapshots(strategy: str = None, mode: str = None, db_path: Path = DEFAULT_DB_PATH):
    return _select(portfolio_snapshots_table, strategy, mode, db_path)
