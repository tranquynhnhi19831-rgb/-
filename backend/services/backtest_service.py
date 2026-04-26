import random


def run_backtest(symbol: str, start: str, end: str) -> dict:
    trades = random.randint(8, 20)
    win_rate = round(random.uniform(0.35, 0.62), 2)
    total_return = round(random.uniform(-0.08, 0.18), 4)
    drawdown = round(random.uniform(0.02, 0.12), 4)
    fees = round(trades * 0.0008, 4)
    return {
        "symbol": symbol,
        "start": start,
        "end": end,
        "trades": trades,
        "win_rate": win_rate,
        "total_return": total_return,
        "max_drawdown": drawdown,
        "return_after_fees": round(total_return - fees, 4),
    }
