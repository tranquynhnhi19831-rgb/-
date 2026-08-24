from __future__ import annotations

import argparse
import json
from collections import defaultdict

from backtest.binance_vision import fetch_usdm_ohlcv_vision
from backtest.engine import BacktestEngine
from backtest.jianghe_runner import generate_jianghe_signals_fast, quality_first_v2_config
from backtest.types import BacktestConfig


def _bucket(value: float, cuts: tuple[float, ...]) -> str:
    low = 0.0
    for high in cuts:
        if value < high:
            return f"[{low:.2f},{high:.2f})"
        low = high
    return f"[{low:.2f},inf)"


def _new_group() -> dict:
    return {
        "trades": 0,
        "wins": 0,
        "net_pnl": 0.0,
        "fees": 0.0,
        "planned_risk": 0.0,
        "hold_bars": 0,
        "targets": 0,
        "stops": 0,
        "times": 0,
    }


def _finalize(groups: dict[str, dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for key, row in sorted(groups.items()):
        trades = int(row["trades"])
        planned_risk = float(row["planned_risk"])
        out[key] = {
            "trades": trades,
            "wins": int(row["wins"]),
            "win_rate": float(row["wins"] / trades) if trades else 0.0,
            "net_pnl": float(row["net_pnl"]),
            "expectancy": float(row["net_pnl"] / trades) if trades else 0.0,
            "fees": float(row["fees"]),
            "fee_to_planned_risk": float(row["fees"] / planned_risk) if planned_risk > 0 else None,
            "avg_hold_bars": float(row["hold_bars"] / trades) if trades else 0.0,
            "target_rate": float(row["targets"] / trades) if trades else 0.0,
            "stop_rate": float(row["stops"] / trades) if trades else 0.0,
            "time_rate": float(row["times"] / trades) if trades else 0.0,
        }
    return out


def _add(groups: dict[str, dict], key: str, *, trade, planned_risk: float) -> None:
    row = groups.setdefault(key, _new_group())
    row["trades"] += 1
    row["wins"] += int(trade.net_pnl > 0)
    row["net_pnl"] += float(trade.net_pnl)
    row["fees"] += float(trade.fees)
    row["planned_risk"] += float(planned_risk)
    row["hold_bars"] += int(trade.exit_index - trade.entry_index + 1)
    if trade.exit_reason == "TARGET":
        row["targets"] += 1
    elif trade.exit_reason in {"STOP", "STOP_GAP"}:
        row["stops"] += 1
    elif trade.exit_reason == "TIME":
        row["times"] += 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--symbol", default="BTC/USDT")
    args = parser.parse_args()

    context = fetch_usdm_ohlcv_vision(args.symbol, "15m", args.start, args.end, timeout_seconds=60)
    execution = fetch_usdm_ohlcv_vision(args.symbol, "1m", args.start, args.end, timeout_seconds=60)
    cfg = quality_first_v2_config()
    signals = generate_jianghe_signals_fast(context, execution, cfg)

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

    signal_map = {(s.index, s.setup, s.side): s for s in signals}
    by_setup: dict[str, dict] = {}
    by_side: dict[str, dict] = {}
    by_exit: dict[str, dict] = {}
    by_context_efficiency: dict[str, dict] = {}
    by_utc_hour: dict[str, dict] = {}
    by_stop_pct: dict[str, dict] = {}

    fee_to_risk_values: list[float] = []
    hold_values: list[int] = []
    missing_metadata = 0

    for trade in result.trades:
        signal = signal_map.get((trade.signal_index, trade.setup, trade.side))
        if signal is None:
            missing_metadata += 1
            continue

        planned_risk = abs(float(trade.entry_price) - float(trade.stop_price)) * float(trade.quantity)
        if planned_risk > 0:
            fee_to_risk_values.append(float(trade.fees) / planned_risk)
        hold_values.append(int(trade.exit_index - trade.entry_index + 1))

        context_eff = float(
            signal.metadata.get(
                "runner_context_efficiency",
                signal.metadata.get("context_efficiency", 0.0),
            )
        )
        stop_pct = abs(float(trade.entry_price) - float(trade.stop_price)) / float(trade.entry_price)
        hour = int(signal.timestamp.hour) if signal.timestamp is not None else -1

        _add(by_setup, trade.setup, trade=trade, planned_risk=planned_risk)
        _add(by_side, trade.side, trade=trade, planned_risk=planned_risk)
        _add(by_exit, trade.exit_reason, trade=trade, planned_risk=planned_risk)
        _add(
            by_context_efficiency,
            _bucket(context_eff, (0.25, 0.35, 0.45, 0.60)),
            trade=trade,
            planned_risk=planned_risk,
        )
        _add(by_utc_hour, f"{hour:02d}", trade=trade, planned_risk=planned_risk)
        _add(
            by_stop_pct,
            _bucket(stop_pct, (0.0015, 0.0025, 0.0040, 0.0060, 0.0100)),
            trade=trade,
            planned_risk=planned_risk,
        )

    fee_to_risk_values.sort()
    hold_values.sort()

    def percentile(values, p: float):
        if not values:
            return None
        index = min(len(values) - 1, max(0, round((len(values) - 1) * p)))
        return float(values[index])

    payload = {
        "symbol": args.symbol,
        "start": args.start,
        "end": args.end,
        "profile": "QUALITY_FIRST_V2",
        "signals": len(signals),
        "trades": len(result.trades),
        "metrics": result.metrics,
        "diagnostics": {
            "missing_signal_metadata": missing_metadata,
            "fee_to_planned_risk": {
                "p25": percentile(fee_to_risk_values, 0.25),
                "p50": percentile(fee_to_risk_values, 0.50),
                "p75": percentile(fee_to_risk_values, 0.75),
            },
            "hold_bars": {
                "p25": percentile(hold_values, 0.25),
                "p50": percentile(hold_values, 0.50),
                "p75": percentile(hold_values, 0.75),
            },
            "by_setup": _finalize(by_setup),
            "by_side": _finalize(by_side),
            "by_exit_reason": _finalize(by_exit),
            "by_context_efficiency": _finalize(by_context_efficiency),
            "by_utc_hour": _finalize(by_utc_hour),
            "by_stop_distance_pct": _finalize(by_stop_pct),
        },
        "interpretation_guardrails": [
            "Use diagnostics to identify broad failure modes, not to cherry-pick one winning hour or bucket.",
            "Any new filter must be validated on untouched years / walk-forward windows before promotion.",
            "This diagnostic run omits daily S7 risk limits and funding, matching the V2 signal-quality A/B.",
        ],
    }
    print("DIAGNOSTICS_JSON=" + json.dumps(payload, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
