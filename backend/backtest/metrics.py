from __future__ import annotations

from collections.abc import Sequence

from backtest.types import BacktestTrade


def max_drawdown(equity_curve: Sequence[float]) -> float:
    if not equity_curve:
        return 0.0
    peak = float(equity_curve[0])
    worst = 0.0
    for value in equity_curve:
        value = float(value)
        peak = max(peak, value)
        if peak > 0:
            worst = max(worst, (peak - value) / peak)
    return float(worst)


def max_consecutive_losses(trades: Sequence[BacktestTrade]) -> int:
    current = 0
    worst = 0
    for trade in trades:
        if trade.net_pnl < 0:
            current += 1
            worst = max(worst, current)
        else:
            current = 0
    return worst


def summarize(
    trades: Sequence[BacktestTrade],
    equity_curve: Sequence[float],
    initial_equity: float,
) -> dict[str, float | int]:
    final_equity = float(equity_curve[-1]) if equity_curve else float(initial_equity)
    wins = [t for t in trades if t.net_pnl > 0]
    losses = [t for t in trades if t.net_pnl < 0]
    gross_profit = sum(t.net_pnl for t in wins)
    gross_loss = -sum(t.net_pnl for t in losses)
    total_fees = sum(t.fees for t in trades)
    total_funding = sum(t.funding for t in trades)
    total_net_pnl = sum(t.net_pnl for t in trades)
    count = len(trades)

    return {
        "initial_equity": float(initial_equity),
        "final_equity": final_equity,
        "net_pnl": float(total_net_pnl),
        "total_return": float(final_equity / initial_equity - 1.0) if initial_equity else 0.0,
        "trades": count,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": float(len(wins) / count) if count else 0.0,
        "avg_win": float(gross_profit / len(wins)) if wins else 0.0,
        "avg_loss": float(gross_loss / len(losses)) if losses else 0.0,
        "expectancy": float(total_net_pnl / count) if count else 0.0,
        "profit_factor": float(gross_profit / gross_loss) if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0),
        "max_drawdown": max_drawdown(equity_curve),
        "max_consecutive_losses": max_consecutive_losses(trades),
        "fees": float(total_fees),
        "funding": float(total_funding),
    }


def summarize_by_setup(trades: Sequence[BacktestTrade]) -> dict[str, dict[str, float | int]]:
    grouped: dict[str, list[BacktestTrade]] = {}
    for trade in trades:
        grouped.setdefault(trade.setup, []).append(trade)

    result: dict[str, dict[str, float | int]] = {}
    for setup, rows in grouped.items():
        wins = [t for t in rows if t.net_pnl > 0]
        losses = [t for t in rows if t.net_pnl < 0]
        gross_profit = sum(t.net_pnl for t in wins)
        gross_loss = -sum(t.net_pnl for t in losses)
        result[setup] = {
            "trades": len(rows),
            "win_rate": len(wins) / len(rows) if rows else 0.0,
            "net_pnl": sum(t.net_pnl for t in rows),
            "expectancy": sum(t.net_pnl for t in rows) / len(rows) if rows else 0.0,
            "profit_factor": gross_profit / gross_loss if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0),
            "fees": sum(t.fees for t in rows),
            "funding": sum(t.funding for t in rows),
        }
    return result
