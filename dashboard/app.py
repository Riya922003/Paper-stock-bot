"""
UI -- a Streamlit dashboard reading directly from the same SQLite
database the live bot and backtester write to. No separate backend
server for the MVP; if a non-Python frontend is ever needed, put a
thin API layer in front of storage/db.py without touching Strategy
Core, Order Handler, or Portfolio State.

Run with: streamlit run dashboard/app.py
"""

import pandas as pd
import streamlit as st

from storage import db

st.set_page_config(page_title="Paper Trading Bot", layout="wide")
st.title("Paper Trading Bot -- Dashboard")

mode = st.sidebar.selectbox("Mode", ["live", "backtest_1_week", "backtest_1_month",
                                      "backtest_3_months", "backtest_6_months",
                                      "backtest_1_year", "backtest_3_years"])
strategy = st.sidebar.selectbox("Strategy", ["mean_reversion", "trend_following", "breakout"])

portfolio = db.get_latest_portfolio(strategy=strategy, mode=mode)

col1, col2, col3 = st.columns(3)
if portfolio:
    col1.metric("Cash", f"${portfolio['cash']:,.2f}")
    col2.metric("Equity", f"${portfolio['equity']:,.2f}")
    col3.metric("Last updated", portfolio["timestamp"])
else:
    st.info("No portfolio snapshots yet for this strategy/mode.")

st.subheader("Trade log")
fills = db.get_all_fills(strategy=strategy, mode=mode)
st.dataframe(pd.DataFrame(fills), use_container_width=True)

st.subheader("Decision log")
decisions = db.get_all_decisions(strategy=strategy, mode=mode)
st.dataframe(pd.DataFrame(decisions), use_container_width=True)
