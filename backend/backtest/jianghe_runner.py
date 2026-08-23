from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from backtest.types import CandidateSignal
from strategy.jianghe.breakout import evaluate_breakout_continuation_from_structure
from strategy.jianghe.pullback import evaluate_trend_pullback_from_structure
from strategy.jianghe.second_push import evaluate_second_push_failure_from_structure
from strategy.jianghe.structure import classify_structure

SETUP_PULLBACK = "TREND_PULLBACK_CONTINUATION"
SETUP_BREAKOUT = "BREAKOUT_CONTINUATION"
SETUP_SECOND_PUSH = "SECOND_PUSH_FAILURE"
ALL_SETUPS = (SETUP_PULLBACK, SETUP_BREAKOUT, SETUP_SECOND_PUSH)


@dataclass(frozen=True)
class JiangheRunnerConfig:
    context_lookback: int = 120
    execution_lookback: int = 96
    min_context_bars: int = 30
    min_execution_bars: int = 24
    signal_cooldown_bars: int = 3
    enabled_setups: tuple[str, ...] = ALL_SETUPS

    def validate(self) -> None:
        if self.context_lookback < self.min_context_bars:
            raise ValueError("context_lookback must be >= min_context_bars")
        if self.execution_lookback < self.min_execution_bars:
            raise ValueError("execution_lookback must be >= min_execution_bars")
        if self.signal_cooldown_bars < 0:
            raise ValueError("signal_cooldown_bars must be >= 0")
        unknown = set(self.enabled_setups).difference(ALL_SETUPS)
        if unknown:
            raise ValueError(f"unknown setups: {sorted(unknown)}")


def _validate_frame(df: pd.DataFrame, name: str) -> pd.DataFrame:
    required = {"timestamp", "open", "high", "low", "close"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"{name} missing columns: {sorted(missing)}")
    result = df.copy()
    result["timestamp"] = pd.to_datetime(result["timestamp"], utc=True)
    return result.sort_values("timestamp").reset_index(drop=True)


def generate_jianghe_signals(
    context_bars: pd.DataFrame,
    execution_bars: pd.DataFrame,
    config: JiangheRunnerConfig | None = None,
) -> list[CandidateSignal]:
    """Generate candidate signals without look-ahead.

    Both inputs must use candle CLOSE timestamps. For each execution candle, the
    runner only exposes context candles whose close timestamp is <= the current
    execution close timestamp. Signals are therefore known only after the
    current execution candle closes; BacktestEngine enters no earlier than the
    following candle open.
    """
    cfg = config or JiangheRunnerConfig()
    cfg.validate()
    context = _validate_frame(context_bars, "context_bars")
    execution = _validate_frame(execution_bars, "execution_bars")

    signals: list[CandidateSignal] = []
    last_emitted: dict[tuple[str, str], int] = {}

    for i in range(len(execution)):
        if i + 1 < cfg.min_execution_bars:
            continue
        now = execution.loc[i, "timestamp"]
        ctx = context[context["timestamp"] <= now].tail(cfg.context_lookback)
        if len(ctx) < cfg.min_context_bars:
            continue

        ex = execution.iloc[max(0, i + 1 - cfg.execution_lookback) : i + 1]
        structure = classify_structure(ctx[["open", "high", "low", "close"]])
        evaluations = []

        if SETUP_PULLBACK in cfg.enabled_setups:
            evaluations.append(
                evaluate_trend_pullback_from_structure(
                    structure,
                    ex[["open", "high", "low", "close"]],
                )
            )
        if SETUP_BREAKOUT in cfg.enabled_setups:
            evaluations.append(
                evaluate_breakout_continuation_from_structure(
                    structure,
                    ex[["open", "high", "low", "close"]],
                )
            )
        if SETUP_SECOND_PUSH in cfg.enabled_setups:
            evaluations.append(
                evaluate_second_push_failure_from_structure(
                    structure,
                    ex[["open", "high", "low", "close"]],
                )
            )

        for evaluation in evaluations:
            if not evaluation.candidate or evaluation.side is None or evaluation.invalidation_reference is None:
                continue
            key = (evaluation.setup, evaluation.side)
            previous_index = last_emitted.get(key)
            if previous_index is not None and i - previous_index <= cfg.signal_cooldown_bars:
                continue

            signals.append(
                CandidateSignal(
                    index=i,
                    timestamp=now,
                    setup=evaluation.setup,
                    side=evaluation.side,
                    entry_reference=evaluation.entry_reference,
                    invalidation_reference=float(evaluation.invalidation_reference),
                    metadata=evaluation.to_dict(),
                )
            )
            last_emitted[key] = i

    return signals
