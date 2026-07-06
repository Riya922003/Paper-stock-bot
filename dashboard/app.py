"""
UI -- a Streamlit dashboard reading directly from the same database
the live bot and backtester write to. No separate backend server for
the MVP; if a non-Python frontend is ever needed, put a thin API
layer in front of storage/db.py without touching Strategy Core, Order
Handler, or Portfolio State.

Run with: streamlit run dashboard/app.py
"""

import json
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

from report import COMMISSION, SLIPPAGE_PCT, compute_metrics, reconstruct_trades
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

STRATEGY_BLURBS = {
    "trend_following": (
        "Buys when short-term momentum (EMA9) crosses above long-term momentum (EMA21), "
        "confirmed by RSI(14) between 40-65 so it's not chasing an already-overbought spike. "
        "Exits on a -3% stop-loss, +6% take-profit, or the trend reversing -- whichever hits first."
    ),
    "mean_reversion": "Candidate strategy -- not yet implemented.",
    "breakout": "Candidate strategy -- not yet implemented.",
}

ACTION_LABELS = {"BUY": "🟢 BUY", "SELL": "🔴 SELL", "HOLD": "⚪ HOLD"}

st.set_page_config(page_title="Paper Trading Bot", layout="wide", page_icon="📈")

st.markdown(
    """
    <style>
    [data-testid="stMetric"] {
        background-color: rgba(255,255,255,0.03);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 10px;
        padding: 14px 18px 10px 18px;
    }
    [data-testid="stMetricLabel"] { font-size: 0.82rem; opacity: 0.7; }
    </style>
    """,
    unsafe_allow_html=True,
)


def with_action_labels(df: pd.DataFrame) -> pd.DataFrame:
    """
    st.dataframe's grid renderer doesn't respect a pandas Styler's cell
    CSS (verified: background-color/color from .style.map() render as
    plain default text, not colored) -- an emoji-prefixed label is a
    visual cue guaranteed to actually show up.
    """
    df = df.copy()
    df["action"] = df["action"].map(lambda v: ACTION_LABELS.get(v, v))
    return df


def current_positions_df(fills: list, positions_json: str) -> pd.DataFrame:
    held = json.loads(positions_json) if positions_json else {}
    rows = []
    for ticker, qty in held.items():
        buys = [f for f in fills if f["ticker"] == ticker and f["action"] == "BUY"]
        entry = buys[-1] if buys else None
        rows.append(
            {
                "ticker": ticker,
                "quantity": qty,
                "entry_price": entry["price"] if entry else None,
                "entry_time": entry["timestamp"] if entry else None,
            }
        )
    return pd.DataFrame(rows)


st.title("📈 Paper Trading Bot")
st.caption("Automated EMA/RSI trend-following strategy, trading 8 US stocks in an Alpaca paper account.")

with st.sidebar:
    st.header("Filters")
    mode = st.selectbox("Mode", ["live", "backtest_1_week", "backtest_1_month",
                                  "backtest_3_months", "backtest_6_months",
                                  "backtest_1_year", "backtest_3_years"])
    strategy = st.selectbox("Strategy", ["trend_following", "mean_reversion", "breakout"])
    st.divider()
    st.caption(f"**{strategy}**")
    st.caption(STRATEGY_BLURBS.get(strategy, ""))

snapshots = db.get_all_portfolio_snapshots(strategy=strategy, mode=mode)
fills = db.get_all_fills(strategy=strategy, mode=mode)
decisions = db.get_all_decisions(strategy=strategy, mode=mode)

tab_overview, tab_trades, tab_decisions = st.tabs(["📊 Overview", "💰 Trade Log", "🧾 Decision Log"])

with tab_overview:
    if not snapshots:
        st.info("No portfolio snapshots yet for this strategy/mode.")
    else:
        equity_curve = [s["equity"] for s in snapshots]
        trades = reconstruct_trades(fills)
        metrics = compute_metrics(trades, equity_curve, STARTING_CAPITAL, equity_curve[-1])

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Starting capital", f"${metrics.starting_capital:,.2f}")
        col2.metric("Equity", f"${metrics.ending_capital:,.2f}")
        col3.metric("Net P&L", f"${metrics.net_pnl:,.2f}", f"{metrics.return_pct:+.2f}%")
        col4.metric("Max drawdown", f"{metrics.max_drawdown_pct:.2f}%")

        col5, col6, col7, col8 = st.columns(4)
        col5.metric("Total trades", metrics.total_trades)
        col6.metric("Winning trades", metrics.winning_trades)
        col7.metric("Losing trades", metrics.losing_trades)
        col8.metric("Win rate", f"{metrics.win_rate:.1f}%")

        st.caption(
            f"Last updated: {snapshots[-1]['timestamp']}  ·  "
            f"Slippage assumption: {SLIPPAGE_PCT * 100:.2f}% (applied against the trader on every fill)  ·  "
            f"Commission assumption: ${COMMISSION:.2f} (Alpaca is commission-free)"
        )

        st.subheader("Equity curve")
        equity_df = pd.DataFrame(
            {"Equity ($)": equity_curve},
            index=pd.to_datetime([s["timestamp"] for s in snapshots]),
        )
        st.area_chart(equity_df)

        st.subheader("Current positions")
        positions_df = current_positions_df(fills, snapshots[-1]["positions_json"])
        if positions_df.empty:
            st.caption("No open positions right now.")
        else:
            st.dataframe(positions_df, width="stretch", hide_index=True)

with tab_trades:
    st.caption(f"{len(fills)} completed fills for {strategy} / {mode}.")
    if fills:
        st.dataframe(with_action_labels(pd.DataFrame(fills)), width="stretch", hide_index=True)
    else:
        st.caption("No fills yet.")

with tab_decisions:
    st.caption(
        f"{len(decisions)} decisions logged for {strategy} / {mode} -- every cycle, including HOLDs, "
        "per the anti-cherry-picking rule (no decision is ever skipped or hidden)."
    )
    action_filter = st.multiselect("Filter by action", ["BUY", "SELL", "HOLD"], default=["BUY", "SELL", "HOLD"])
    filtered = [d for d in decisions if d["action"] in action_filter]

    row_limit = st.select_slider("Rows to show (most recent first)", options=[50, 200, 1000, 5000], value=200)
    recent = list(reversed(filtered))[:row_limit]

    st.caption(f"Showing {len(recent)} of {len(filtered)} matching decisions.")
    if recent:
        st.dataframe(with_action_labels(pd.DataFrame(recent)), width="stretch", hide_index=True)
    else:
        st.caption("No decisions match this filter.")
