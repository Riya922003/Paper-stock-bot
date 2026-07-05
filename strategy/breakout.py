"""
Breakout strategy -- NOT YET IMPLEMENTED.

Rule sketch (exact numbers not finalized -- see
docs/Trading_Bot_HLD_Approach.md, section 4):
- BUY a ticker when it pushes above its recent high (e.g. highest
  close in the last N bars)
- SELL on a pullback below that level, or the standard stop-loss /
  profit-target safety net

Must remain a pure function: no I/O, no network calls, no
datetime.now() -- read time only from snapshot.timestamp.
"""

from core.models import MarketSnapshot, PortfolioState, Decision


def decide(snapshot: MarketSnapshot, portfolio: PortfolioState) -> list[Decision]:
    raise NotImplementedError("Fill in breakout rule thresholds first")
