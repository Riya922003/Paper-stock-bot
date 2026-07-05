"""
Report Generator (Component 6, PRD section 8.4) -- turns the logged
decisions/fills/portfolio history for one strategy+period into the
metrics and files the task requires.

Never re-runs the strategy; only reads what backtest.py already
recorded. That's the whole point -- these numbers can't have been
quietly adjusted after the fact, which is the anti-cherry-picking proof
the task asks for.

Usage: called from backtest.py at the end of each period's run.
"""

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from execution.backtest_adapter import SLIPPAGE_PCT
from storage import db

REPORTS_DIR = Path(__file__).parent / "reports"
COMMISSION = 0.0  # Alpaca is commission-free, per PRD 8.3


@dataclass
class CompletedTrade:
    ticker: str
    entry_time: datetime
    entry_price: float
    exit_time: datetime
    exit_price: float
    quantity: float
    pnl: float
    pnl_pct: float


@dataclass
class ReportMetrics:
    starting_capital: float
    ending_capital: float
    net_pnl: float
    return_pct: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    max_drawdown_pct: float
    best_trade: CompletedTrade | None
    worst_trade: CompletedTrade | None
    trades: list


def _parse_ts(value):
    return value if isinstance(value, datetime) else datetime.fromisoformat(value)


def reconstruct_trades(fills: list[dict]) -> list[CompletedTrade]:
    """
    Pairs each BUY with the next SELL for the same ticker into a
    completed round-trip trade. This system never holds more than one
    open position per ticker and never partially fills (PRD 5.2/5.3),
    so simple FIFO pairing per ticker is exact -- no ambiguity about
    which buy a sell closes out.

    A ticker still open (bought but not yet sold) when the fills run
    out is not a completed trade and is excluded, per PRD 8.4's
    "completed round-trips" definition.
    """
    ordered = sorted(fills, key=lambda f: f["timestamp"])
    open_buys: dict[str, dict] = {}
    trades = []

    for f in ordered:
        ticker = f["ticker"]
        if f["action"] == "BUY":
            open_buys[ticker] = f
        elif f["action"] == "SELL" and ticker in open_buys:
            entry = open_buys.pop(ticker)
            entry_price = entry["price"]
            exit_price = f["price"]
            quantity = f["quantity"]
            trades.append(
                CompletedTrade(
                    ticker=ticker,
                    entry_time=_parse_ts(entry["timestamp"]),
                    entry_price=entry_price,
                    exit_time=_parse_ts(f["timestamp"]),
                    exit_price=exit_price,
                    quantity=quantity,
                    pnl=(exit_price - entry_price) * quantity,
                    pnl_pct=(exit_price - entry_price) / entry_price * 100,
                )
            )

    return trades


def compute_max_drawdown(equity_curve: list[float]) -> float:
    """Largest peak-to-trough drop in the equity curve, as a percentage."""
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        if peak > 0:
            max_dd = max(max_dd, (peak - value) / peak * 100)
    return max_dd


def compute_metrics(
    trades: list[CompletedTrade],
    equity_curve: list[float],
    starting_capital: float,
    ending_capital: float,
) -> ReportMetrics:
    net_pnl = ending_capital - starting_capital
    return_pct = (net_pnl / starting_capital * 100) if starting_capital else 0.0

    winning = [t for t in trades if t.pnl > 0]
    losing = [t for t in trades if t.pnl <= 0]
    total = len(trades)
    win_rate = (len(winning) / total * 100) if total else 0.0

    return ReportMetrics(
        starting_capital=starting_capital,
        ending_capital=ending_capital,
        net_pnl=net_pnl,
        return_pct=return_pct,
        total_trades=total,
        winning_trades=len(winning),
        losing_trades=len(losing),
        win_rate=win_rate,
        max_drawdown_pct=compute_max_drawdown(equity_curve),
        best_trade=max(trades, key=lambda t: t.pnl) if trades else None,
        worst_trade=min(trades, key=lambda t: t.pnl) if trades else None,
        trades=trades,
    )


def format_summary(metrics: ReportMetrics, strategy: str, period_name: str) -> str:
    lines = [
        f"Backtest Report: {strategy} -- {period_name}",
        "=" * 50,
        f"Starting capital:   ${metrics.starting_capital:,.2f}",
        f"Ending capital:     ${metrics.ending_capital:,.2f}",
        f"Net P&L:            ${metrics.net_pnl:,.2f}",
        f"Return:             {metrics.return_pct:.2f}%",
        "",
        f"Total trades:       {metrics.total_trades}",
        f"Winning trades:     {metrics.winning_trades}",
        f"Losing trades:      {metrics.losing_trades}",
        f"Win rate:           {metrics.win_rate:.2f}%",
        f"Max drawdown:       {metrics.max_drawdown_pct:.2f}%",
        "",
    ]

    if metrics.best_trade:
        b = metrics.best_trade
        lines.append(f"Best trade:         {b.ticker} entry ${b.entry_price:.2f} -> exit ${b.exit_price:.2f}, P&L ${b.pnl:,.2f}")
    else:
        lines.append("Best trade:         (no completed trades)")

    if metrics.worst_trade:
        w = metrics.worst_trade
        lines.append(f"Worst trade:        {w.ticker} entry ${w.entry_price:.2f} -> exit ${w.exit_price:.2f}, P&L ${w.pnl:,.2f}")
    else:
        lines.append("Worst trade:        (no completed trades)")

    lines += [
        "",
        f"Slippage assumption:   {SLIPPAGE_PCT * 100:.2f}% (applied against the trader on every fill)",
        f"Commission assumption: ${COMMISSION:.2f} (Alpaca is commission-free)",
    ]
    return "\n".join(lines)


def write_trade_log_csv(trades: list[CompletedTrade], path: Path) -> None:
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["ticker", "entry_time", "entry_price", "exit_time", "exit_price", "quantity", "pnl", "pnl_pct"])
        for t in trades:
            writer.writerow(
                [t.ticker, t.entry_time.isoformat(), t.entry_price, t.exit_time.isoformat(), t.exit_price, t.quantity, t.pnl, t.pnl_pct]
            )


def generate_report(
    strategy: str,
    period_name: str,
    starting_capital: float,
    db_path: Path = db.DEFAULT_DB_PATH,
    output_dir: Path = REPORTS_DIR,
) -> ReportMetrics:
    mode = f"backtest_{period_name}"

    fills = db.get_all_fills(strategy=strategy, mode=mode, db_path=db_path)
    snapshots = db.get_all_portfolio_snapshots(strategy=strategy, mode=mode, db_path=db_path)

    trades = reconstruct_trades(fills)
    equity_curve = [s["equity"] for s in snapshots]
    ending_capital = equity_curve[-1] if equity_curve else starting_capital

    metrics = compute_metrics(trades, equity_curve, starting_capital, ending_capital)

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f"report_{period_name}_{strategy}_summary.txt").write_text(
        format_summary(metrics, strategy, period_name)
    )
    write_trade_log_csv(trades, output_dir / f"report_{period_name}_{strategy}_trades.csv")

    return metrics
