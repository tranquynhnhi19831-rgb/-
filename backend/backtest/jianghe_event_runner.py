from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from backtest.types import CandidateSignal
from strategy.jianghe.pullback_event import EventPullbackConfig, evaluate_event_pullback_from_structure
from strategy.jianghe.structure import classify_structure
from strategy.jianghe.types import MarketRegime, StructureSnapshot


@dataclass(frozen=True)
class EventPullbackRunnerConfig:
    context_lookback: int = 120
    execution_lookback: int = 64
    min_context_bars: int = 30
    min_execution_bars: int = 16
    signal_cooldown_bars: int = 6
    event_config: EventPullbackConfig = field(default_factory=EventPullbackConfig)

    def validate(self) -> None:
        if self.context_lookback < self.min_context_bars:
            raise ValueError("context_lookback must be >= min_context_bars")
        if self.execution_lookback < self.min_execution_bars:
            raise ValueError("execution_lookback must be >= min_execution_bars")
        if self.signal_cooldown_bars < 0:
            raise ValueError("signal_cooldown_bars must be >= 0")


def _frame(df: pd.DataFrame, name: str) -> pd.DataFrame:
    required = {"timestamp", "open", "high", "low", "close"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"{name} missing columns: {sorted(missing)}")
    out = df.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
    return out.sort_values("timestamp").reset_index(drop=True)


def generate_event_pullback_signals_fast(
    context_bars: pd.DataFrame,
    execution_bars: pd.DataFrame,
    config: EventPullbackRunnerConfig | None = None,
) -> list[CandidateSignal]:
    """Generate V3 event-driven pullback signals without look-ahead.

    Context structure is recalculated only when a new higher-timeframe candle is
    visible. Lower-timeframe phases are inferred from confirmed swings inside the
    execution window; `find_confirmed_swings` itself requires right-side bars, so
    an execution pivot cannot be used before it is confirmed.
    """

    cfg = config or EventPullbackRunnerConfig()
    cfg.validate()
    context = _frame(context_bars, "context_bars")
    execution = _frame(execution_bars, "execution_bars")

    ctx_times = context["timestamp"].astype("int64").to_numpy()
    ex_times = execution["timestamp"].astype("int64").to_numpy()
    ctx_ohlc = context[["open", "high", "low", "close"]]
    ex_ohlc = execution[["open", "high", "low", "close"]]

    signals: list[CandidateSignal] = []
    last_emitted: dict[str, int] = {}
    last_ctx_end = -1
    structure: StructureSnapshot | None = None

    for i, now_ns in enumerate(ex_times):
        if i + 1 < cfg.min_execution_bars:
            continue
        ctx_end = int(np.searchsorted(ctx_times, now_ns, side="right"))
        if ctx_end < cfg.min_context_bars:
            continue

        if ctx_end != last_ctx_end:
            ctx_start = max(0, ctx_end - cfg.context_lookback)
            structure = classify_structure(ctx_ohlc.iloc[ctx_start:ctx_end])
            last_ctx_end = ctx_end
        assert structure is not None
        if structure.regime not in {MarketRegime.BULL_TREND, MarketRegime.BEAR_TREND}:
            continue

        ex_start = max(0, i + 1 - cfg.execution_lookback)
        ex = ex_ohlc.iloc[ex_start : i + 1]
        evaluation = evaluate_event_pullback_from_structure(structure, ex, cfg.event_config)
        if not evaluation.candidate or evaluation.side is None or evaluation.invalidation_reference is None:
            continue

        previous = last_emitted.get(evaluation.side)
        if previous is not None and i - previous <= cfg.signal_cooldown_bars:
            continue

        metadata = evaluation.to_dict()
        metadata["runner_context_efficiency"] = float(structure.trend_efficiency)
        signals.append(
            CandidateSignal(
                index=i,
                timestamp=execution.loc[i, "timestamp"],
                setup=evaluation.setup,
                side=evaluation.side,
                entry_reference=evaluation.entry_reference,
                invalidation_reference=float(evaluation.invalidation_reference),
                metadata=metadata,
            )
        )
        last_emitted[evaluation.side] = i

    return signals
