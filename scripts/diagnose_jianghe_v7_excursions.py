from __future__ import annotations

import argparse
import json
import math
import statistics

import pandas as pd

from backtest.binance_vision import fetch_usdm_ohlcv_vision
from backtest.jianghe_scored_runner import generate_scored_multitimeframe_pullback_signals_fast

SLIPPAGE_BPS = 2.0
FEE_RATE = 0.0004
MAX_HOLD_BARS = 64
TARGET_LEVELS_R = (0.5, 1.0, 1.5, 1.8, 2.0, 2.5)


def _apply_entry_slippage(price: float, side: str) -> float:
    rate = SLIPPAGE_BPS / 10_000.0
    return float(price) * (1.0 + rate if side == "LONG" else 1.0 - rate)


def _quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    s = pd.Series(values, dtype=float)
    return float(s.quantile(q))


def _one_signal(execution: pd.DataFrame, signal) -> dict | None:
    entry_index = int(signal.index) + 1
    if entry_index >= len(execution):
        return None

    raw_entry = float(execution.loc[entry_index, "open"])
    entry = _apply_entry_slippage(raw_entry, signal.side)
    stop = float(signal.invalidation_reference)
    stop_distance = entry - stop if signal.side == "LONG" else stop - entry
    if stop_distance <= 0:
        return None

    end = min(len(execution) - 1, entry_index + MAX_HOLD_BARS - 1)
    side_sign = 1.0 if signal.side == "LONG" else -1.0
    max_favorable_r = 0.0
    max_adverse_r = 0.0
    max_favorable_bar = 0
    stopped = False
    stop_bar = None
    target_before_stop = {str(level): False for level in TARGET_LEVELS_R}
    unresolved = set(TARGET_LEVELS_R)

    for offset, i in enumerate(range(entry_index, end + 1)):
        row = execution.loc[i]
        open_i = float(row["open"])
        high = float(row["high"])
        low = float(row["low"])

        if signal.side == "LONG":
            favorable = (high - entry) / stop_distance
            adverse = (entry - low) / stop_distance
            gap_stop = open_i <= stop
            hit_stop = low <= stop
        else:
            favorable = (entry - low) / stop_distance
            adverse = (high - entry) / stop_distance
            gap_stop = open_i >= stop
            hit_stop = high >= stop

        if favorable > max_favorable_r:
            max_favorable_r = float(favorable)
            max_favorable_bar = offset
        max_adverse_r = max(max_adverse_r, float(adverse))

        # Conservative STOP_FIRST policy. If stop and an R threshold are both
        # touched in the same bar, the threshold is not credited first.
        if gap_stop or hit_stop:
            stopped = True
            stop_bar = offset
            break

        for level in tuple(unresolved):
            if favorable >= level:
                target_before_stop[str(level)] = True
                unresolved.remove(level)

    close_at_end = float(execution.loc[end, "close"])
    mark_r = side_sign * (close_at_end - entry) / stop_distance
    round_trip_friction_estimate = (
        (entry + max(entry, 1e-12)) * FEE_RATE
        + 2.0 * entry * (SLIPPAGE_BPS / 10_000.0)
    )
    friction_to_one_unit_risk = round_trip_friction_estimate / max(stop_distance, 1e-12)

    return {
        "signal_index": int(signal.index),
        "timestamp": str(signal.timestamp),
        "side": signal.side,
        "score": float(signal.metadata.get("quality_score", 0.0)),
        "entry": entry,
        "stop": stop,
        "stop_distance": stop_distance,
        "mfe_r_before_stop_or_timeout": max_favorable_r,
        "mae_r_before_stop_or_timeout": max_adverse_r,
        "mfe_bar_offset": int(max_favorable_bar),
        "stopped_within_64": stopped,
        "stop_bar_offset": stop_bar,
        "mark_r_at_64_or_data_end": float(mark_r),
        "target_before_stop": target_before_stop,
        "friction_to_price_risk_ratio_estimate": float(friction_to_one_unit_risk),
    }


def _summary(rows: list[dict]) -> dict:
    mfes = [float(r["mfe_r_before_stop_or_timeout"]) for r in rows]
    maes = [float(r["mae_r_before_stop_or_timeout"]) for r in rows]
    friction = [float(r["friction_to_price_risk_ratio_estimate"]) for r in rows]
    stopped = [r for r in rows if r["stopped_within_64"]]
    reached = {
        str(level): sum(1 for r in rows if r["target_before_stop"][str(level)])
        for level in TARGET_LEVELS_R
    }
    count = len(rows)
    return {
        "signals_analyzed": count,
        "stopped_within_64": len(stopped),
        "stop_fraction": (len(stopped) / count if count else 0.0),
        "reached_before_stop_counts": reached,
        "reached_before_stop_fractions": {
            key: (value / count if count else 0.0) for key, value in reached.items()
        },
        "mfe_r": {
            "mean": (statistics.fmean(mfes) if mfes else 0.0),
            "median": (statistics.median(mfes) if mfes else 0.0),
            "p25": _quantile(mfes, 0.25),
            "p75": _quantile(mfes, 0.75),
            "max": (max(mfes) if mfes else 0.0),
        },
        "mae_r": {
            "mean": (statistics.fmean(maes) if maes else 0.0),
            "median": (statistics.median(maes) if maes else 0.0),
            "p25": _quantile(maes, 0.25),
            "p75": _quantile(maes, 0.75),
            "max": (max(maes) if maes else 0.0),
        },
        "friction_to_price_risk_ratio_estimate": {
            "median": (statistics.median(friction) if friction else 0.0),
            "p75": _quantile(friction, 0.75),
            "max": (max(friction) if friction else 0.0),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--symbol", default="BTC/USDT")
    args = parser.parse_args()

    macro = fetch_usdm_ohlcv_vision(args.symbol, "1h", args.start, args.end, timeout_seconds=60)
    context = fetch_usdm_ohlcv_vision(args.symbol, "15m", args.start, args.end, timeout_seconds=60)
    execution = fetch_usdm_ohlcv_vision(args.symbol, "1m", args.start, args.end, timeout_seconds=60)
    signals = generate_scored_multitimeframe_pullback_signals_fast(macro, context, execution)

    rows = []
    for signal in signals:
        item = _one_signal(execution, signal)
        if item is not None:
            rows.append(item)

    payload = {
        "symbol": args.symbol,
        "start": args.start,
        "end": args.end,
        "profile": "V5_1H_15M_1M_SCORE_ONLY_DIAGNOSTIC",
        "policy": {
            "entry": "NEXT_BAR_OPEN_WITH_2BPS_ADVERSE_SLIPPAGE",
            "same_bar": "STOP_FIRST",
            "max_hold_bars": MAX_HOLD_BARS,
            "target_levels_r": list(TARGET_LEVELS_R),
            "note": "diagnostic only; no exit parameter is promoted from these windows",
        },
        "summary": _summary(rows),
        "trades": rows,
    }
    print("EXCURSION_DIAGNOSTIC_JSON=" + json.dumps(payload, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
