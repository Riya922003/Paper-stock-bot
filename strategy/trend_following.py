"""
Trend-following strategy -- the MVP strategy (docs/PRD.md section 5).

EMA(9)/EMA(21) crossover, filtered by RSI(14), with a fixed stop-loss /
take-profit safety net. Selected when STRATEGY=trend_following.

Must remain a pure function: no I/O, no network calls, no datetime.now()
-- read time only from snapshot.timestamp. This is what keeps backtest and
live runs provably identical.
"""

import pandas_ta as ta

from core.models import Decision, MarketSnapshot, PortfolioState

EMA_FAST = 9
EMA_SLOW = 21
RSI_PERIOD = 14
RSI_MIN = 40
RSI_MAX = 65

STOP_LOSS_PCT = 0.03
TAKE_PROFIT_PCT = 0.06

POSITION_SIZE_PCT = 0.125
MAX_POSITIONS = 4


def _indicators(bars):
    """Attach EMA_FAST/EMA_SLOW/RSI columns to a copy of the bars frame.

    pandas-ta returns None (not a NaN-filled Series) when there are fewer
    bars than the indicator's period -- normalize that to NaN so
    downstream comparisons (e.g. curr["ema_fast"] > curr["ema_slow"])
    safely evaluate to False instead of raising TypeError on None <= None.
    """
    df = bars.copy()
    df["ema_fast"] = ta.ema(df["close"], length=EMA_FAST)
    df["ema_slow"] = ta.ema(df["close"], length=EMA_SLOW)
    df["rsi"] = ta.rsi(df["close"], length=RSI_PERIOD)
    df[["ema_fast", "ema_slow", "rsi"]] = df[["ema_fast", "ema_slow", "rsi"]].astype(float)
    return df


def _crossed_above(df):
    # Fewer than 2 bars (e.g. the very first candle of a backtest, with
    # no history before it) -- nothing to compare, so no crossover yet.
    if len(df) < 2:
        return False
    prev, curr = df.iloc[-2], df.iloc[-1]
    return prev["ema_fast"] <= prev["ema_slow"] and curr["ema_fast"] > curr["ema_slow"]


def _crossed_below(df):
    if len(df) < 2:
        return False
    prev, curr = df.iloc[-2], df.iloc[-1]
    return prev["ema_fast"] >= prev["ema_slow"] and curr["ema_fast"] < curr["ema_slow"]


def _decide_sell(ticker: str, price: float, position, df) -> Decision:
    entry = position.avg_entry_price
    change_pct = (price - entry) / entry

    if change_pct <= -STOP_LOSS_PCT:
        return Decision(
            ticker=ticker,
            action="SELL",
            reason=f"Stop-loss: entry ${entry:.2f}, current ${price:.2f} ({change_pct:.2%})",
            quantity=position.qty,
        )

    if change_pct >= TAKE_PROFIT_PCT:
        return Decision(
            ticker=ticker,
            action="SELL",
            reason=f"Take-profit: entry ${entry:.2f}, current ${price:.2f} ({change_pct:.2%})",
            quantity=position.qty,
        )

    if _crossed_below(df):
        return Decision(
            ticker=ticker,
            action="SELL",
            reason="EMA9 crossed below EMA21, trend invalidated",
            quantity=position.qty,
        )

    return Decision(ticker=ticker, action="HOLD", reason="Position open, no exit signal")


def _decide_buy(ticker: str, price: float, portfolio: PortfolioState, df) -> Decision:
    rsi = df.iloc[-1]["rsi"]

    if not _crossed_above(df):
        return Decision(ticker=ticker, action="HOLD", reason="Hold: no buy signal, no EMA9/EMA21 crossover")

    if not (RSI_MIN <= rsi <= RSI_MAX):
        return Decision(
            ticker=ticker,
            action="HOLD",
            reason=f"Hold: EMA crossed but RSI={rsi:.1f} outside [{RSI_MIN}, {RSI_MAX}]",
        )

    if len(portfolio.positions) >= MAX_POSITIONS:
        return Decision(
            ticker=ticker,
            action="HOLD",
            reason=f"Hold: signal valid but at max positions ({MAX_POSITIONS})",
        )

    position_size = portfolio.starting_capital * POSITION_SIZE_PCT
    if portfolio.cash < position_size:
        return Decision(
            ticker=ticker,
            action="HOLD",
            reason=f"Hold: signal valid but insufficient cash (${portfolio.cash:.2f} < ${position_size:.2f})",
        )

    quantity = round(position_size / price, 2)
    return Decision(
        ticker=ticker,
        action="BUY",
        reason=f"EMA9 crossed above EMA21, RSI={rsi:.1f}",
        quantity=quantity,
    )


def decide(snapshot: MarketSnapshot, portfolio: PortfolioState) -> list[Decision]:
    """
    Pure function. No side effects. No I/O.
    Returns exactly one Decision per ticker in snapshot.
    """
    decisions = []

    for ticker, data in snapshot.tickers.items():
        if data.is_stale:
            decisions.append(
                Decision(ticker=ticker, action="HOLD", reason="Hold: stale or missing market data")
            )
            continue

        df = _indicators(data.bars)
        position = portfolio.positions.get(ticker)

        if position is not None:
            decisions.append(_decide_sell(ticker, data.last_price, position, df))
        else:
            decisions.append(_decide_buy(ticker, data.last_price, portfolio, df))

    return decisions
