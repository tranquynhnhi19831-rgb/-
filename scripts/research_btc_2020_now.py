from __future__ import annotations

import argparse
import io
import json
import math
import time
import zipfile
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone

import httpx
import numpy as np
import pandas as pd

from backtest.binance_vision import _parse_kline_zip
from backtest.metrics import max_drawdown
from backtest.types import CandidateSignal
from strategy.jianghe.breakout import evaluate_breakout_continuation_from_structure
from strategy.jianghe.pullback import evaluate_trend_pullback_from_structure
from strategy.jianghe.second_push import evaluate_second_push_failure_from_structure
from strategy.jianghe.structure import classify_structure
from strategy.jianghe.types import MarketRegime

SYMBOL = "BTCUSDT"
MARKET = "BINANCE_USDT_M"
DATA_BASE = "https://data.binance.vision/data/futures/um"
SETUPS = (
    "TREND_PULLBACK_CONTINUATION",
    "BREAKOUT_CONTINUATION",
    "SECOND_PUSH_FAILURE",
)

# Current S7/Paper intent. These are system research assumptions, not a claim
# that Jianghe uses these exact numeric values.
INITIAL_EQUITY = 100.0
RISK_PER_TRADE = 0.005
FEE_RATE = 0.0004
SLIPPAGE_BPS = 2.0
REWARD_RISK = 1.8
LEVERAGE = 3.0
MAX_MARGIN_FRACTION = 0.10
MAX_HOLD_BARS = 64
MAX_TRADES_PER_DAY = 3
MAX_DAILY_LOSS = 0.02
MAX_CONSECUTIVE_LOSSES_PER_DAY = 3
SIGNAL_COOLDOWN_BARS = 3
CONTEXT_LOOKBACK = 120
EXECUTION_LOOKBACK = 96
MIN_CONTEXT_BARS = 30
MIN_EXECUTION_BARS = 24

# This long-range research run deliberately does not hard-code a historical
# Binance BTCUSDT minQty/stepSize because Binance filters can change and the
# archive does not provide a point-in-time exchangeInfo history. The result is
# therefore a strategy/execution backtest, not a proof that every tiny 100U
# order would have satisfied the historical exchange filters.


