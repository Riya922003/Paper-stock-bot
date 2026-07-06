"""
Entry point: runs the live paper-trading loop on a schedule.

Usage: python run_live.py

Also runs a minimal HTTP health-check endpoint alongside the scheduler
so this can be hosted on Render's free "Web Service" tier (which
requires binding to $PORT and responding to HTTP requests) with
UptimeRobot pinging it to prevent the free tier's 15-minute inactivity
sleep. The endpoint has nothing to do with the trading logic itself --
it exists purely to satisfy the hosting platform's requirements.
"""

import os
from http.server import BaseHTTPRequestHandler, HTTPServer

from alpaca.trading.client import TradingClient
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

from core.models import PortfolioState
from data import live_feed
from execution import live_adapter
from portfolio.state import apply_fill
from storage import db
from strategy import get_strategy

load_dotenv()

STARTING_CASH = 100_000.0
CHECK_INTERVAL_MINUTES = int(os.getenv("CHECK_INTERVAL_MINUTES", 5))

portfolio = PortfolioState(cash=STARTING_CASH, starting_capital=STARTING_CASH)
_trading_client = TradingClient(os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY"), paper=True)


def tick() -> None:
    if not live_feed.is_market_open(_trading_client):
        print("Market is closed -- skipping this cycle.")
        return

    strategy_name = os.getenv("STRATEGY", "trend_following")
    decide = get_strategy(strategy_name)

    snapshot = live_feed.get_snapshot()
    decisions = decide(snapshot, portfolio)

    for decision in decisions:
        db.log_decision(decision, strategy_name, mode="live", timestamp=snapshot.timestamp)
        fill = live_adapter.submit_order(decision, snapshot)
        if fill:
            db.log_fill(fill, strategy_name, mode="live")
            apply_fill(portfolio, fill)

    db.save_portfolio_snapshot(
        cash=portfolio.cash,
        equity=portfolio.equity(snapshot),
        positions={t: p.qty for t, p in portfolio.positions.items()},
        strategy=strategy_name,
        mode="live",
        timestamp=snapshot.timestamp,
    )


class _HealthHandler(BaseHTTPRequestHandler):
    """Responds 200 OK to anything -- Render's health check and
    UptimeRobot's pings both just need a successful HTTP response,
    not any particular content."""

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass  # silence per-request logging -- would spam every 5 min from UptimeRobot


def main() -> None:
    db.init_db()
    # BackgroundScheduler (not BlockingScheduler) runs tick() in its
    # own thread, leaving the main thread free to run the health
    # server, which is what actually keeps the process alive here.
    scheduler = BackgroundScheduler()
    scheduler.add_job(tick, "interval", minutes=CHECK_INTERVAL_MINUTES)
    print(f"Starting live loop, checking every {CHECK_INTERVAL_MINUTES} minutes...")
    tick()  # run once immediately on startup
    scheduler.start()

    port = int(os.getenv("PORT", 8000))
    print(f"Health check server listening on port {port}...")
    HTTPServer(("0.0.0.0", port), _HealthHandler).serve_forever()


if __name__ == "__main__":
    main()
