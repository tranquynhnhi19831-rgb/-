from __future__ import annotations

import argparse
import json
import time

from backtest.binance_vision import fetch_usdm_ohlcv_vision
from backtest.engine import BacktestEngine
from backtest.jianghe_multitimeframe_runner import generate_multitimeframe_event_pullback_signals_fast
from backtest.jianghe_scored_runner import generate_scored_multitimeframe_pullback_signals_fast
from backtest.types import BacktestConfig


def _config(*, economic_gate: bool) -> BacktestConfig:
    return BacktestConfig(
        initial_equity=100.0,
        risk_per_trade=0.005,
        fee_rate=0.0004,
        slippage_bps=2.0,
        reward_risk=1.8,
        max_hold_bars=64,
        leverage=3.0,
        max_margin_fraction=0.10,
        same_bar_policy="STOP_FIRST",
        max_friction_to_planned_risk=0.25 if economic_gate else None,
    )


def _summary(label: str, signals, result, elapsed_s: float) -> dict:
    metrics = result.metrics
    payload = {
        "label": label,
        "signals": len(signals),
        "trades": metrics["trades"],
        "wins": metrics["wins"],
        "losses": metrics["losses"],
        "win_rate": metrics["win_rate"],
        "profit_factor": metrics["profit_factor"],
        "expectancy": metrics["expectancy"],
        "net_pnl": metrics["net_pnl"],
        "final_equity": metrics["final_equity"],
        "max_drawdown": metrics["max_drawdown"],
        "fees": metrics["fees"],
        "skipped_signals": metrics["skipped_signals"],
        "economic_skips": metrics.get("economic_skips", 0),
        "max_consecutive_losses": metrics["max_consecutive_losses"],
        "elapsed_s": elapsed_s,
    }
    print(f"{label}_RESULT_JSON=" + json.dumps(payload, sort_keys=True), flush=True)
    return payload


def _run(label, execution, signals, *, economic_gate: bool):
    started = time.perf_counter()
    result = BacktestEngine(_config(economic_gate=economic_gate)).run(execution, signals)
    return _summary(label, signals, result, time.perf_counter() - started)


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
        f"DATA_READY macro={len(macro)} context={len(context)} execution={len(execution)}",
        flush=True,
    )

    started = time.perf_counter()
    v4_signals = generate_multitimeframe_event_pullback_signals_fast(macro, context, execution)
    v4_signal_s = time.perf_counter() - started
    v4 = _run("V4_HARD_GATES", execution, v4_signals, economic_gate=False)
    v4["signal_generation_s"] = v4_signal_s

    started = time.perf_counter()
    v5_signals = generate_scored_multitimeframe_pullback_signals_fast(macro, context, execution)
    v5_signal_s = time.perf_counter() - started
    scored = _run("V5_SCORE_ONLY", execution, v5_signals, economic_gate=False)
    scored["signal_generation_s"] = v5_signal_s
    economics = _run("V5_SCORE_ECON", execution, v5_signals, economic_gate=True)
    economics["signal_generation_s"] = v5_signal_s

    payload = {
        "symbol": args.symbol,
        "start": args.start,
        "end": args.end,
        "timeframes": {"macro": "1h", "context": "15m", "execution": "1m"},
        "assumptions": {
            "initial_equity": 100.0,
            "risk_per_trade": 0.005,
            "reward_risk": 1.8,
            "fee_rate_each_side": 0.0004,
            "slippage_bps_each_fill": 2.0,
            "leverage": 3.0,
            "max_margin_fraction": 0.10,
            "max_hold_bars": 64,
            "same_bar_policy": "STOP_FIRST",
            "economic_max_friction_to_planned_risk": 0.25,
        },
        "experiments": {
            "v4_hard_gates": v4,
            "v5_score_only": scored,
            "v5_score_economics": economics,
        },
        "interpretation": {
            "v4_to_score": "isolates replacing multiple momentum hard gates with a coarse quality score",
            "score_to_economics": "isolates the small-account friction-to-planned-risk gate",
            "promotion_rule": "no promotion from a single window; require multi-window and untouched-year validation",
        },
    }
    print("COMPARISON_JSON=" + json.dumps(payload, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
