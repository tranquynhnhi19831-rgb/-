from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from backtest.types import CandidateSignal
from strategy.jianghe.pullback_event import EventPullbackConfig, evaluate_event_pullback_from_structure
from strategy.jianghe.structure import classify_structure
from strategy.jianghe.types import MarketRegime, StructureSnapshot


@dataclass(frozen=True)
class MultiTimeframeRunnerConfig:
    """Research-only 1h -> 15m -> 1m Jianghe pullback pipeline.

    The 1h structure supplies the broad directional bias, the 15m structure
    supplies the tradable structural location/state, and the 1m event-driven
    evaluator supplies the execution trigger. All three inputs use candle-close
    timestamps and are revealed only when their close time is <= the current
    1m close, preserving the existing no-lookahead convention.
    """

    macro_lookback: int = 120
    context_lookback: int = 120
    execution_lookback: int = 64
    min_macro_bars: int = 30
    min_context_bars: int = 30
    min_execution_bars: int = 16
    signal_cooldown_bars: int = 6
    min_macro_efficiency: float = 0.18
    min_context_efficiency: float = 0.22
    require_macro_context_same_direction: bool = True
    event_config: EventPullbackConfig = field(default_factory=EventPullbackConfig)

    def validate(self) -> None:
        if self.macro_lookback < self.min_macro_bars:
            raise ValueError("macro_lookback must be >= min_macro_bars")
        if self.context_lookback < self.min_context_bars:
            raise ValueError("context_lookback must be >= min_context_bars")
        if self.execution_lookback < self.min_execution_bars:
            raise ValueError("execution_lookback must be >= min_execution_bars")
        if self.signal_cooldown_bars < 0:
            raise ValueError("signal_cooldown_bars must be >= 0")
        if not 0.0 <= self.min_macro_efficiency <= 1.0:
            raise ValueError("min_macro_efficiency must be between 0 and 1")
        if not 0.0 <= self.min_context_efficiency <= 1.0:
            raise ValueError("min_context_efficiency must be between 0 and 1")


def _frame(df: pd.DataFrame, name: str) -> pd.DataFrame:
    required = {"timestamp", "open", "high", "low", "close"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"{name} missing columns: {sorted(missing)}")
    out = df.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
    return out.sort_values("timestamp").reset_index(drop=True)


def _trend_direction(structure: StructureSnapshot) -> int:
    if structure.regime == MarketRegime.BULL_TREND:
        return 1
    if structure.regime == MarketRegime.BEAR_TREND:
        return -1
    return 0


def _structure_is_directionally_valid(structure: StructureSnapshot, min_efficiency: float) -> bool:
    direction = _trend_direction(structure)
    return (
        direction != 0
        and structure.trend_efficiency >= min_efficiency
        and structure.net_direction == direction
    )


def multitimeframe_alignment_allowed(
    macro: StructureSnapshot,
    context: StructureSnapshot,
    config: MultiTimeframeRunnerConfig | None = None,
) -> bool:
    """Return whether 1h and 15m context are strong/aligned enough for V4.

    This is intentionally coarse. It tests the missing multi-timeframe idea
    without optimizing a large parameter surface: both structures must be
    confirmed directional trends, recent path direction must agree with each
    structure, and (by default) the 1h and 15m trend directions must match.
    """

    cfg = config or MultiTimeframeRunnerConfig()
    cfg.validate()
    if not _structure_is_directionally_valid(macro, cfg.min_macro_efficiency):
        return False
    if not _structure_is_directionally_valid(context, cfg.min_context_efficiency):
        return False
    if cfg.require_macro_context_same_direction:
        return _trend_direction(macro) == _trend_direction(context)
    return True