def utc_ts(value: str | pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def month_starts(start: pd.Timestamp, end: pd.Timestamp):
    cur = start.to_period("M").start_time.tz_localize("UTC")
    last = (end - pd.Timedelta(nanoseconds=1)).to_period("M").start_time.tz_localize("UTC")
    while cur <= last:
        yield cur
        cur = (cur + pd.offsets.MonthBegin(1)).to_pydatetime()
        cur = pd.Timestamp(cur, tz="UTC")


def _get_zip(client: httpx.Client, url: str) -> bytes | None:
    response = client.get(url)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.content


def fetch_vision_range(symbol: str, timeframe: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Download official Binance USD-M kline archives.

    Prefer monthly packages; fall back to daily packages for a partial/current
    month or if a monthly package is not yet published.
    """
    raw = symbol.replace("/", "").replace(":USDT", "")
    frames: list[pd.DataFrame] = []
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        for month in month_starts(start, end):
            next_month = pd.Timestamp(month + pd.offsets.MonthBegin(1))
            slice_start = max(start, month)
            slice_end = min(end, next_month)
            ym = month.strftime("%Y-%m")
            filename = f"{raw}-{timeframe}-{ym}.zip"
            monthly_url = f"{DATA_BASE}/monthly/klines/{raw}/{timeframe}/{filename}"
            payload = _get_zip(client, monthly_url)
            if payload is not None:
                frames.append(_parse_kline_zip(payload))
                continue

            first_day = slice_start.floor("D")
            last_day = (slice_end - pd.Timedelta(nanoseconds=1)).floor("D")
            for day in pd.date_range(first_day, last_day, freq="D", tz="UTC"):
                ds = day.strftime("%Y-%m-%d")
                daily_name = f"{raw}-{timeframe}-{ds}.zip"
                daily_url = f"{DATA_BASE}/daily/klines/{raw}/{timeframe}/{daily_name}"
                daily_payload = _get_zip(client, daily_url)
                if daily_payload is None:
                    # Current UTC day may not yet have a completed daily archive.
                    continue
                frames.append(_parse_kline_zip(daily_payload))

    if not frames:
        raise RuntimeError(f"no Binance Data Vision data for {raw} {timeframe} {start}..{end}")
    df = pd.concat(frames, ignore_index=True)
    df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    df = df[(df["timestamp"] >= start) & (df["timestamp"] < end)].reset_index(drop=True)
    if df.empty:
        raise RuntimeError(f"empty filtered Binance Data Vision data for {raw} {timeframe}")
    return df


def generate_signals_fast(context: pd.DataFrame, execution: pd.DataFrame) -> list[CandidateSignal]:
    """Same Jianghe evaluator logic as the repo runner, optimized for long history.

    The original runner re-filters the full context DataFrame on every 1m bar.
    This version uses searchsorted and only recomputes the 15m structure when a
    new context candle becomes visible. Signal chronology and evaluator calls
    remain the same: current 1m close -> signal -> next 1m open at earliest.
    """
    context = context.copy().sort_values("timestamp").reset_index(drop=True)
    execution = execution.copy().sort_values("timestamp").reset_index(drop=True)
    context["timestamp"] = pd.to_datetime(context["timestamp"], utc=True)
    execution["timestamp"] = pd.to_datetime(execution["timestamp"], utc=True)
    ctx_times = context["timestamp"].astype("int64").to_numpy()
    ex_times = execution["timestamp"].astype("int64").to_numpy()
    ctx_ohlc = context[["open", "high", "low", "close"]]
    ex_ohlc = execution[["open", "high", "low", "close"]]

    signals: list[CandidateSignal] = []
    last_emitted: dict[tuple[str, str], int] = {}
    last_ctx_end = -1
    structure = None
    started = time.perf_counter()

    for i, now_ns in enumerate(ex_times):
        if i + 1 < MIN_EXECUTION_BARS:
            continue
        ctx_end = int(np.searchsorted(ctx_times, now_ns, side="right"))
        if ctx_end < MIN_CONTEXT_BARS:
            continue

        if ctx_end != last_ctx_end:
            ctx_start = max(0, ctx_end - CONTEXT_LOOKBACK)
            structure = classify_structure(ctx_ohlc.iloc[ctx_start:ctx_end])
            last_ctx_end = ctx_end
        assert structure is not None

        ex_start = max(0, i + 1 - EXECUTION_LOOKBACK)
        ex = ex_ohlc.iloc[ex_start : i + 1]
        evaluations = []
        if structure.regime in {MarketRegime.BULL_TREND, MarketRegime.BEAR_TREND}:
            evaluations.append(evaluate_trend_pullback_from_structure(structure, ex))
            evaluations.append(evaluate_breakout_continuation_from_structure(structure, ex))
        if structure.regime != MarketRegime.UNKNOWN:
            evaluations.append(evaluate_second_push_failure_from_structure(structure, ex))

        for evaluation in evaluations:
            if not evaluation.candidate or evaluation.side is None or evaluation.invalidation_reference is None:
                continue
            key = (evaluation.setup, evaluation.side)
            previous = last_emitted.get(key)
            if previous is not None and i - previous <= SIGNAL_COOLDOWN_BARS:
                continue
            signals.append(
                CandidateSignal(
                    index=i,
                    timestamp=execution.loc[i, "timestamp"],
                    setup=evaluation.setup,
                    side=evaluation.side,
                    entry_reference=evaluation.entry_reference,
                    invalidation_reference=float(evaluation.invalidation_reference),
                    metadata=evaluation.to_dict(),
                )
            )
            last_emitted[key] = i

        if i and i % 100_000 == 0:
            elapsed = time.perf_counter() - started
            print(f"SIGNAL_PROGRESS bars={i} signals={len(signals)} elapsed_s={elapsed:.1f}", flush=True)

    return signals


def slip(price: float, side: str, is_entry: bool) -> float:
    rate = SLIPPAGE_BPS / 10_000.0
    if side == "LONG":
        return price * (1.0 + rate if is_entry else 1.0 - rate)
    return price * (1.0 - rate if is_entry else 1.0 + rate)


def backtest_with_s7_risk(execution: pd.DataFrame, signals: list[CandidateSignal]) -> dict:
    """Risk-aware single-position simulation matching the current S7 intent.

    Consecutive-loss cooldown is interpreted as: after 3 losses in a row, block
    new entries for the rest of that UTC day and reset the cooldown next day.
    This avoids the current Paper helper's otherwise permanent lock after the
    first global 3-loss streak and matches the documented 'cooldown' intent.
    """
    df = execution.reset_index(drop=True).copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    equity = INITIAL_EQUITY
    equity_curve = [equity]
    next_free_index = 0
    trades = []
    skipped_overlap = 0
    skipped_bad_stop = 0
    blocked_daily_limit = 0
    blocked_daily_loss = 0
    blocked_loss_cooldown = 0
    opened_by_day: dict[str, int] = defaultdict(int)
    pnl_by_day: dict[str, float] = defaultdict(float)
    consecutive_losses_by_day: dict[str, int] = defaultdict(int)
    setup_stats = defaultdict(lambda: {"trades": 0, "wins": 0, "net_pnl": 0.0, "fees": 0.0})

    for signal in sorted(signals, key=lambda s: s.index):
        if signal.index < next_free_index:
            skipped_overlap += 1
            continue
        entry_index = signal.index + 1
        if entry_index >= len(df):
            continue

        entry_day = str(df.loc[entry_index, "timestamp"].date())
        day_realized = pnl_by_day[entry_day]
        day_start_equity = max(0.0, equity - day_realized)
        if opened_by_day[entry_day] >= MAX_TRADES_PER_DAY:
            blocked_daily_limit += 1
            continue
        if day_start_equity > 0 and day_realized <= -(day_start_equity * MAX_DAILY_LOSS):
            blocked_daily_loss += 1
            continue
        if consecutive_losses_by_day[entry_day] >= MAX_CONSECUTIVE_LOSSES_PER_DAY:
            blocked_loss_cooldown += 1
            continue

        raw_entry = float(df.loc[entry_index, "open"])
        entry = slip(raw_entry, signal.side, True)
        stop = float(signal.invalidation_reference)
        stop_distance = entry - stop if signal.side == "LONG" else stop - entry
        if stop_distance <= 0:
            skipped_bad_stop += 1
            continue

        risk_amount = equity * RISK_PER_TRADE
        risk_qty = risk_amount / stop_distance
        max_notional = equity * MAX_MARGIN_FRACTION * LEVERAGE
        margin_qty = max_notional / entry
        quantity = min(risk_qty, margin_qty)
        if quantity <= 0:
            continue

        target = entry + REWARD_RISK * stop_distance if signal.side == "LONG" else entry - REWARD_RISK * stop_distance
        max_exit_index = min(len(df) - 1, entry_index + MAX_HOLD_BARS - 1)
        exit_index = max_exit_index
        exit_reason = "TIME"
        raw_exit = float(df.loc[max_exit_index, "close"])

        for i in range(entry_index, max_exit_index + 1):
            open_i = float(df.loc[i, "open"])
            high = float(df.loc[i, "high"])
            low = float(df.loc[i, "low"])
            if signal.side == "LONG" and open_i <= stop:
                raw_exit = open_i
                exit_reason = "STOP_GAP"
                exit_index = i
                break
            if signal.side == "SHORT" and open_i >= stop:
                raw_exit = open_i
                exit_reason = "STOP_GAP"
                exit_index = i
                break
            if signal.side == "LONG":
                hit_stop, hit_target = low <= stop, high >= target
            else:
                hit_stop, hit_target = high >= stop, low <= target
            if hit_stop and hit_target:
                raw_exit = stop  # conservative STOP_FIRST
                exit_reason = "STOP"
                exit_index = i
                break
            if hit_stop:
                raw_exit = stop
                exit_reason = "STOP"
                exit_index = i
                break
            if hit_target:
                raw_exit = target
                exit_reason = "TARGET"
                exit_index = i
                break

        exit_price = slip(raw_exit, signal.side, False)
        side_sign = 1.0 if signal.side == "LONG" else -1.0
        gross = side_sign * (exit_price - entry) * quantity
        entry_notional = entry * quantity
        exit_notional = exit_price * quantity
        fees = (entry_notional + exit_notional) * FEE_RATE
        net = gross - fees  # funding omitted; max hold is only 64 minutes
        equity_before = equity
        equity = max(0.0, equity + net)
        exit_day = str(df.loc[exit_index, "timestamp"].date())
        pnl_by_day[exit_day] += net
        opened_by_day[entry_day] += 1

        # Cooldown is based on consecutive realized outcomes within the UTC day
        # on which they are realized. A win resets that day's streak.
        if net < 0:
            consecutive_losses_by_day[exit_day] += 1
        else:
            consecutive_losses_by_day[exit_day] = 0

        trades.append(
            {
                "setup": signal.setup,
                "side": signal.side,
                "entry_index": entry_index,
                "exit_index": exit_index,
                "entry_timestamp": df.loc[entry_index, "timestamp"].isoformat(),
                "exit_timestamp": df.loc[exit_index, "timestamp"].isoformat(),
                "entry_price": entry,
                "exit_price": exit_price,
                "stop_price": stop,
                "target_price": target,
                "quantity": quantity,
                "gross_pnl": gross,
                "fees": fees,
                "net_pnl": net,
                "exit_reason": exit_reason,
                "equity_before": equity_before,
                "equity_after": equity,
            }
        )
        s = setup_stats[signal.setup]
        s["trades"] += 1
        s["wins"] += int(net > 0)
        s["net_pnl"] += net
        s["fees"] += fees
        equity_curve.append(equity)
        next_free_index = exit_index + 1
        if equity <= 0:
            break

    wins = [t for t in trades if t["net_pnl"] > 0]
    losses = [t for t in trades if t["net_pnl"] < 0]
    gross_profit = sum(t["net_pnl"] for t in wins)
    gross_loss = -sum(t["net_pnl"] for t in losses)
    result = {
        "initial_equity": INITIAL_EQUITY,
        "final_equity": equity,
        "total_return": equity / INITIAL_EQUITY - 1.0,
        "net_pnl": equity - INITIAL_EQUITY,
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(trades) if trades else 0.0,
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else None,
        "max_drawdown": max_drawdown(equity_curve),
        "fees": sum(t["fees"] for t in trades),
        "skipped_overlap": skipped_overlap,
        "skipped_bad_stop": skipped_bad_stop,
        "blocked_daily_limit": blocked_daily_limit,
        "blocked_daily_loss": blocked_daily_loss,
        "blocked_loss_cooldown": blocked_loss_cooldown,
        "by_setup": {},
        "equity_curve": equity_curve,
        "trades_detail": trades,
    }
    for setup, s in setup_stats.items():
        result["by_setup"][setup] = {
            **s,
            "win_rate": s["wins"] / s["trades"] if s["trades"] else 0.0,
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--end-2026", default="2026-08-23T00:00:00Z")
    args = parser.parse_args()
    year = args.year
    start = pd.Timestamp(f"{year}-01-01T00:00:00Z")
    if year == 2026:
        end = utc_ts(args.end_2026)
    else:
        end = pd.Timestamp(f"{year + 1}-01-01T00:00:00Z")
    warmup_start = start - pd.Timedelta(hours=30)

    print(f"RESEARCH_RANGE year={year} start={start} end={end}", flush=True)
    t0 = time.perf_counter()
    context = fetch_vision_range(SYMBOL, "15m", warmup_start, end)
    execution = fetch_vision_range(SYMBOL, "1m", warmup_start, end)
    print(
        f"DATA_READY context={len(context)} execution={len(execution)} elapsed_s={time.perf_counter()-t0:.1f}",
        flush=True,
    )
    signals = generate_signals_fast(context, execution)
    signals = [s for s in signals if s.timestamp is not None and start <= pd.Timestamp(s.timestamp) < end]
    print(f"SIGNALS_READY count={len(signals)} elapsed_s={time.perf_counter()-t0:.1f}", flush=True)
    result = backtest_with_s7_risk(execution, signals)
    result["year"] = year
    result["start"] = start.isoformat()
    result["end"] = end.isoformat()
    result["symbol"] = "BTC/USDT"
    result["market"] = MARKET
    result["data_source"] = "BINANCE_DATA_VISION_USDM_OFFICIAL_ARCHIVES"
    result["signals_generated"] = len(signals)
    result["context_bars"] = len(context)
    result["execution_bars"] = len(execution)
    result["assumptions"] = {
        "initial_equity": INITIAL_EQUITY,
        "risk_per_trade": RISK_PER_TRADE,
        "fee_rate_each_side": FEE_RATE,
        "slippage_bps_each_fill": SLIPPAGE_BPS,
        "reward_risk": REWARD_RISK,
        "leverage": LEVERAGE,
        "max_margin_fraction": MAX_MARGIN_FRACTION,
        "max_hold_bars_1m": MAX_HOLD_BARS,
        "max_trades_per_utc_day": MAX_TRADES_PER_DAY,
        "max_daily_loss_fraction": MAX_DAILY_LOSS,
        "max_consecutive_losses_per_utc_day": MAX_CONSECUTIVE_LOSSES_PER_DAY,
        "same_bar_policy": "STOP_FIRST",
        "funding": "OMITTED_MAX_HOLD_64M",
        "historical_exchange_filters": "NOT_POINT_IN_TIME_ARCHIVED",
    }

    # Keep logs compact; full trade detail is not printed.
    compact = {k: v for k, v in result.items() if k not in {"equity_curve", "trades_detail"}}
    print("RESULT_JSON=" + json.dumps(compact, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
