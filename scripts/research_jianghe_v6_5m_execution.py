from __future__ import annotations

import argparse
import json
import time

from backtest.binance_vision import fetch_usdm_ohlcv_vision
from backtest.engine import BacktestEngine
from backtest.jianghe_scored_runner import (
    ScoredMultiTimeframeRunnerConfig,
    generate_scored_multitimeframe_pullback_signals_fast,
)
from backtest.types import BacktestConfig


def _engine_config(*, max_hold_bars: int, economic_gate: bool) -> BacktestConfig:
    return BacktestConfig(
        initial_equity=100.0,
        risk_per_trade=0.005,
        fee_rate=0.0004,
        slippage_bps=2.0,
        reward_risk=1.8,
        max_hold_bars=max_hold_bars,
        leverage=3.0,
        max_margin_fraction=0.10,
        same_bar_policy="STOP_FIRST",
        max_friction_to_planned_risk=0.25 if economic_gate else None,
    )


def _summary(label: str, signals, result, signal_generation_s: float, execution_timeframe: str) -> dict:
    metrics = result.metrics
    payload = {
        "label": label,
        "execution_timeframe": execution_timeframe,
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
        "signal_generation_s": signal_generation_s,
    }
    print(f"{label}_RESULT_JSON=" + json.dumps(payload, sort_keys=True), flush=True)
    return payload


def _run(label, execution, signals, *, max_hold_bars: int, economic_gate: bool, signal_generation_s: float, execution_timeframe: str):
    result = BacktestEngine(
        _engine_config(max_hold_bars=max_hold_bars, economic_gate=economic_gate)
    ).run(execution, signals)
    return _summary(label, signals, result, signal_generation_s, execution_timeframe)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--symbol", default="BTC/USDT")
    args = parser.parse_args()

    macro = fetch_usdm_ohlcv_vision(args.symbol, "1h", args.start, args.end, timeout_seconds=60)
    context = fetch_usdm_ohlcv_vision(args.symbol, "15m", args.start, args.end, timeout_seconds=60)
    execution_1m = fetch_usdm_ohlcv_vision(args.symbol, "1m", args.start, args.end, timeout_seconds=60)
    execution_5m = fetch_usdm_ohlcv_vision(args.symbol, "5m", args.start, args.end, timeout_seconds=60)
    print(
        "DATA_READY "
        f"macro={len(macro)} context={len(context)} execution_1m={len(execution_1m)} execution_5m={len(execution_5m)}",
        flush=True,
    )

    v5_cfg = ScoredMultiTimeframeRunnerConfig()
    started = time.perf_counter()
    v5_signals = generate_scored_multitimeframe_pullback_signals_fast(
        macro, context, execution_1m, v5_cfg
    )
    v5_signal_s = time.perf_counter() - started

    # Six 1m cooldown bars ~= one 5m bar. Keep the cooldown in roughly the same
    # wall-clock range while allowing the 5m candle itself to define the coarser
    # impulse/pullback/trigger events.
    v6_cfg = ScoredMultiTimeframeRunnerConfig(
        signal_cooldown_bars=1,
        execution_timeframe_label="5m",
        setup_version="V6_5M_SCORED_MTF_PULLBACK",
        setup_name="TREND_PULLBACK_EVENT_V6_5M_SCORED_MTF",
    )
    started = time.perf_counter()
    v6_signals = generate_scored_multitimeframe_pullback_signals_fast(
        macro, context, execution_5m, v6_cfg
    )
    v6_signal_s = time.perf_counter() - started

    experiments = {
        "v5_1m_score_only": _run(
            "V5_1M_SCORE_ONLY",
            execution_1m,
            v5_signals,
            max_hold_bars=64,
            economic_gate=False,
            signal_generation_s=v5_signal_s,
            execution_timeframe="1m",
        ),
        "v5_1m_score_econ": _run(
            "V5_1M_SCORE_ECON",
            execution_1m,
            v5_signals,
            max_hold_bars=64,
            economic_gate=True,
            signal_generation_s=v5_signal_s,
            execution_timeframe="1m",
        ),
        "v6_5m_score_only": _run(
            "V6_5M_SCORE_ONLY",
            execution_5m,
            v6_signals,
            max_hold_bars=13,
            economic_gate=False,
            signal_generation_s=v6_signal_s,
            execution_timeframe="5m",
        ),
        "v6_5m_score_econ": _run(
            "V6_5M_SCORE_ECON",
            execution_5m,
            v6_signals,
            max_hold_bars=13,
            economic_gate=True,
            signal_generation_s=v6_signal_s,
            execution_timeframe="5m",
        ),
    }

    payload = {
        "symbol": args.symbol,
        "start": args.start,
        "end": args.end,
        "fixed_timeframes": {"macro": "1h", "context": "15m"},
        "comparison": {"v5_execution": "1m", "v6_execution": "5m"},
        "assumptions": {
            "initial_equity": 100.0,
            "risk_per_trade": 0.005,
            "reward_risk": 1.8,
            "fee_rate_each_side": 0.0004,
            "slippage_bps_each_fill": 2.0,
            "leverage": 3.0,
            "max_margin_fraction": 0.10,
            "same_bar_policy": "STOP_FIRST",
            "v5_max_hold": "64 x 1m = 64 minutes",
            "v6_max_hold": "13 x 5m = 65 minutes",
            "economic_max_friction_to_planned_risk": 0.25,
        },
        "experiments": experiments,
        "interpretation": {
            "primary_question": "does coarser 5m execution improve signal economics/expectancy without changing 1h/15m structure?",
            "not_parameter_optimization": True,
            "promotion_rule": "no promotion from Q1 windows; require untouched full-year/walk-forward and later seven-symbol shared-equity validation",
        },
    }
    print("COMPARISON_JSON=" + json.dumps(payload, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
