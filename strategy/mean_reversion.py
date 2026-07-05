"""
Mean-reversion strategy -- NOT YET IMPLEMENTED.

Rule sketch (exact numbers not finalized -- see
docs/Trading_Bot_HLD_Approach.md, section 4):
- BUY a ticker when its price drops unusually far below its recent
  average
- SELL when: stop-loss hit, profit-target hit, or price has returned
  to/above the recent average (the original reason for buying is gone)

Must remain a pure function: no I/O, no network calls, no
datetime.now() -- read time only from snapshot.timestamp. This is
what keeps backtest and live runs provably identical.
"""

from core.models import MarketSnapshot, PortfolioState, Decision


def decide(snapshot: MarketSnapshot, portfolio: PortfolioState) -> list[Decision]:
    raise NotImplementedError("Fill in mean-reversion rule thresholds first")
