"""
UI -- a Streamlit dashboard reading directly from the same SQLite
database the live bot and backtester write to. No separate backend
server for the MVP; if a non-Python frontend is ever needed, put a
thin API layer in front of storage/db.py without touching Strategy
Core, Order Handler, or Portfolio State.

Run with: streamlit run dashboard/app.py
"""

import os
import sys
from pathlib import Path

# storage/, core/, etc. live at the repo root, one level up from this
# file. Depending on how the hosting platform invokes this script, the
# repo root isn't always on sys.path automatically (confirmed on
# Streamlit Community Cloud -- it only put dashboard/ itself on the
# path, causing "ModuleNotFoundError: No module named 'storage'").
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# Streamlit Community Cloud's "Secrets" don't automatically become
# environment variables the way a local .env does -- bridge them here
# so storage/db.py's os.getenv("DATABASE_URL") works the same way in
# both places (see docs/PRD.md section 16.2). Locally there's no
# .streamlit/secrets.toml at all (we use .env instead), and accessing
# st.secrets in that case raises rather than returning empty -- catch
# that and just fall back to whatever .env already loaded.
try:
    if "DATABASE_URL" in st.secrets:
        os.environ["DATABASE_URL"] = st.secrets["DATABASE_URL"]
except Exception:
    pass

from report import compute_metrics, reconstruct_trades
from storage import db

# Safe to call every time -- only creates tables if they don't already
# exist. Without this, a freshly provisioned database (e.g. a new
# Neon/Postgres instance with DATABASE_URL set but never initialized
# by backtest.py/run_live.py yet) has no tables at all, and every
# query below fails with "relation does not exist".
db.init_db()

# Matches backtest.py / run_live.py's STARTING_CASH -- position sizing
# and return % are always relative to this fixed starting amount, not
# current cash (PRD 5.3), so it's not something the dashboard can infer
# from the data alone.
STARTING_CAPITAL = 100_000.0

st.set_page_config(page_title="Paper Trading Bot", layout="wide")
st.title("Paper Trading Bot -- Dashboard")

mode = st.sidebar.selectbox("Mode", ["live", "backtest_1_week", "backtest_1_month",
                                      "backtest_3_months", "backtest_6_months",
                                      "backtest_1_year", "backtest_3_years"])
strategy = st.sidebar.selectbox("Strategy", ["mean_reversion", "trend_following", "breakout"])

snapshots = db.get_all_portfolio_snapshots(strategy=strategy, mode=mode)
fills = db.get_all_fills(strategy=strategy, mode=mode)

if not snapshots:
    st.info("No portfolio snapshots yet for this strategy/mode.")
else:
    equity_curve = [s["equity"] for s in snapshots]
    trades = reconstruct_trades(fills)
    metrics = compute_metrics(trades, equity_curve, STARTING_CAPITAL, equity_curve[-1])

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Equity", f"${metrics.ending_capital:,.2f}")
    col2.metric("Net P&L", f"${metrics.net_pnl:,.2f}", f"{metrics.return_pct:+.2f}%")
    col3.metric("Win rate", f"{metrics.win_rate:.1f}%", f"{metrics.total_trades} trades")
    col4.metric("Max drawdown", f"{metrics.max_drawdown_pct:.2f}%")
    col5.metric("Last updated", snapshots[-1]["timestamp"])

    st.subheader("Equity curve")
    equity_df = pd.DataFrame(
        {"equity": equity_curve},
        index=pd.to_datetime([s["timestamp"] for s in snapshots]),
    )
    st.line_chart(equity_df)

st.subheader("Trade log")
st.dataframe(pd.DataFrame(fills), use_container_width=True)

st.subheader("Decision log")
decisions = db.get_all_decisions(strategy=strategy, mode=mode)
st.dataframe(pd.DataFrame(decisions), use_container_width=True)
