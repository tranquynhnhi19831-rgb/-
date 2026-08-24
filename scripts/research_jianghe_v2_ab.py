from __future__ import annotations

import argparse
import json
import time

from backtest.binance_vision import fetch_usdm_ohlcv_vision
from backtest.engine import BacktestEngine
from backtest.jianghe_runner import (
    JiangheRunnerConfig,
    generate_jianghe_signals_fast,
    quality_first_v2_config,
)
from backtest.types import BacktestConfig


def _summary(result, signals, elapsed_s: float) -> dict:
    metrics = result.metrics
    return {
        "signals": len(signals),
        "trades": metrics["trades"],
        "wins": metrics["wins"],
        "losses": metrics["losses"],
        "win_rate": metrics["win_rate"],
        "profit_factor": metrics["profit_factor"],
        "expectancy": metrics["expectancy"],
        "net_pnl": metrics["net_pnl"],
        "total_return": metrics["total_return"],
        "final_equity": metrics["final_equity"],
        "max_drawdown": metrics["max_drawdown"],
        "fees": metrics["fees"],
        "max_consecutive_losses": metrics["max_consecutive_losses"],
        "by_setup": metrics["by_setup"],
        "elapsed_s": elapsed_s,
    }


def _run(label, context, execution, runner_cfg):
    started = time.perf_counter()
    signals = generate_jianghe_signals_fast(context, execution, runner_cfg)
    signal_elapsed = time.perf_counter() - started
    engine = BacktestEngine(
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
    result = engine.run(execution, signals)
    elapsed = time.perf_counter() - started
    payload = _summary(result, signals, elapsed)
    payload["signal_generation_s"] = signal_elapsed
    print(f"{label}_RESULT_JSON=" + json.dumps(payload, sort_keys=True), flush=True)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--symbol", default="BTC/USDT")
    args = parser.parse_args()

    print(f"A_B_RANGE symbol={args.symbol} start={args.start} end={args.end}", flush=True)
    context = fetch_usdm_ohlcv_vision(args.symbol, "15m", args.start, args.end, timeout_seconds=60)
    execution = fetch_usdm_ohlcv_vision(args.symbol, "1m", args.start, args.end, timeout_seconds=60)
    print(
        f"DATA_READY context={len(context)} execution={len(execution)}",
        flush=True,
    )

    baseline = _run("BASELINE", context, execution, JiangheRunnerConfig())
    v2 = _run("V2", context, execution, quality_first_v2_config())

    comparison = {
        "symbol": args.symbol,
        "start": args.start,
        "end": args.end,
        "context_timeframe": "15m",
        "execution_timeframe": "1m",
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
            "daily_risk_limits": "OMITTED_IN_THIS_SIGNAL_QUALITY_AB_TEST",
            "funding": "OMITTED",
        },
        "baseline": baseline,
        "v2": v2,
        "delta": {
            "signals": v2["signals"] - baseline["signals"],
            "trades": v2["trades"] - baseline["trades"],
            "win_rate": v2["win_rate"] - baseline["win_rate"],
            "profit_factor": (
                None
                if v2["profit_factor"] is None or baseline["profit_factor"] is None
                else v2["profit_factor"] - baseline["profit_factor"]
            ),
            "expectancy": v2["expectancy"] - baseline["expectancy"],
            "net_pnl": v2["net_pnl"] - baseline["net_pnl"],
            "max_drawdown": v2["max_drawdown"] - baseline["max_drawdown"],
        },
    }
    print("COMPARISON_JSON=" + json.dumps(comparison, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
