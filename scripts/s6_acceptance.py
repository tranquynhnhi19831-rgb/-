from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from backtest.jianghe_runner import (
    ALL_SETUPS,
    SETUP_BREAKOUT,
    SETUP_PULLBACK,
    SETUP_SECOND_PUSH,
)
from services.backtest_service import run_backtest


VARIANTS = {
    "combined": ALL_SETUPS,
    "pullback_only": (SETUP_PULLBACK,),
    "breakout_only": (SETUP_BREAKOUT,),
    "second_push_only": (SETUP_SECOND_PUSH,),
}


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


def _checks(result: dict) -> dict[str, bool]:
    metrics = result["metrics"]
    bars = result["bars"]
    return {
        "context_data_received": int(bars["context"]) > 0,
        "execution_data_received": int(bars["execution"]) > 0,
        "initial_equity_is_100u": abs(float(metrics["initial_equity"]) - 100.0) < 1e-9,
        "final_equity_is_finite": _finite(metrics["final_equity"]),
        "account_not_bankrupt": float(metrics["final_equity"]) > 0.0,
        "drawdown_is_bounded": 0.0 <= float(metrics["max_drawdown"]) <= 1.0,
        "fees_are_nonnegative": float(metrics["fees"]) >= 0.0,
        "funding_is_finite": _finite(metrics["funding"]),
        "signal_count_is_valid": int(result["signals_generated"]) >= 0,
        "trade_count_is_valid": int(metrics["trades"]) >= 0,
    }


def run_acceptance(symbol: str, start: str, end: str) -> dict:
    variants: dict[str, dict] = {}
    passed = True

    for name, setups in VARIANTS.items():
        result = run_backtest(
            symbol,
            start,
            end,
            enabled_setups=tuple(setups),
            initial_equity=100.0,
            risk_per_trade=0.005,
            fee_rate=0.0004,
            slippage_bps=2.0,
            reward_risk=1.5,
            leverage=3.0,
            max_margin_fraction=0.10,
        )
        checks = _checks(result)
        variant_passed = all(checks.values())
        passed = passed and variant_passed
        metrics = result["metrics"]
        variants[name] = {
            "passed": variant_passed,
            "enabled_setups": result["enabled_setups"],
            "bars": result["bars"],
            "signals_generated": result["signals_generated"],
            "skipped_signals": result["skipped_signals"],
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
            "note": (
                "Zero trades does not fail S6.5. This gate validates deterministic data/execution plumbing; "
                "statistical profitability requires longer walk-forward studies."
            ),
        }

    return _sanitize(
        {
            "stage": "S6.5",
            "passed": passed,
            "symbol": symbol,
            "start": start,
            "end": end,
            "market": "BINANCE_USDT_M_PUBLIC_HISTORY",
            "variants": variants,
            "profitability_gate": False,
            "next_stage_if_passed": "S7_BINANCE_USDT_M_TESTNET",
        }
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the S6.5 Binance public-history acceptance gate.")
    parser.add_argument("--symbol", default="BTC/USDT")
    parser.add_argument("--start", default="2026-08-01")
    parser.add_argument("--end", default="2026-08-03")
    parser.add_argument("--output", default="artifacts/s6_acceptance.json")
    args = parser.parse_args()

    report = run_acceptance(args.symbol, args.start, args.end)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