def generate_multitimeframe_event_pullback_signals_fast(
    macro_bars: pd.DataFrame,
    context_bars: pd.DataFrame,
    execution_bars: pd.DataFrame,
    config: MultiTimeframeRunnerConfig | None = None,
) -> list[CandidateSignal]:
    """Generate research V4 signals using 1h bias, 15m state, 1m trigger.

    No future macro/context candle is visible early: both higher-timeframe end
    indices are located with ``searchsorted(..., side='right')`` against the
    current 1m candle close. Structures are reclassified only when a new closed
    higher-timeframe bar becomes visible. The same confirmed 1m pullback swing
    may emit at most one signal; a new swing event is required before re-entry.
    """

    cfg = config or MultiTimeframeRunnerConfig()
    cfg.validate()
    macro = _frame(macro_bars, "macro_bars")
    context = _frame(context_bars, "context_bars")
    execution = _frame(execution_bars, "execution_bars")

    macro_times = macro["timestamp"].astype("int64").to_numpy()
    ctx_times = context["timestamp"].astype("int64").to_numpy()
    ex_times = execution["timestamp"].astype("int64").to_numpy()
    macro_ohlc = macro[["open", "high", "low", "close"]]
    ctx_ohlc = context[["open", "high", "low", "close"]]
    ex_ohlc = execution[["open", "high", "low", "close"]]

    signals: list[CandidateSignal] = []
    last_emitted: dict[str, int] = {}
    seen_events: set[tuple[str, int]] = set()
    last_macro_end = -1
    last_ctx_end = -1
    macro_structure: StructureSnapshot | None = None
    context_structure: StructureSnapshot | None = None

    for i, now_ns in enumerate(ex_times):
        if i + 1 < cfg.min_execution_bars:
            continue

        macro_end = int(np.searchsorted(macro_times, now_ns, side="right"))
        ctx_end = int(np.searchsorted(ctx_times, now_ns, side="right"))
        if macro_end < cfg.min_macro_bars or ctx_end < cfg.min_context_bars:
            continue

        if macro_end != last_macro_end:
            macro_start = max(0, macro_end - cfg.macro_lookback)
            macro_structure = classify_structure(macro_ohlc.iloc[macro_start:macro_end])
            last_macro_end = macro_end

        if ctx_end != last_ctx_end:
            ctx_start = max(0, ctx_end - cfg.context_lookback)
            context_structure = classify_structure(ctx_ohlc.iloc[ctx_start:ctx_end])
            last_ctx_end = ctx_end

        assert macro_structure is not None
        assert context_structure is not None
        if not multitimeframe_alignment_allowed(macro_structure, context_structure, cfg):
            continue

        ex_start = max(0, i + 1 - cfg.execution_lookback)
        ex = ex_ohlc.iloc[ex_start : i + 1]
        evaluation = evaluate_event_pullback_from_structure(
            context_structure,
            ex,
            cfg.event_config,
        )
        if not evaluation.candidate or evaluation.side is None or evaluation.invalidation_reference is None:
            continue
        if evaluation.pullback_end_index is None:
            continue

        event_anchor = ex_start + int(evaluation.pullback_end_index)
        event_key = (evaluation.side, event_anchor)
        if event_key in seen_events:
            continue

        previous = last_emitted.get(evaluation.side)
        if previous is not None and i - previous <= cfg.signal_cooldown_bars:
            continue

        metadata = evaluation.to_dict()
        metadata.update(
            {
                "event_pullback_index_abs": int(event_anchor),
                "macro_timeframe": "1h",
                "macro_regime": macro_structure.regime.value,
                "macro_efficiency": float(macro_structure.trend_efficiency),
                "macro_net_direction": int(macro_structure.net_direction),
                "context_timeframe": "15m",
                "context_regime": context_structure.regime.value,
                "context_efficiency": float(context_structure.trend_efficiency),
                "execution_timeframe": "1m",
                "multitimeframe_alignment": True,
            }
        )
        signals.append(
            CandidateSignal(
                index=i,
                timestamp=execution.loc[i, "timestamp"],
                setup="TREND_PULLBACK_EVENT_V4_MTF",
                side=evaluation.side,
                entry_reference=evaluation.entry_reference,
                invalidation_reference=float(evaluation.invalidation_reference),
                metadata=metadata,
            )
        )
        seen_events.add(event_key)
        last_emitted[evaluation.side] = i

    return signals
