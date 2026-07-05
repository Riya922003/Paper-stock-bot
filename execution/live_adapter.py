"""
Live Order Handler -- places real orders through Alpaca (paper account
for now; switching to a real account later is just an API key change,
see docs/Trading_Bot_HLD_Approach.md section 7).

Shares its function signature with backtest_adapter.py on purpose --
the run loop calls whichever one is active without knowing the
difference.

Order failure handling (PRD Component 5): if anything goes wrong
(network error, insufficient funds, market closed, order never fills),
this logs the problem and returns None instead of placing/confirming
the order. It does not retry immediately and does not raise -- the
next scheduled cycle will naturally re-evaluate and may place the
order again.
"""

import os
import time

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, OrderStatus, TimeInForce
from alpaca.trading.requests import MarketOrderRequest

from core.models import Decision, Fill, MarketSnapshot

FILL_POLL_TIMEOUT_SECONDS = 30
FILL_POLL_INTERVAL_SECONDS = 2

_TERMINAL_STATUSES = {OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.REJECTED, OrderStatus.EXPIRED}


def _order_to_fill(decision: Decision, order) -> Fill | None:
    """A partially filled or still-pending order isn't a completed trade yet."""
    if order.status != OrderStatus.FILLED or order.filled_avg_price is None:
        return None
    return Fill(
        ticker=decision.ticker,
        action=decision.action,
        quantity=float(order.filled_qty),
        price=float(order.filled_avg_price),
        timestamp=order.filled_at,
        order_id=str(order.id),
    )


def _wait_for_fill(client: TradingClient, order_id, timeout: float = FILL_POLL_TIMEOUT_SECONDS,
                    interval: float = FILL_POLL_INTERVAL_SECONDS):
    """Polls Alpaca until the order reaches a terminal status or the timeout elapses."""
    waited = 0.0
    order = client.get_order_by_id(order_id)
    while order.status not in _TERMINAL_STATUSES and waited < timeout:
        time.sleep(interval)
        waited += interval
        order = client.get_order_by_id(order_id)
    return order


def _make_client() -> TradingClient:
    return TradingClient(os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY"), paper=True)


def submit_order(
    decision: Decision,
    snapshot: MarketSnapshot,
    client: TradingClient = None,
    poll_timeout: float = FILL_POLL_TIMEOUT_SECONDS,
    poll_interval: float = FILL_POLL_INTERVAL_SECONDS,
) -> Fill | None:
    if decision.action == "HOLD":
        return None

    if client is None:
        client = _make_client()

    try:
        request = MarketOrderRequest(
            symbol=decision.ticker,
            qty=decision.quantity,
            side=OrderSide.BUY if decision.action == "BUY" else OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        )
        order = client.submit_order(request)
        final_order = _wait_for_fill(client, order.id, timeout=poll_timeout, interval=poll_interval)
        fill = _order_to_fill(decision, final_order)
        if fill is None:
            print(f"[live_adapter] Order for {decision.ticker} did not fill (status={final_order.status})")
        return fill
    except Exception as e:
        print(f"[live_adapter] Order failed for {decision.ticker}: {e}")
        return None
