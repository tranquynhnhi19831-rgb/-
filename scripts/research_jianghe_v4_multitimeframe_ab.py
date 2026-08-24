from __future__ import annotations

import argparse
import json
import time

from backtest.binance_vision import fetch_usdm_ohlcv_vision
from backtest.engine import BacktestEngine
from backtest.jianghe_event_runner import generate_event_pullback_signals_fast
from backtest.jianghe_multitimeframe_runner import generate_multitimeframe_event_pullback_signals_fast
from backtest.types import BacktestConfig


def _engine() -> BacktestEngine:
    return BacktestEngine(
        BacktestConfig(
            initial_equity=100.0,
            risk_per_trade=0.005,
            fee_rate=0.0004,
            slippage_bps=2.0,
            reward_risk=1.8,
            max_hold_bars=64,
            leverage=3.0,
            max_margin_fraction=0.10,
            same_bar_policy="STOP_FIRST",
        )
    )


def _summary(label: str, signals, result, elapsed_s: float) -> dict:
    m = result.metrics
    payload = {
        "label": label,
        "signals": len(signals),
        "trades": m["trades"],
        "wins": m["wins"],
        "losses": m["losses"],
        "win_rate": m["win_rate"],
        "profit_factor": m["profit_factor"],
        "expectancy": m["expectancy"],
        "net_pnl": m["net_pnl"],
        "final_equity": m["final_equity"],
        "max_drawdown": m["max_drawdown"],
        "fees": m["fees"],
        "max_consecutive_losses": m["max_consecutive_losses"],
        "elapsed_s": elapsed_s,
    }
    print(f"{label}_RESULT_JSON=" + json.dumps(payload, sort_keys=True), flush=True)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--symbol", default="BTC/USDT")
    args = parser.parse_args()

    macro = fetch_usdm_ohlcv_vision(args.symbol, "1h", args.start, args.end, timeout_seconds=60)
    context = fetch_usdm_ohlcv_vision(args.symbol, "15m", args.start, args.end, timeout_seconds=60)
    execution = fetch_usdm_ohlcv_vision(args.symbol, "1m", args.start, args.end, timeout_seconds=60)
    print(
        f"DATA_READY macro_1h={len(macro)} context_15m={len(context)} execution_1m={len(execution)}",
        flush=True,
    )

    started = time.perf_counter()
    v3_signals = generate_event_pullback_signals_fast(context, execution)
    v3_result = _engine().run(execution, v3_signals)
    v3 = _summary("V3_EVENT_PULLBACK", v3_signals, v3_result, time.perf_counter() - started)

    started = time.perf_counter()
    v4_signals = generate_multitimeframe_event_pullback_signals_fast(macro, context, execution)
    v4_result = _engine().run(execution, v4_signals)
    v4 = _summary("V4_MTF_EVENT_PULLBACK", v4_signals, v4_result, time.perf_counter() - started)

    comparison = {
        "symbol": args.symbol,
        "start": args.start,
        "end": args.end,
        "v3_timeframes": {"context": "15m", "execution": "1m"},
        "v4_timeframes": {"macro": "1h", "context": "15m", "execution": "1m"},
        "change_under_test": "ADD_CONFIRMED_1H_DIRECTIONAL_BIAS_TO_15M_EVENT_PULLBACK",
        "assumptions": {
            "initial_equity": 100.0,
            "risk_per_trade": 0.005,
            "reward_risk": 1.8,
            "fee_rate_each_side": 0.0004,
            "slippage_bps_each_fill": 2.0,
            "max_hold_bars": 64,
            "leverage": 3.0,
            "max_margin_fraction": 0.10,
            "same_bar_policy": "STOP_FIRST",
            "funding": "OMITTED",
            "daily_risk_limits": "OMITTED_IN_SIGNAL_QUALITY_AB_TEST",
        },
        "v3": v3,
        "v4": v4,
        "delta": {
            "signals": v4["signals"] - v3["signals"],
            "trades": v4["trades"] - v3["trades"],
            "win_rate": v4["win_rate"] - v3["win_rate"],
            "profit_factor": (
                None
                if v4["profit_factor"] is None or v3["profit_factor"] is None
                else v4["profit_factor"] - v3["profit_factor"]
            ),
            "expectancy": v4["expectancy"] - v3["expectancy"],
            "net_pnl": v4["net_pnl"] - v3["net_pnl"],
            "max_drawdown": v4["max_drawdown"] - v3["max_drawdown"],
        },
    }
    print("COMPARISON_JSON=" + json.dumps(comparison, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
