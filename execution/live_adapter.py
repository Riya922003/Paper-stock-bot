"""
Live Order Handler -- places real orders through Alpaca (paper account
for now; switching to a real account later is just an API key change,
see docs/Trading_Bot_HLD_Approach.md section 7).

Shares its function signature with backtest_adapter.py on purpose --
the run loop calls whichever one is active without knowing the
difference.

TODO: use alpaca-py's TradingClient to submit a market order for
decision.quantity shares of decision.ticker, then wait for / poll the
fill and return it as a Fill.
"""

from core.models import Decision, MarketSnapshot, Fill


def submit_order(decision: Decision, snapshot: MarketSnapshot) -> Fill | None:
    if decision.action == "HOLD":
        return None
    raise NotImplementedError("Wire up alpaca-py TradingClient here")
