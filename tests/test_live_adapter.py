"""
Unit tests for execution/live_adapter.py. All against a fake Alpaca
client -- no real network access, no real orders ever placed.

The real alpaca-py shapes this depends on (MarketOrderRequest fields,
Order fields, OrderStatus/OrderSide/TimeInForce enum member names) were
verified against the installed library while building this module, not
guessed from memory.
"""

from datetime import datetime

from alpaca.trading.enums import OrderStatus

from core.models import Decision
from execution.live_adapter import _order_to_fill, _wait_for_fill, submit_order


class FakeOrder:
    def __init__(self, id="order-1", status=OrderStatus.FILLED, filled_qty=10.0, filled_avg_price=100.5, filled_at=None):
        self.id = id
        self.status = status
        self.filled_qty = filled_qty
        self.filled_avg_price = filled_avg_price
        self.filled_at = filled_at or datetime(2026, 7, 4, 10, 5)


class FakeClient:
    def __init__(self, submit_result=None, poll_sequence=None, raise_on_submit=None):
        self.submit_result = submit_result
        self.poll_sequence = list(poll_sequence) if poll_sequence else None
        self.raise_on_submit = raise_on_submit
        self.submitted_requests = []

    def submit_order(self, request):
        if self.raise_on_submit:
            raise self.raise_on_submit
        self.submitted_requests.append(request)
        return self.submit_result

    def get_order_by_id(self, order_id):
        if self.poll_sequence:
            return self.poll_sequence.pop(0)
        return self.submit_result


def test_hold_returns_no_fill_without_touching_client():
    decision = Decision(ticker="AAPL", action="HOLD", reason="no signal")
    assert submit_order(decision, snapshot=None, client=FakeClient()) is None


def test_order_to_fill_when_filled():
    decision = Decision(ticker="AAPL", action="BUY", reason="signal", quantity=10)
    order = FakeOrder(status=OrderStatus.FILLED, filled_qty=10.0, filled_avg_price=150.25, id="abc123")
    fill = _order_to_fill(decision, order)
    assert fill is not None
    assert fill.ticker == "AAPL"
    assert fill.action == "BUY"
    assert fill.quantity == 10.0
    assert fill.price == 150.25
    assert fill.order_id == "abc123"


def test_order_to_fill_when_not_filled_returns_none():
    decision = Decision(ticker="AAPL", action="BUY", reason="signal", quantity=10)
    order = FakeOrder(status=OrderStatus.NEW, filled_avg_price=None)
    assert _order_to_fill(decision, order) is None


def test_wait_for_fill_polls_until_filled():
    pending = FakeOrder(status=OrderStatus.NEW, filled_avg_price=None)
    filled = FakeOrder(status=OrderStatus.FILLED, filled_avg_price=100.0)
    client = FakeClient(poll_sequence=[pending, pending, filled])
    result = _wait_for_fill(client, "order-1", timeout=10, interval=0)
    assert result.status == OrderStatus.FILLED


def test_wait_for_fill_gives_up_after_timeout():
    pending = FakeOrder(status=OrderStatus.NEW, filled_avg_price=None)
    client = FakeClient(poll_sequence=[pending] * 100)
    result = _wait_for_fill(client, "order-1", timeout=0, interval=0)
    assert result.status == OrderStatus.NEW


def test_submit_order_returns_fill_on_success():
    decision = Decision(ticker="AAPL", action="BUY", reason="signal", quantity=10)
    submitted = FakeOrder(id="order-1", status=OrderStatus.NEW, filled_avg_price=None)
    filled = FakeOrder(id="order-1", status=OrderStatus.FILLED, filled_qty=10.0, filled_avg_price=150.0)
    client = FakeClient(submit_result=submitted, poll_sequence=[filled])

    fill = submit_order(decision, snapshot=None, client=client)

    assert fill is not None
    assert fill.price == 150.0
    assert len(client.submitted_requests) == 1
    assert client.submitted_requests[0].symbol == "AAPL"
    assert client.submitted_requests[0].qty == 10


def test_submit_order_returns_none_on_api_failure_not_raise():
    # PRD Component 5: an order failure must be logged and return None,
    # never raise and kill the run loop.
    decision = Decision(ticker="AAPL", action="BUY", reason="signal", quantity=10)
    client = FakeClient(raise_on_submit=ConnectionError("network down"))
    fill = submit_order(decision, snapshot=None, client=client)
    assert fill is None


def test_submit_order_returns_none_when_order_never_fills():
    decision = Decision(ticker="AAPL", action="BUY", reason="signal", quantity=10)
    submitted = FakeOrder(id="order-1", status=OrderStatus.NEW, filled_avg_price=None)
    client = FakeClient(submit_result=submitted, poll_sequence=[submitted])
    fill = submit_order(decision, snapshot=None, client=client, poll_timeout=0, poll_interval=0)
    assert fill is None
