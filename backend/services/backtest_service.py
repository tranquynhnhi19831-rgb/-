from __future__ import annotations

from datetime import datetime, timezone
from exchange.binance_client import BinanceClient
from services.market_data_service import fetch_historical_range
from strategy.n_pattern_strategy import generate_signal


def _to_ms(v: str) -> int:
    return int(datetime.fromisoformat(v).replace(tzinfo=timezone.utc).timestamp() * 1000)


def run_backtest(symbol: str, start: str, end: str, testnet: bool, api_key: str, secret: str) -> dict:
    client = BinanceClient(api_key, secret, testnet)
    since_ms, until_ms = _to_ms(start), _to_ms(end)

    h1 = fetch_historical_range(client, symbol, "1h", since_ms, until_ms)
    m15 = fetch_historical_range(client, symbol, "15m", since_ms, until_ms)
    if h1.empty or m15.empty:
        return {"ok": False, "error": "历史K线为空"}

    equity = 20.0
    peak = equity
    max_dd = 0.0
    wins = losses = 0
    pnl_sum = 0.0
    fee_rate = 0.0004
    trades = []

    for i in range(120, len(m15), 4):
        ts = m15.iloc[i]["ts"]
        h1_slice = h1[h1["ts"] <= ts].tail(300)
        m15_slice = m15.iloc[: i + 1].tail(300)
        signal = generate_signal(symbol, h1_slice, m15_slice)
        if not signal:
            continue

        entry, stop, take = signal["entry"], signal["stop_loss"], signal["take_profit"]
        qty = max((equity * 0.01) / max(abs(entry - stop), 1e-9), 0.001)

        future = m15.iloc[i + 1 : i + 25]
        exit_price = float(future.iloc[-1]["close"]) if not future.empty else entry
        outcome = "timeout"
        for _, row in future.iterrows():
            h, l = float(row["high"]), float(row["low"])
            if signal["side"] == "long":
                if l <= stop:
                    exit_price = stop
                    outcome = "sl"
                    break
                if h >= take:
                    exit_price = take
                    outcome = "tp"
                    break
            else:
                if h >= stop:
                    exit_price = stop
                    outcome = "sl"
                    break
                if l <= take:
                    exit_price = take
                    outcome = "tp"
                    break

        pnl = (exit_price - entry) * qty if signal["side"] == "long" else (entry - exit_price) * qty
        fee = (entry * qty + exit_price * qty) * fee_rate
        pnl_after_fee = pnl - fee
        pnl_sum += pnl_after_fee
        equity += pnl_after_fee
        peak = max(peak, equity)
        dd = (peak - equity) / peak if peak > 0 else 0
        max_dd = max(max_dd, dd)

        if pnl_after_fee > 0:
            wins += 1
        else:
            losses += 1

        trades.append({"time": str(ts), "side": signal["side"], "entry": entry, "exit": exit_price, "pnl": pnl_after_fee, "outcome": outcome})

    total = wins + losses
    avg_win = sum(t["pnl"] for t in trades if t["pnl"] > 0) / max(wins, 1)
    avg_loss = abs(sum(t["pnl"] for t in trades if t["pnl"] <= 0) / max(losses, 1))
    return {
        "ok": True,
        "symbol": symbol,
        "start": start,
        "end": end,
        "trades": total,
        "win_rate": round(wins / total, 4) if total else 0,
        "total_return": round((equity - 20.0) / 20.0, 4),
        "max_drawdown": round(max_dd, 4),
        "profit_factor": round((avg_win / avg_loss), 4) if avg_loss > 0 else 0,
        "return_after_fees": round(pnl_sum / 20.0, 4),
        "samples": trades[-20:],
    }
