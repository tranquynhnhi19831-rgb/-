from __future__ import annotations

import argparse
import json
import time
from dataclasses import replace

from backtest.binance_vision import fetch_usdm_ohlcv_vision
from backtest.engine import BacktestEngine
from backtest.jianghe_event_runner import generate_event_pullback_signals_fast
from backtest.jianghe_research_fast import generate_jianghe_signals_research_fast
from backtest.jianghe_runner import SETUP_PULLBACK, quality_first_v2_config
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

    context = fetch_usdm_ohlcv_vision(args.symbol, "15m", args.start, args.end, timeout_seconds=60)
    execution = fetch_usdm_ohlcv_vision(args.symbol, "1m", args.start, args.end, timeout_seconds=60)
    print(f"DATA_READY context={len(context)} execution={len(execution)}", flush=True)

    fixed_cfg = replace(quality_first_v2_config(), enabled_setups=(SETUP_PULLBACK,))

    started = time.perf_counter()
    fixed_signals = generate_jianghe_signals_research_fast(context, execution, fixed_cfg)
    fixed_result = _engine().run(execution, fixed_signals)
    fixed = _summary("V2_FIXED_PULLBACK", fixed_signals, fixed_result, time.perf_counter() - started)

    started = time.perf_counter()
    event_signals = generate_event_pullback_signals_fast(context, execution)
    event_result = _engine().run(execution, event_signals)
    event = _summary("V3_EVENT_PULLBACK", event_signals, event_result, time.perf_counter() - started)

    comparison = {
        "symbol": args.symbol,
        "start": args.start,
        "end": args.end,
        "context_timeframe": "15m",
        "execution_timeframe": "1m",
        "change_under_test": "FIXED_PHASE_LENGTHS_VS_CONFIRMED_SWING_EVENT_PHASES",
        "fixed_runner": "SEMANTICS_PRESERVING_REGIME_SHORT_CIRCUIT",
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
        },
        "fixed_v2": fixed,
        "event_v3": event,
        "delta": {
            "trades": event["trades"] - fixed["trades"],
            "win_rate": event["win_rate"] - fixed["win_rate"],
            "profit_factor": (
                None
                if event["profit_factor"] is None or fixed["profit_factor"] is None
                else event["profit_factor"] - fixed["profit_factor"]
            ),
            "expectancy": event["expectancy"] - fixed["expectancy"],
            "net_pnl": event["net_pnl"] - fixed["net_pnl"],
            "max_drawdown": event["max_drawdown"] - fixed["max_drawdown"],
        },
    }
    print("COMPARISON_JSON=" + json.dumps(comparison, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
