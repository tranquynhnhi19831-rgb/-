from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from backtest.metrics import summarize, summarize_by_setup
from backtest.types import BacktestConfig, BacktestResult, BacktestTrade, CandidateSignal

REQUIRED_COLUMNS = {"open", "high", "low", "close"}


def _validate_ohlc(df: pd.DataFrame) -> None:
    missing = REQUIRED_COLUMNS.difference(df.columns)
    if missing:
        raise ValueError(f"missing OHLC columns: {sorted(missing)}")
    if len(df) < 2:
        raise ValueError("backtest requires at least two bars")


def _apply_slippage(price: float, side: str, is_entry: bool, bps: float) -> float:
    rate = bps / 10_000.0
    if side == "LONG":
        return price * (1.0 + rate if is_entry else 1.0 - rate)
    return price * (1.0 - rate if is_entry else 1.0 + rate)


def _funding_cost(
    bars: pd.DataFrame,
    side: str,
    notional: float,
) -> float:
    """Return signed funding cost; positive means cost, negative means credit.

    Optional `funding_rate` rows should be zero except on funding timestamps.
    Positive rates mean longs pay shorts, matching Binance futures convention.
    """
    if "funding_rate" not in bars.columns:
        return 0.0
    rates = bars["funding_rate"].fillna(0.0).astype(float)
    side_sign = 1.0 if side == "LONG" else -1.0
    return float(notional * side_sign * rates.sum())


class BacktestEngine:
    """Single-position deterministic bar backtester.

    Execution policy is intentionally explicit and conservative:
    - signals are known at bar close;
    - entry occurs no earlier than the next bar open;
    - risk sizing uses structural invalidation;
    - margin/notional is capped for the 100U profile;
    - same-bar stop/target ambiguity defaults to STOP_FIRST;
    - fees, adverse slippage and optional funding are deducted.
    """

    def __init__(self, config: BacktestConfig | None = None) -> None:
        self.config = config or BacktestConfig()
        self.config.validate()

    def run(
        self,
        bars: pd.DataFrame,
        signals: Iterable[CandidateSignal],
    ) -> BacktestResult:
        _validate_ohlc(bars)
        df = bars.reset_index(drop=True).copy()
        cfg = self.config
        equity = float(cfg.initial_equity)
        equity_curve: list[float] = [equity]
        trades: list[BacktestTrade] = []
        skipped = 0
        next_free_index = 0

        ordered = sorted(signals, key=lambda s: s.index)
        for signal in ordered:
            signal.validate()
            if signal.index < next_free_index:
                skipped += 1
                continue
            entry_index = signal.index + 1
            if entry_index >= len(df):
                skipped += 1
                continue

            raw_entry = float(df.loc[entry_index, "open"])
            entry = _apply_slippage(raw_entry, signal.side, True, cfg.slippage_bps)
            stop = float(signal.invalidation_reference)
            if signal.side == "LONG":
                stop_distance = entry - stop
            else:
                stop_distance = stop - entry
            if stop_distance <= 0:
                skipped += 1
                continue

            risk_amount = equity * cfg.risk_per_trade
            risk_qty = risk_amount / stop_distance
            max_notional = equity * cfg.max_margin_fraction * cfg.leverage
            margin_qty = max_notional / entry
            quantity = min(risk_qty, margin_qty)
            if quantity <= 0:
                skipped += 1
                continue

            if signal.side == "LONG":
                target = entry + cfg.reward_risk * stop_distance
            else:
                target = entry - cfg.reward_risk * stop_distance

            max_exit_index = min(len(df) - 1, entry_index + cfg.max_hold_bars - 1)
            exit_index = max_exit_index
            exit_reason = "TIME"
            raw_exit = float(df.loc[max_exit_index, "close"])

            for i in range(entry_index, max_exit_index + 1):
                high = float(df.loc[i, "high"])
                low = float(df.loc[i, "low"])
                if signal.side == "LONG":
                    hit_stop = low <= stop
                    hit_target = high >= target
                else:
                    hit_stop = high >= stop
                    hit_target = low <= target

                if hit_stop and hit_target:
                    if cfg.same_bar_policy == "STOP_FIRST":
                        raw_exit = stop
                        exit_reason = "STOP"
                    else:
                        raw_exit = target
                        exit_reason = "TARGET"
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

            exit_price = _apply_slippage(raw_exit, signal.side, False, cfg.slippage_bps)
            side_sign = 1.0 if signal.side == "LONG" else -1.0
            gross_pnl = side_sign * (exit_price - entry) * quantity
            entry_notional = entry * quantity
            exit_notional = exit_price * quantity
            fees = (entry_notional + exit_notional) * cfg.fee_rate
            funding = _funding_cost(
                df.iloc[entry_index : exit_index + 1],
                signal.side,
                entry_notional,
            )
            net_pnl = gross_pnl - fees - funding
            equity_before = equity
            equity = max(0.0, equity + net_pnl)
            risk_denom = stop_distance * quantity
            r_multiple = net_pnl / risk_denom if risk_denom > 0 else 0.0

            trades.append(
                BacktestTrade(
                    setup=signal.setup,
                    side=signal.side,
                    signal_index=signal.index,
                    entry_index=entry_index,
                    exit_index=exit_index,
                    entry_price=float(entry),
                    exit_price=float(exit_price),
                    stop_price=float(stop),
                    target_price=float(target),
                    quantity=float(quantity),
                    gross_pnl=float(gross_pnl),
                    fees=float(fees),
                    funding=float(funding),
                    net_pnl=float(net_pnl),
                    r_multiple=float(r_multiple),
                    exit_reason=exit_reason,
                    equity_before=float(equity_before),
                    equity_after=float(equity),
                )
            )
            equity_curve.append(equity)
            next_free_index = exit_index + 1
            if equity <= 0:
                break

        metrics = summarize(trades, equity_curve, cfg.initial_equity)
        metrics["skipped_signals"] = skipped
        metrics["setup_count"] = len({t.setup for t in trades})
        metrics["by_setup"] = summarize_by_setup(trades)  # type: ignore[assignment]

        return BacktestResult(
            config=cfg,
            trades=tuple(trades),
            metrics=metrics,
            equity_curve=tuple(equity_curve),
            skipped_signals=skipped,
        )
