"""
Strategy registry -- the swappable slot described in the HLD diagram.

Set STRATEGY in .env to one of the keys below; run_live.py and
backtest.py both load whichever one is configured, through
get_strategy(). Every strategy function must share the exact same
signature:

    decide(snapshot: MarketSnapshot, portfolio: PortfolioState) -> list[Decision]
"""

from strategy import mean_reversion, trend_following, breakout

STRATEGIES = {
    "mean_reversion": mean_reversion.decide,
    "trend_following": trend_following.decide,
    "breakout": breakout.decide,
}


def get_strategy(name: str):
    try:
        return STRATEGIES[name]
    except KeyError:
        raise ValueError(f"Unknown strategy '{name}'. Available: {list(STRATEGIES)}")
