from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import pandas as pd

from backtest.binance_data import attach_funding_rates
from backtest.binance_vision import fetch_usdm_ohlcv_vision
from backtest.engine import BacktestEngine
from backtest.jianghe_runner import (
    ALL_SETUPS,
    JiangheRunnerConfig,
    SETUP_BREAKOUT,
    SETUP_PULLBACK,
    SETUP_SECOND_PUSH,
    generate_jianghe_signals,
)
from backtest.types import BacktestConfig


VARIANTS = {
    "combined": ALL_SETUPS,
    "pullback_only": (SETUP_PULLBACK,),
    "breakout_only": (SETUP_BREAKOUT,),
    "second_push_only": (SETUP_SECOND_PUSH,),
}


def _utc(value: str) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _finite(value) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _sanitize(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _sanitize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    return value


def _checks(metrics: dict, context_count: int, execution_count: int, signal_count: int) -> dict[str, bool]:
    return {
        "official_data_vision_source": True,
        "context_data_received": context_count > 0,
        "execution_data_received": execution_count > 0,
        "initial_equity_is_100u": abs(float(metrics["initial_equity"]) - 100.0) < 1e-9,
        "final_equity_is_finite": _finite(metrics["final_equity"]),
        "account_not_bankrupt": float(metrics["final_equity"]) > 0.0,
        "drawdown_is_bounded": 0.0 <= float(metrics["max_drawdown"]) <= 1.0,
        "fees_are_nonnegative": float(metrics["fees"]) >= 0.0,
        "funding_is_finite": _finite(metrics["funding"]),
        "signal_count_is_valid": signal_count >= 0,
        "trade_count_is_valid": int(metrics["trades"]) >= 0,
    }


def run_acceptance(symbol: str, start: str, end: str) -> dict:
    start_ts = _utc(start)
    end_ts = _utc(end)
    if end_ts <= start_ts:
        raise ValueError("end must be after start")

    runner_cfg = JiangheRunnerConfig()
    # Default 15m context lookback is the larger warm-up requirement.
    warmup = max(
        runner_cfg.context_lookback * pd.Timedelta(minutes=15),
        runner_cfg.execution_lookback * pd.Timedelta(minutes=1),
    )
    warmup_start = start_ts - warmup

    context = fetch_usdm_ohlcv_vision(symbol, "15m", warmup_start, end_ts)
    execution = fetch_usdm_ohlcv_vision(symbol, "1m", warmup_start, end_ts)
    funding = pd.DataFrame(columns=["timestamp", "funding_rate"])
    execution = attach_funding_rates(execution, funding)
    if context.empty or execution.empty:
        raise ValueError("Binance Data Vision returned no historical candles")

    all_signals = generate_jianghe_signals(context, execution, runner_cfg)
    all_signals = [
        signal
        for signal in all_signals
        if signal.timestamp is not None and start_ts <= pd.Timestamp(signal.timestamp) < end_ts
    ]

    bt_cfg = BacktestConfig(
        initial_equity=100.0,
        risk_per_trade=0.005,
        fee_rate=0.0004,
        slippage_bps=2.0,
        reward_risk=1.5,
        leverage=3.0,
        max_margin_fraction=0.10,
    )

    variants: dict[str, dict] = {}
    passed = True
    for name, setups in VARIANTS.items():
        selected = [signal for signal in all_signals if signal.setup in setups]
        result = BacktestEngine(bt_cfg).run(execution, selected)
        metrics = result.metrics
        checks = _checks(metrics, len(context), len(execution), len(selected))
        variant_passed = all(checks.values())
        passed = passed and variant_passed
        variants[name] = {
            "passed": variant_passed,
            "enabled_setups": list(setups),
            "signals_generated": len(selected),
            "skipped_signals": result.skipped_signals,
            "checks": checks,
            "metrics": {
                "initial_equity": metrics["initial_equity"],
                "final_equity": metrics["final_equity"],
                "net_pnl": metrics["net_pnl"],
                "total_return": metrics["total_return"],
                "trades": metrics["trades"],
                "wins": metrics["wins"],
                "losses": metrics["losses"],
                "win_rate": metrics["win_rate"],
                "expectancy": metrics["expectancy"],
                "profit_factor": metrics["profit_factor"],
                "max_drawdown": metrics["max_drawdown"],
                "max_consecutive_losses": metrics["max_consecutive_losses"],
                "fees": metrics["fees"],
                "funding": metrics["funding"],
                "by_setup": metrics.get("by_setup", {}),
            },
        }

    return _sanitize(
        {
            "stage": "S6.5",
            "passed": passed,
            "symbol": symbol,
            "start": start_ts.isoformat(),
            "end": end_ts.isoformat(),
            "market": "BINANCE_USDT_M",
            "ci_history_source": "BINANCE_DATA_VISION_OFFICIAL_ARCHIVE",
            "funding_source": "NOT_EXERCISED_IN_CI_VISION_MODE",
            "bars": {"context": len(context), "execution": len(execution)},
            "all_signals_generated": len(all_signals),
            "variants": variants,
            "profitability_gate": False,
            "note": (
                "S6.5 validates historical data/time/execution plumbing, not strategy profitability. "
                "Funding arithmetic is unit-tested and live network funding is rechecked in the allowed-region Testnet runtime."
            ),
            "next_stage_if_passed": "S7_BINANCE_USDT_M_TESTNET",
        }
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the S6.5 Binance public-history acceptance gate.")
    parser.add_argument("--symbol", default="BTC/USDT")
    parser.add_argument("--start", default="2026-08-01T00:00:00Z")
    parser.add_argument("--end", default="2026-08-01T06:00:00Z")
    parser.add_argument("--output", default="artifacts/s6_acceptance.json")
    args = parser.parse_args()

    try:
        report = run_acceptance(args.symbol, args.start, args.end)
    except Exception as exc:
        report = {
            "stage": "S6.5",
            "passed": False,
            "symbol": args.symbol,
            "start": args.start,
            "end": args.end,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(_sanitize(report), ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(_sanitize(report), ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())