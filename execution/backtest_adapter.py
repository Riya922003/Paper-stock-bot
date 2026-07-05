"""
Backtest Order Handler -- simulates a fill using the NEXT candle's open
price (never the current snapshot's price -- that would be lookahead
bias, since the strategy decided using only data up to now and can't
know the current candle's own outcome yet).

Shares its function signature with live_adapter.py on purpose -- the
run loop calls whichever one is active without knowing the difference.

Slippage: 0.1% of trade value, applied against the trader (PRD 8.3) --
buys fill slightly above the next open, sells fill slightly below it.
"""

from core.models import Decision, Fill, MarketSnapshot

SLIPPAGE_PCT = 0.001


def submit_order(decision: Decision, snapshot: MarketSnapshot) -> Fill | None:
    if decision.action == "HOLD":
        return None

    ticker_data = snapshot.tickers[decision.ticker]
    if ticker_data.next_open is None:
        # No future bar to fill against (e.g. the last candle of a
        # backtest period) -- can't simulate a realistic fill.
        return None

    if decision.action == "BUY":
        price = ticker_data.next_open * (1 + SLIPPAGE_PCT)
    else:  # SELL
        price = ticker_data.next_open * (1 - SLIPPAGE_PCT)

    return Fill(
        ticker=decision.ticker,
        action=decision.action,
        quantity=decision.quantity,
        price=price,
        timestamp=snapshot.timestamp,
    )
